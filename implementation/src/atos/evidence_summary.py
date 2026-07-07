"""Structured evidence summary generator. Reads canonical JSON, never greps text."""
from __future__ import annotations
import json
from pathlib import Path

SCHEMA_VERSION = 1

def _read_json(path):
    p = Path(path)
    if not p.exists():
        return None, f"MISSING: {path}"
    try:
        return json.loads(p.read_text()), None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        return None, f"INVALID: {path} ({e})"

def _read_text(path):
    p = Path(path)
    if not p.exists():
        return None, f"MISSING: {path}"
    try:
        return p.read_text(), None
    except (OSError, UnicodeDecodeError) as e:
        return None, f"UNREADABLE: {path} ({e})"

def generate_summary(head_sha, run_id, atos_dir, freq_dir):
    errors = []
    a_dir = Path(atos_dir)
    f_dir = Path(freq_dir)
    
    # ATOS
    atos_result = "UNKNOWN"
    secret_result = "UNKNOWN"
    plog, err = _read_text(a_dir / "pytest.log")
    if err: errors.append(err)
    elif plog and "passed" in plog.split("\n")[-5:][0] if len(plog.split("\n")) >= 5 else "passed" in plog:
        atos_result = "PASSED"
    else: atos_result = "FAILED"; errors.append("pytest not passed")
    
    slog, err = _read_text(a_dir / "no_secret_scan.log")
    if err: errors.append(err)
    elif slog and "No secret" in slog: secret_result = "CLEAN"
    else: secret_result = "FAILED"; errors.append("secret scan not clean")
    
    # Canonical
    canonical = {}
    can, err = _read_json(f_dir / "freqtrade_data/backtest_results/canonical_baseline_summary.json")
    if err: errors.append(err)
    if can:
        canonical = {
            "trades": can.get("total_trades", "ERROR"),
            "profit_total_pct": can.get("profit_total_pct", "ERROR"),
            "winrate": can.get("winrate", "ERROR"),
            "max_drawdown_pct": can.get("max_drawdown_pct", "ERROR"),
            "profit_factor": can.get("profit_factor", "ERROR"),
        }
    else: canonical = {"trades": "ERROR", "profit_total_pct": "ERROR", "winrate": "ERROR", "max_drawdown_pct": "ERROR", "profit_factor": "ERROR"}
    
    la, err = _read_json(f_dir / "freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json")
    if err: canonical["lookahead_final_status"] = "ERROR"; errors.append(err)
    elif la: canonical["lookahead_final_status"] = la.get("final_status", "ERROR")
    else: canonical["lookahead_final_status"] = "ERROR"
    
    # Round1
    round1 = {}
    rr, err = _read_text(f_dir / "validation_reports/strategy_fix_round1.md")
    if err: round1["report_present"] = False; errors.append(err)
    else: round1["report_present"] = True; round1["baseline_integrity"] = "PASS" if "Baseline integrity: PASS" in (rr or "") else "FAIL"
    
    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "head_sha": head_sha,
        "atos_tests_result": atos_result,
        "secret_scan_result": secret_result,
        "canonical": canonical,
        "round1": round1,
        "live": "FORBIDDEN",
        "errors": errors,
    }
    return summary, errors

def summary_pass(summary, errors):
    if errors: return False
    if summary.get("atos_tests_result") != "PASSED": return False
    if summary.get("secret_scan_result") != "CLEAN": return False
    lf = summary.get("canonical", {}).get("lookahead_final_status", "?")
    if lf not in ("PASS", "PASS_WITH_RC_ANOMALY"): return False
    return True
