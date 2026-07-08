"""Structured evidence summary generator + atomic writer + CLI.

Usage: python -m atos.evidence_summary <head_sha> <run_id> <atos_result> <freq_result> <atos_dir> <freq_dir>
Exit 0 on PASS, nonzero on FAIL.
"""
from __future__ import annotations
import json, os, sys, tempfile
from pathlib import Path

SCHEMA_VERSION = 1
REQUIRED_CANONICAL_KEYS = ("total_trades","profit_total_pct","winrate","max_drawdown_pct","profit_factor")
VALID_LA_FINAL = frozenset({"PASS","PASS_WITH_RC_ANOMALY"})
LA_REQUIRED_KEYS = ("schema_version","parser_status","has_bias","fatal_markers_found","final_status","freqtrade_returncode","explicit_no_bias_evidence")
MANIFEST_REQUIRED_KEYS = ("schema_version","run_id","head_sha","job")

def _validate_simple_ci_evidence(sci, expected_head_sha):
    errs = []
    if not isinstance(sci, dict):
        errs.append(f"simple_ci not dict: {type(sci).__name__}")
        return errs
    for k in ("schema_version","workflow_id","workflow_path","run_id","head_sha","status","conclusion","verified"):
        if k not in sci: errs.append(f"simple_ci missing key: {k}")
    sv = sci.get("schema_version")
    if type(sv) is not int or sv != 1: errs.append(f"simple_ci schema_version not int(1): {sv}")
    if sci.get("workflow_id") is None or type(sci.get("workflow_id")) is not int: errs.append("simple_ci workflow_id missing/wrong type")
    EXPECTED_CI_WORKFLOW_ID = 305746223  # .github/workflows/ci.yml
    if sci.get("workflow_id") != EXPECTED_CI_WORKFLOW_ID: errs.append("simple_ci wrong workflow_id: " + str(sci.get("workflow_id")) + " != " + str(EXPECTED_CI_WORKFLOW_ID))
    if sci.get("workflow_path") != ".github/workflows/ci.yml": errs.append("simple_ci wrong workflow_path")
    if sci.get("head_sha") != expected_head_sha: errs.append("simple_ci head_sha mismatch")
    if sci.get("status") != "completed": errs.append("simple_ci not completed")
    if sci.get("conclusion") != "success": errs.append("simple_ci not success")
    if sci.get("verified") is not True: errs.append("simple_ci verified is not True")
    return errs

def _read_json(path):
    p=Path(path)
    if not p.exists(): return None,f"MISSING:{path}"
    try: raw=p.read_bytes()
    except OSError as e: return None,f"UNREADABLE:{path}({e})"
    try: d=json.loads(raw)
    except (json.JSONDecodeError,UnicodeDecodeError) as e: return None,f"INVALID JSON:{path}({e})"
    if not isinstance(d,dict): return None,f"NOT DICT:{path}({type(d).__name__})"
    return d,None

def _read_text(path):
    p=Path(path)
    if not p.exists(): return None,f"MISSING:{path}"
    try: return p.read_text(),None
    except OSError as e: return None,f"UNREADABLE:{path}({e})"

def _exact_int(val,label,errors):
    if type(val) is not int: errors.append(f"{label} not int: {type(val).__name__}"); return False
    if val<0: errors.append(f"{label} negative: {val}"); return False
    return True

def _exact_finite(val,label,errors):
    if isinstance(val,bool): errors.append(f"{label} is bool"); return False
    if not isinstance(val,(int,float)): errors.append(f"{label} not numeric: {type(val).__name__}"); return False
    f=float(val)
    if f!=f: errors.append(f"{label} is NaN"); return False
    if f in (float("inf"),float("-inf")): errors.append(f"{label} is Inf"); return False
    return True

def _validate_manifest(manifest,run_id,sha,expected_job,errors):
    if manifest is None: errors.append("manifest missing"); return
    for k in MANIFEST_REQUIRED_KEYS:
        if k not in manifest: errors.append(f"manifest missing key: {k}")
    sv=manifest.get("schema_version")
    if type(sv) is not int or sv!=1: errors.append(f"manifest schema_version not int(1): type={type(sv).__name__} val={sv}")
    if manifest.get("run_id")!=run_id: errors.append("manifest run_id mismatch")
    if manifest.get("head_sha")!=sha: errors.append("manifest head_sha mismatch")
    if manifest.get("job")!=expected_job: errors.append("manifest job mismatch")

