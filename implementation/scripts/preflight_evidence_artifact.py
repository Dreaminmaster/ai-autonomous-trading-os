#!/usr/bin/env python3
"""Preflight evidence artifact validation."""
import json, os, sys
from pathlib import Path
def fail(msg): print(f"PREFLIGHT FAIL: {msg}"); sys.exit(1)
mode = sys.argv[1] if len(sys.argv)>1 else fail("usage: atos-tests|freqtrade")
rid = os.environ["GITHUB_RUN_ID"]; sha = os.environ["GITHUB_SHA"]
def exists(path,label):
    p=Path(path)
    if not p.exists(): fail(label+" missing: "+path)
    if not p.is_file(): fail(label+" not file: "+path)
def jdict(path,label):
    exists(path,label)
    try: d=json.loads(Path(path).read_text())
    except Exception as e: fail(label+" JSON: "+str(e))
    if not isinstance(d,dict): fail(label+" not dict")
    return d
def chk_manifest(path):
    d=jdict(path,"manifest")
    sv=d.get("schema_version")
    if type(sv) is not int or sv!=1: fail("manifest schema_version != 1")
    if d.get("run_id")!=rid: fail("manifest run_id mismatch")
    if d.get("head_sha")!=sha: fail("manifest head_sha mismatch")
    if d.get("job")!=mode: fail("manifest job mismatch")
if mode=="atos-tests":
    chk_manifest("evidence_manifest.json");exists("pytest.log","pytest");exists("no_secret_scan.log","secret");exists("freqtrade_data/backtest_results/walk_forward_report.json","wfr")
elif mode=="freqtrade":
    chk_manifest("evidence_manifest.json");exists("freqtrade_data/backtest_results/canonical_baseline_summary.json","can_sum");exists("freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json","can_la")
    r1=jdict("validation_reports/strategy_fix_round1.json","round1");sv=r1.get("selected_variants")
    if not isinstance(sv,list) or not sv: fail("selected_variants empty")
    for v in sv:
        if not isinstance(v,dict): fail("variant not dict")
        sf=v.get("lookahead_status_file")
        if not isinstance(sf,str) or not sf.strip(): fail("la sf bad")
        rp=Path(sf)
        if ".." in sf or not rp.resolve().is_relative_to(Path.cwd().resolve()): fail("path traversal: "+sf)
        la=jdict(sf,"la_"+v.get("variant","?"))
        if la.get("variant")!=v.get("variant",""): fail("la variant mismatch")
        if la.get("final_status")!=v.get("lookahead_final_status"): fail("copied status mismatch")
        for k in ("schema_version","parser_status","has_bias","fatal_markers_found","final_status","freqtrade_returncode","explicit_no_bias_evidence"):
            if k not in la: fail("la missing key: "+k)
else: fail("unknown mode: "+mode)
print("PREFLIGHT "+mode+" PASS")

