"""Evidence summary generator contract tests — P0-P6."""
import json, tempfile, pathlib, pytest
from atos.evidence_summary import generate_summary, summary_pass

def _mk(*items):
    d = tempfile.mkdtemp()
    for it in items:
        p = pathlib.Path(d) / it["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        content = it["content"]
        p.write_text(content if isinstance(content,str) else json.dumps(content))
    return d

def _man(run_id, sha, job):
    return {"schema_version":1,"run_id":run_id,"head_sha":sha,"job":job}

def _can():
    return {"total_trades":244,"profit_total_pct":-16.12,"winrate":44.67,
            "max_drawdown_pct":17.85,"profit_factor":0.75,
            "baseline_integrity":"CONFIRMED","pair_universe_integrity":"PASS","cache_mode":"none","run_id":"run1"}

def _la_pass():
    return {"schema_version":1,"parser_status":"PASS","has_bias":False,
            "fatal_markers_found":[],"final_status":"PASS","freqtrade_returncode":0,"explicit_no_bias_evidence":False,"variant":"v1_la","output_base":"v1_la"}

def _la_anom():
    return {"schema_version":1,"parser_status":"PASS","has_bias":False,
            "fatal_markers_found":[],"final_status":"PASS_WITH_RC_ANOMALY",
            "freqtrade_returncode":1,"explicit_no_bias_evidence":True,"variant":"v1_la","output_base":"v1_la"}

def _r1():
    return {"schema_version":1,"run_id":"run1","head_sha":"s1","baseline_integrity":"PASS",
            "baseline_metrics":{k:"PASS" for k in
            ["total_trades","profit_total_pct","winrate","max_drawdown_pct","profit_factor"]},
            "selected_variants":[{"variant":"v1","lookahead_variant":"v1_la","lookahead_status_file":"freqtrade_data/backtest_results/v1_la_lookahead_status.json","lookahead_final_status":"PASS"}]}

# P0+P3
def test_atos_upstream_fails():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")})
    s,e=generate_summary("s1","run1","failure","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_freqtrade_upstream_fails():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")})
    s,e=generate_summary("s1","run1","success","failure",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

# P4
def test_atos_sha_mismatch():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","WRONG","atos-tests")})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_freq_sha_mismatch():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","WRONG","freqtrade")})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_run_id_mismatch():
    d=_mk({"path":"evidence_manifest.json","content":_man("WRONG","s1","atos-tests")})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_manifest_missing():
    d=tempfile.mkdtemp()
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_manifest_invalid_json():
    d=_mk({"path":"evidence_manifest.json","content":"not json"})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

# P1
def test_partial_canonical_fails():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_summary.json","content":{"total_trades":244}})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_canonical_nan():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    c=_can();c["profit_total_pct"]=float("nan")
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_summary.json","content":c})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_canonical_bool():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    c=_can();c["total_trades"]=True
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_summary.json","content":c})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

# P5
def test_la_fake_minimal():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_summary.json","content":_can()},
           {"path":"validation_reports/strategy_fix_round1.json","content":_r1()},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json",
            "content":{"final_status":"PASS","variant":"v1_la","output_base":"v1_la"}})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_la_anom_no_evidence():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    la=_la_anom();la["explicit_no_bias_evidence"]=False
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_summary.json","content":_can()},
           {"path":"validation_reports/strategy_fix_round1.json","content":_r1()},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json","content":la})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_la_with_fatal():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    la=_la_pass();la["fatal_markers_found"]=["Traceback"]
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_summary.json","content":_can()},
           {"path":"validation_reports/strategy_fix_round1.json","content":_r1()},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json","content":la})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_la_has_bias_true():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    la=_la_pass();la["has_bias"]=True
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_summary.json","content":_can()},
           {"path":"validation_reports/strategy_fix_round1.json","content":_r1()},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json","content":la})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

# P6
def test_root_array():
    d=_mk({"path":"evidence_manifest.json","content":"[]"})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_root_string():
    d=_mk({"path":"evidence_manifest.json","content":"\"PASS\""})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

def test_root_number():
    d=_mk({"path":"evidence_manifest.json","content":"1"})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is False

# Success
def test_full_pass():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_summary.json","content":_can()},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json","content":_la_pass()},
           {"path":"validation_reports/strategy_fix_round1.json","content":_r1()},
           {"path":"freqtrade_data/backtest_results/v1_la_lookahead_status.json","content":_la_pass()})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is True
    assert "?" not in json.dumps(s)

def test_anomaly_pass():
    d=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","atos-tests")})
    fd=_mk({"path":"evidence_manifest.json","content":_man("run1","s1","freqtrade")},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_summary.json","content":_can()},
           {"path":"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json","content":_la_anom()},
           {"path":"validation_reports/strategy_fix_round1.json","content":_r1()},
           {"path":"freqtrade_data/backtest_results/v1_la_lookahead_status.json","content":_la_pass()})
    s,e=generate_summary("s1","run1","success","success",d,fd,simple_ci_job="success")
    assert summary_pass(s,e) is True