def _validate_la(la,errors):
    if la is None: return
    for k in LA_REQUIRED_KEYS:
        if k not in la: errors.append(f"LA missing key: {k}"); return
    if type(la.get("schema_version")) is not int or la.get("schema_version")!=1: errors.append(f"LA bad schema_version")
    if la.get("parser_status")!="PASS": errors.append("LA parser_status!=PASS")
    if la.get("has_bias") is not False: errors.append("LA has_bias!=False")
    fm=la.get("fatal_markers_found")
    if not isinstance(fm,list) or fm!=[]: errors.append("LA fatal_markers_found!=[]")
    fs=la.get("final_status")
    if fs not in VALID_LA_FINAL: errors.append(f"LA final_status invalid: {fs}")
    rc=la.get("freqtrade_returncode")
    if type(rc) is not int: errors.append(f"LA freqtrade_returncode not int: {type(rc).__name__}")
    enb=la.get("explicit_no_bias_evidence")
    if type(enb) is not bool: errors.append(f"LA explicit_no_bias_evidence not bool: {type(enb).__name__}")
    if fs=="PASS" and rc!=0: errors.append("LA PASS but rc!=0")
    if fs=="PASS_WITH_RC_ANOMALY":
        if rc==0: errors.append("LA PASS_WITH_RC_ANOMALY but rc=0")
        if enb is not True: errors.append("LA PASS_WITH_RC_ANOMALY but enb!=True")

def _validate_round1(r1,run_id,sha,errors,freq_dir):
    if r1 is None: errors.append("round1 missing"); return
    sv=r1.get("schema_version")
    if type(sv) is not int or sv!=1: errors.append(f"round1 schema_version: {sv}")
    if r1.get("run_id")!=run_id: errors.append("round1 run_id mismatch")
    if r1.get("head_sha")!=sha: errors.append("round1 head_sha mismatch")
    if r1.get("baseline_integrity")!="PASS": errors.append("round1 baseline_integrity!=PASS")
    bm=r1.get("baseline_metrics")
    if not isinstance(bm,dict): errors.append("round1 baseline_metrics not dict")
    else:
        for k in REQUIRED_CANONICAL_KEYS:
            if bm.get(k)!="PASS": errors.append(f"round1 bm.{k}={bm.get(k)}")
    sv_list=r1.get("selected_variants")
    if not isinstance(sv_list,list) or not sv_list: errors.append("round1 selected_variants empty or not list")
    else:
        for v in sv_list:
            if not isinstance(v,dict): errors.append(f"round1 variant not dict: {type(v).__name__}"); continue
            vn=v.get("variant")
            if not isinstance(vn,str) or not vn.strip(): errors.append(f"round1 variant name bad: {vn}"); continue
            lv=v.get("lookahead_variant","")
            if not isinstance(lv,str) or not lv.strip(): errors.append(f"round1 variant {vn} lookahead_variant empty/bad")
            elif lv!=vn+"_la": errors.append(f"round1 variant {vn} lookahead_variant contract: {lv} != {vn}_la")
            sf=v.get("lookahead_status_file")
            if not isinstance(sf,str) or not sf.strip(): errors.append(f"round1 variant {vn} status_file bad: {sf}"); continue
            cp_fs=v.get("lookahead_final_status")
            if cp_fs not in VALID_LA_FINAL: errors.append(f"round1 variant {vn} copied status bad: {cp_fs}")
            freq_p=Path(freq_dir)
            rp=freq_p/sf
            if ".." in sf or not rp.resolve().is_relative_to(freq_p.resolve()):
                errors.append(f"round1 variant {vn} path traversal: {sf}")
                continue
            la_data,la_err=_read_json(str(rp))
            if la_err: errors.append(f"round1 variant {vn} LA {la_err}"); continue
            _validate_la(la_data,errors)
            actual_fs=la_data.get("final_status","?")
            if actual_fs!=cp_fs: errors.append(f"round1 variant {vn} fs mismatch: copied={cp_fs} actual={actual_fs}")
            la_variant=la_data.get("variant")
            lv_expected=v.get("lookahead_variant","")
            if not isinstance(la_variant,str) or not la_variant.strip():
                errors.append(f"round1 variant {vn} LA variant missing/empty/bad: {type(la_variant).__name__}")
            elif la_variant!=lv_expected:
                errors.append(f"round1 variant {vn} identity mismatch: la.variant={la_variant} != {lv_expected}")
            ob=la_data.get("output_base","")
            if not isinstance(ob,str) or not ob:
                errors.append(f"round1 variant {vn} LA output_base empty/bad")
            elif ob!=lv_expected:
                errors.append(f"round1 variant {vn} output_base mismatch: {ob} != {lv_expected}")

