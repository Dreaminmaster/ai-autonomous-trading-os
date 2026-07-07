"""Structured evidence summary generator. Reads canonical JSON, receives upstream job results."""
from __future__ import annotations
import json
from pathlib import Path

SCHEMA_VERSION = 1
REQUIRED_CANONICAL_KEYS = ("total_trades","profit_total_pct","winrate","max_drawdown_pct","profit_factor")
VALID_LA_FINAL = frozenset({"PASS","PASS_WITH_RC_ANOMALY"})
LA_REQUIRED_KEYS = ("schema_version","parser_status","has_bias","fatal_markers_found","final_status","freqtrade_returncode","explicit_no_bias_evidence")
MANIFEST_REQUIRED_KEYS = ("schema_version","run_id","head_sha","job")

def _read_json(path):
    p = Path(path)
    if not p.exists(): return None, f"MISSING: {path}"
    try: raw = p.read_bytes()
    except OSError as e: return None, f"UNREADABLE: {path} ({e})"
    try: decoded = json.loads(raw)
    except (json.JSONDecodeError,UnicodeDecodeError) as e: return None, f"INVALID JSON: {path} ({e})"
    if not isinstance(decoded,dict): return None, f"NOT A DICT: {path} (got {type(decoded).__name__})"
    return decoded, None

def _read_text(path):
    p = Path(path)
    if not p.exists(): return None, f"MISSING: {path}"
    try: return p.read_text(), None
    except OSError as e: return None, f"UNREADABLE: {path} ({e})"

def _exact_int(val, label, errors):
    if type(val) is not int: errors.append(f"{label} not int: {type(val).__name__} ({val})")
    elif val < 0: errors.append(f"{label} negative: {val}")
    return type(val) is int and val >= 0

def _exact_finite(val, label, errors):
    if isinstance(val,bool): errors.append(f"{label} is bool")
    elif not isinstance(val,(int,float)): errors.append(f"{label} not numeric: {type(val).__name__} ({val})")
    else:
        try:
            f=float(val)
            if f!=f: errors.append(f"{label} is NaN")
            elif f in (float("inf"),float("-inf")): errors.append(f"{label} is Inf")
        except: errors.append(f"{label} not floatable: {val}")
    return isinstance(val,(int,float)) and not isinstance(val,bool) and float(val)==float(val) and float(val) not in (float("inf"),float("-inf"))

def _validate_manifest(manifest, run_id, sha, expected_job, errors):
    if manifest is None: errors.append("manifest missing"); return
    for k in MANIFEST_REQUIRED_KEYS:
        if k not in manifest: errors.append(f"manifest missing key: {k}")
    if manifest.get("schema_version") != 1: errors.append(f"manifest schema_version != 1: {manifest.get('schema_version')}")
    if manifest.get("run_id") != run_id: errors.append(f"manifest run_id mismatch: {manifest.get('run_id')} != {run_id}")
    if manifest.get("head_sha") != sha: errors.append(f"manifest head_sha mismatch")
    if manifest.get("job") != expected_job: errors.append(f"manifest job mismatch")

def _validate_la(la, errors):
    if la is None: return
    for k in LA_REQUIRED_KEYS:
        if k not in la: errors.append(f"LA missing key: {k}"); return
    if type(la.get("schema_version")) is not int or la.get("schema_version")!=1: errors.append(f"LA bad schema_version: {la.get('schema_version')}")
    if la.get("parser_status") != "PASS": errors.append(f"LA parser_status != PASS: {la.get('parser_status')}")
    if la.get("has_bias") is not False: errors.append(f"LA has_bias != False: {la.get('has_bias')}")
    fm = la.get("fatal_markers_found")
    if not isinstance(fm,list) or fm != []: errors.append(f"LA fatal_markers_found != []: {fm}")
    fs = la.get("final_status")
    if fs not in VALID_LA_FINAL: errors.append(f"LA final_status invalid: {fs}")
    rc = la.get("freqtrade_returncode")
    if type(rc) is not int: errors.append(f"LA freqtrade_returncode not int: {type(rc).__name__}")
    elif isinstance(rc,bool): errors.append(f"LA freqtrade_returncode is bool")
    enb = la.get("explicit_no_bias_evidence")
    if type(enb) is not bool: errors.append(f"LA explicit_no_bias_evidence not bool: {type(enb).__name__}")
    if fs == "PASS" and rc != 0: errors.append(f"LA PASS but rc={rc}")
    if fs == "PASS_WITH_RC_ANOMALY":
        if rc == 0: errors.append("LA PASS_WITH_RC_ANOMALY but rc=0")
        if enb is not True: errors.append("LA PASS_WITH_RC_ANOMALY but explicit_no_bias_evidence is not True")

