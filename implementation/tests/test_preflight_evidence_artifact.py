"""Preflight validation contract tests."""
import json, os, tempfile, pathlib, subprocess, sys, pytest

PREFLIGHT = str(pathlib.Path(__file__).resolve().parents[1] / "scripts" / "preflight_evidence_artifact.py")

def _run(mode, files, env_extra=None):
    d = tempfile.mkdtemp()
    for name,content in files.items():
        p = pathlib.Path(d) / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, dict): content = json.dumps(content)
        p.write_text(content)
    env = os.environ.copy()
    env["GITHUB_RUN_ID"] = "run42"
    env["GITHUB_SHA"] = "abc123"
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([sys.executable, PREFLIGHT, mode], capture_output=True, text=True, cwd=d, env=env)
    return r.returncode, r.stdout, r.stderr

def _pass(mode, files, **kw):
    rc, out, err = _run(mode, files, **kw)
    assert rc == 0, f"expected PASS got rc={rc}\nSTDOUT: {out}\nSTDERR: {err}"

def _fail(mode, files, **kw):
    rc, out, err = _run(mode, files, **kw)
    assert rc != 0, f"expected FAIL got rc=0"

def _manifest(job="atos-tests"):
    return {"schema_version":1,"run_id":"run42","head_sha":"abc123","job":job}

# ═══ ATOS ═══
def test_atos_pass():
    _pass("atos-tests", {"evidence_manifest.json": _manifest(), "pytest.log":"x", "no_secret_scan.log":"x", "freqtrade_data/backtest_results/walk_forward_report.json":"x"})

def test_atos_missing_manifest(): _fail("atos-tests", {"pytest.log":"x","no_secret_scan.log":"x","freqtrade_data/backtest_results/walk_forward_report.json":"x"})
def test_atos_invalid_manifest(): m=_manifest(); m["schema_version"]="bad"; _fail("atos-tests", {"evidence_manifest.json":m,"pytest.log":"x","no_secret_scan.log":"x","freqtrade_data/backtest_results/walk_forward_report.json":"x"})
def test_atos_manifest_non_dict(): _fail("atos-tests", {"evidence_manifest.json":"[]","pytest.log":"x","no_secret_scan.log":"x","freqtrade_data/backtest_results/walk_forward_report.json":"x"})
def test_atos_wrong_run_id(): m=_manifest(); m["run_id"]="wrong"; _fail("atos-tests", {"evidence_manifest.json":m,"pytest.log":"x","no_secret_scan.log":"x","freqtrade_data/backtest_results/walk_forward_report.json":"x"})
def test_atos_wrong_head_sha(): m=_manifest(); m["head_sha"]="wrong"; _fail("atos-tests", {"evidence_manifest.json":m,"pytest.log":"x","no_secret_scan.log":"x","freqtrade_data/backtest_results/walk_forward_report.json":"x"})
def test_atos_wrong_job(): m=_manifest("wrong"); _fail("atos-tests", {"evidence_manifest.json":m,"pytest.log":"x","no_secret_scan.log":"x","freqtrade_data/backtest_results/walk_forward_report.json":"x"})

# ═══ FREQTRADE base ═══
def _la_pass():
    return {"schema_version":1,"variant":"v1_la","output_base":"v1_la","parser_status":"PASS","has_bias":False,"fatal_markers_found":[],"final_status":"PASS","freqtrade_returncode":0,"explicit_no_bias_evidence":False,"evidence_source":"table","reason":"ok","evidence_log":"/tmp/x"}

def _r1():
    return {"schema_version":1,"run_id":"run42","head_sha":"abc123","baseline_integrity":"PASS","baseline_metrics":{k:"PASS"for k in["total_trades","profit_total_pct","winrate","max_drawdown_pct","profit_factor"]},"selected_variants":[{"variant":"v1","lookahead_variant":"v1_la","lookahead_status_file":"freqtrade_data/backtest_results/v1_la_lookahead_status.json","lookahead_final_status":"PASS"}]}

def test_freq_pass():
    _pass("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{"total_trades":244},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":_la_pass()})

# ═══ missing files ═══
def test_freq_missing_cs(): _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade")})
def test_freq_missing_la(): _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{}})
def test_freq_missing_r1(): _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass()})
def test_freq_empty_sv(): r1=_r1();r1["selected_variants"]=[]; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":r1})
def test_freq_missing_ref_la(): _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1()})
def test_freq_traversal(): r1=_r1();r1["selected_variants"][0]["lookahead_status_file"]="../evil"; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":r1})

# ═══ identity ═══
def test_la_variant_mismatch(): la=_la_pass();la["variant"]="wrong"; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_la_fs_mismatch(): la=_la_pass();la["final_status"]="FAIL"; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_la_ob_mismatch(): la=_la_pass();la["output_base"]="wrong"; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})

# ═══ LA schema ═══
def test_la_sv_bool(): la=_la_pass();la["schema_version"]=True; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_la_rc_bool(): la=_la_pass();la["freqtrade_returncode"]=True; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_la_hb_bad(): la=_la_pass();la["has_bias"]=42; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_la_fm_not_list(): la=_la_pass();la["fatal_markers_found"]="x"; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_la_ps_unknown(): la=_la_pass();la["parser_status"]="BOGUS"; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_la_fs_unknown(): la=_la_pass();la["final_status"]="BOGUS"; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_la_missing_es(): la=_la_pass();del la["evidence_source"]; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_la_reason_non_str(): la=_la_pass();la["reason"]=42; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})

# ═══ cross-field invariants ═══
def test_pass_nonzero_rc(): la=_la_pass();la["freqtrade_returncode"]=1; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_pass_bias_true(): la=_la_pass();la["has_bias"]=True; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_pass_fatal(): la=_la_pass();la["fatal_markers_found"]=["x"]; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_anomaly_rc_zero(): la=_la_pass();la["final_status"]="PASS_WITH_RC_ANOMALY";la["freqtrade_returncode"]=0;la["explicit_no_bias_evidence"]=True; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_anomaly_no_enb(): la=_la_pass();la["final_status"]="PASS_WITH_RC_ANOMALY";la["freqtrade_returncode"]=1;la["explicit_no_bias_evidence"]=False; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_anomaly_bias_true(): la=_la_pass();la["final_status"]="PASS_WITH_RC_ANOMALY";la["freqtrade_returncode"]=1;la["explicit_no_bias_evidence"]=True;la["has_bias"]=True; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
def test_anomaly_fatal(): la=_la_pass();la["final_status"]="PASS_WITH_RC_ANOMALY";la["freqtrade_returncode"]=1;la["explicit_no_bias_evidence"]=True;la["fatal_markers_found"]=["x"]; _fail("freqtrade", {"evidence_manifest.json":_manifest("freqtrade"),"freqtrade_data/backtest_results/canonical_baseline_summary.json":{},"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json":_la_pass(),"validation_reports/strategy_fix_round1.json":_r1(),"freqtrade_data/backtest_results/v1_la_lookahead_status.json":la})