def generate_summary(head_sha,run_id,atos_job,freq_job,atos_dir,freq_dir,simple_ci_evidence=None):
    errors=[]
    a_dir=Path(atos_dir); f_dir=Path(freq_dir)
    if atos_job!="success": errors.append(f"atos-tests: {atos_job}")
    if freq_job!="success": errors.append(f"freqtrade: {freq_job}")
    if simple_ci_evidence is not None:
        sci_errs = _validate_simple_ci_evidence(simple_ci_evidence, head_sha)
        errors.extend(sci_errs)
    
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
        if cr!=run_id: errors.append(f"canonical run_id mismatch: {cr}!={run_id}")
        for fld,exp in [("baseline_integrity","CONFIRMED"),("pair_universe_integrity","PASS"),("cache_mode","none")]:
            if can.get(fld)!=exp: errors.append(f"canonical.{fld}={can.get(fld)}!={exp}")
    
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
       "simple_ci": simple_ci_evidence,
       "gate_status":"FAIL","canonical":canonical,"round1":round1,"live":"FORBIDDEN","errors":errors}
    if summary_pass(s,errors): s["gate_status"]="PASS"
    return s,errors

def summary_pass(s,errors):
    if errors: return False
    if s.get("atos_job_result")!="success": return False
    if s.get("freqtrade_job_result")!="success": return False
    sci=s.get("simple_ci")
    if sci is None: return False
    if sci.get("verified") is not True: return False
    if sci.get("head_sha") != s.get("head_sha"): return False
    c=s.get("canonical",{})
    for k in REQUIRED_CANONICAL_KEYS:
        v=c.get(k)
        if v is None or v=="ERROR": return False
    if c.get("lookahead_final_status") not in VALID_LA_FINAL: return False
    if s.get("round1",{}).get("baseline_integrity")!="PASS": return False
    if s.get("round1",{}).get("report_present") is not True: return False
    return True

# ═══════ Atomic writer ═══════
def write_json_atomic(filepath, data):
    p=Path(filepath)
    p.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=p.parent,prefix=".tmp_",suffix=".json")
    try:
        with open(fd,"w") as f: json.dump(data,f,indent=2); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,p)
    except:
        try: os.unlink(tmp)
        except: pass
        raise

# ═══════ CLI ═══════
def _cli():
    if len(sys.argv)!=8:
        print("Usage: python -m atos.evidence_summary <head_sha> <run_id> <atos_result> <freq_result> <simple_ci_result> <atos_dir> <freq_dir>",file=sys.stderr)
        sys.exit(2)
    sha,run_id,aj,fj,ad,fd=sys.argv[1:7]
    sci_evidence_path = sys.argv[7] if len(sys.argv)>7 else None
    sci_evidence = None
    if sci_evidence_path:
        sci_evidence = json.loads(Path(sci_evidence_path).read_text())
    s,err=generate_summary(sha,run_id,aj,fj,ad,fd,simple_ci_evidence=sci_evidence)
    s["gate_status"]="FAIL"
    if summary_pass(s,err): s["gate_status"]="PASS"
    write_json_atomic("validation_summary.json",s)
    md=["# Validation Report","","| Field | Value |","|-------|-------|",
        f"| Run ID | {run_id} |",f"| Head SHA | {sha} |",
        f"| Status | {s['gate_status']} |",f"| Live | FORBIDDEN |","",
        f"| Canonical Trades | {s.get('canonical',{}).get('total_trades','?')} |",
        f"| Canonical PnL | {s.get('canonical',{}).get('profit_total_pct','?')}% |",
        f"| Lookahead | {s.get('canonical',{}).get('lookahead_final_status','?')} |",
        f"| Errors | {len(err)} |",""]
    Path("validation_summary.md").write_text("\n".join(md))
    sys.exit(0 if s["gate_status"]=="PASS" else 1)

if __name__=="__main__": _cli()