def _validate_round1(r1, run_id, sha, errors, freq_dir):
    if r1 is None: errors.append("round1 missing"); return
    if r1.get("schema_version") != 1: errors.append(f"round1 schema_version: {r1.get('schema_version')}")
    if r1.get("run_id") != run_id: errors.append(f"round1 run_id mismatch: {r1.get('run_id')} != {run_id}")
    if r1.get("head_sha") != sha: errors.append("round1 head_sha mismatch")
    bi = r1.get("baseline_integrity","FAIL")
    if bi != "PASS": errors.append(f"round1 baseline_integrity={bi}")
    bm = r1.get("baseline_metrics")
    if not isinstance(bm,dict): errors.append(f"round1 baseline_metrics not dict: {type(bm).__name__}")
    else:
        for k in REQUIRED_CANONICAL_KEYS:
            if bm.get(k) != "PASS": errors.append(f"round1 baseline_metrics.{k}={bm.get(k)}")
    sv = r1.get("selected_variants",[])
    if not isinstance(sv,list) or not sv: errors.append(f"round1 selected_variants empty or not list")
    else:
        for v in sv:
            if not isinstance(v,dict): errors.append(f"round1 variant not dict: {v}"); continue
            vn = v.get("variant","")
            if not vn: errors.append("round1 variant name empty")
            sf = v.get("lookahead_status_file","")
            if not sf: errors.append(f"round1 variant {vn} status_file empty")
            else:
                rp = Path(freq_dir) / sf
                if ".." in sf or not rp.resolve().is_relative_to(Path(freq_dir).resolve()):
                    errors.append(f"round1 variant {vn} path traversal: {sf}")
                elif not rp.exists():
                    errors.append(f"round1 variant {vn} status file missing: {sf}")
                else:
                    la_data, la_err = _read_json(str(rp))
                    if la_err: errors.append(f"round1 variant {vn} LA {la_err}")
                    else: _validate_la(la_data, errors)

def generate_summary(head_sha,run_id,atos_job,freq_job,atos_dir,freq_dir):
    errors=[]
    a_dir=Path(atos_dir); f_dir=Path(freq_dir)
    if atos_job!="success": errors.append(f"atos-tests: {atos_job}")
    if freq_job!="success": errors.append(f"freqtrade: {freq_job}")
    
    am,err=_read_json(a_dir/"evidence_manifest.json")
    if err: errors.append(err)
    _validate_manifest(am,run_id,head_sha,"atos-tests",errors)
    
    fm,err=_read_json(f_dir/"evidence_manifest.json")
    if err: errors.append(err)
    _validate_manifest(fm,run_id,head_sha,"freqtrade",errors)
    
    canonical={}
    can,err=_read_json(f_dir/"freqtrade_data/backtest_results/canonical_baseline_summary.json")
    if err: errors.append(err); canonical={k:"ERROR" for k in REQUIRED_CANONICAL_KEYS}
    else:
        for k in REQUIRED_CANONICAL_KEYS:
            v=can.get(k)
            if k=="total_trades": _exact_int(v,f"canonical.{k}",errors)
            else: _exact_finite(v,f"canonical.{k}",errors)
            canonical[k]=v
        cr=can.get("run_id")
        if cr!=run_id: errors.append(f"canonical run_id mismatch: {cr} != {run_id}")
        for fld,exp in [("baseline_integrity","CONFIRMED"),("pair_universe_integrity","PASS"),("cache_mode","none")]:
            if can.get(fld)!=exp: errors.append(f"canonical.{fld}={can.get(fld)} != {exp}")
    
    la,err=_read_json(f_dir/"freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json")
    if err: canonical["lookahead_final_status"]="ERROR"; errors.append(err)
    else: _validate_la(la,errors); canonical["lookahead_final_status"]=la.get("final_status","ERROR")
    
    round1={}
    r1,err=_read_json(f_dir/"validation_reports/strategy_fix_round1.json")
    if err: round1["report_present"]=False; errors.append(err)
    else:
        round1["report_present"]=True
        _validate_round1(r1,run_id,head_sha,errors,freq_dir)
        round1["baseline_integrity"]=r1.get("baseline_integrity","FAIL")
    
    s={"schema_version":SCHEMA_VERSION,"run_id":run_id,"head_sha":head_sha,
       "atos_job_result":atos_job,"freqtrade_job_result":freq_job,
       "canonical":canonical,"round1":round1,"live":"FORBIDDEN","errors":errors}
    return s,errors

def summary_pass(s,errors):
    if errors: return False
    if s.get("atos_job_result")!="success": return False
    if s.get("freqtrade_job_result")!="success": return False
    c=s.get("canonical",{})
    for k in REQUIRED_CANONICAL_KEYS:
        v=c.get(k)
        if v is None or v=="ERROR": return False
    if c.get("lookahead_final_status") not in VALID_LA_FINAL: return False
    if s.get("round1",{}).get("baseline_integrity")!="PASS": return False
    if s.get("round1",{}).get("report_present") is not True: return False
    return True
