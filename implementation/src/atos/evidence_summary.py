"""Structured evidence summary generator. Reads canonical JSON, receives upstream job results.

Never uses substring parsing for truth. Required upstream results are authoritative.
"""
from __future__ import annotations
import json
from pathlib import Path

SCHEMA_VERSION = 1

REQUIRED_CANONICAL_KEYS = ("total_trades", "profit_total_pct", "winrate", "max_drawdown_pct", "profit_factor")
VALID_LA_FINAL = frozenset({"PASS", "PASS_WITH_RC_ANOMALY"})


def _read_json(path):
    p = Path(path)
    if not p.exists():
        return None, f"MISSING: {path}"
    try:
        raw = p.read_bytes()
    except OSError as e:
        return None, f"UNREADABLE: {path} ({e})"
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        return None, f"INVALID JSON: {path} ({e})"
    if not isinstance(decoded, dict):
        return None, f"NOT A DICT: {path} (got {type(decoded).__name__})"
    return decoded, None


def _read_text(path):
    p = Path(path)
    if not p.exists():
        return None, f"MISSING: {path}"
    try:
        return p.read_text(), None
    except OSError as e:
        return None, f"UNREADABLE: {path} ({e})"


def _validate_number(val, label, errors):
    if val is None:
        errors.append(f"{label} is None")
        return
    if isinstance(val, bool):
        errors.append(f"{label} is bool ({val})")
        return
    try:
        f = float(val)
        if f != f or f in (float("inf"), float("-inf")):
            errors.append(f"{label} is NaN/Inf")
    except (TypeError, ValueError):
        errors.append(f"{label} is not numeric: {type(val).__name__} ({val})")


def _validate_manifest(manifest, expected_run_id, expected_head_sha, expected_job, errors):
    if manifest is None:
        errors.append("manifest missing")
        return
    for k in ("run_id", "head_sha", "job"):
        if k not in manifest:
            errors.append(f"manifest missing key: {k}")
    if manifest.get("run_id") != expected_run_id:
        errors.append(f"manifest run_id mismatch: {manifest.get('run_id')} != {expected_run_id}")
    if manifest.get("head_sha") != expected_head_sha:
        errors.append(f"manifest head_sha mismatch: {manifest.get('head_sha')} != {expected_head_sha}")
    if manifest.get("job") != expected_job:
        errors.append(f"manifest job mismatch: {manifest.get('job')} != {expected_job}")


def _validate_la_status(la, errors):
    if la is None:
        return
    if la.get("schema_version") != 1:
        errors.append(f"LA schema_version != 1: {la.get('schema_version')}")
    if la.get("parser_status") != "PASS":
        errors.append(f"LA parser_status != PASS: {la.get('parser_status')}")
    if la.get("has_bias") is not False:
        errors.append(f"LA has_bias != False: {la.get('has_bias')}")
    fatal = la.get("fatal_markers_found")
    if fatal is not None and fatal != []:
        errors.append(f"LA fatal_markers_found != []: {fatal}")
    fs = la.get("final_status")
    if fs not in VALID_LA_FINAL:
        errors.append(f"LA final_status invalid: {fs}")
    if fs == "PASS":
        if la.get("freqtrade_returncode") != 0:
            errors.append(f"LA PASS but freqtrade_returncode != 0: {la.get('freqtrade_returncode')}")
    if fs == "PASS_WITH_RC_ANOMALY":
        if la.get("explicit_no_bias_evidence") is not True:
            errors.append("LA PASS_WITH_RC_ANOMALY but explicit_no_bias_evidence is not True")
        if la.get("freqtrade_returncode") == 0:
            errors.append("LA PASS_WITH_RC_ANOMALY but freqtrade_returncode == 0")


def generate_summary(
    head_sha,
    run_id,
    atos_job_result,
    freqtrade_job_result,
    atos_dir,
    freq_dir,
):
    errors = []
    a_dir = Path(atos_dir)
    f_dir = Path(freq_dir)

    # ═══════ P3: upstream job truth (authoritative) ═══════
    if atos_job_result != "success":
        errors.append(f"atos-tests job result: {atos_job_result}")
    if freqtrade_job_result != "success":
        errors.append(f"freqtrade job result: {freqtrade_job_result}")

    # ═══════ P4: manifests ═══════
    atos_manifest, err = _read_json(a_dir / "evidence_manifest.json")
    if err: errors.append(err)
    _validate_manifest(atos_manifest, run_id, head_sha, "atos-tests", errors)

    freq_manifest, err = _read_json(f_dir / "evidence_manifest.json")
    if err: errors.append(err)
    _validate_manifest(freq_manifest, run_id, head_sha, "freqtrade", errors)

    # ═══════ Canonical ═══════
    canonical = {}
    can, err = _read_json(f_dir / "freqtrade_data/backtest_results/canonical_baseline_summary.json")
    if err:
        errors.append(err)
        canonical = {k: "ERROR" for k in REQUIRED_CANONICAL_KEYS}
    else:
        for k in REQUIRED_CANONICAL_KEYS:
            v = can.get(k)
            _validate_number(v, f"canonical.{k}", errors)
            canonical[k] = v
        for field in ("baseline_integrity", "pair_universe_integrity", "cache_mode"):
            v = can.get(field)
            expected = {"baseline_integrity": "CONFIRMED", "pair_universe_integrity": "PASS", "cache_mode": "none"}.get(field)
            if v != expected:
                errors.append(f"canonical.{field} = {v!r}, expected {expected!r}")

    # ═══════ Lookahead ═══════
    la, err = _read_json(f_dir / "freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json")
    if err:
        canonical["lookahead_final_status"] = "ERROR"
        errors.append(err)
    else:
        _validate_la_status(la, errors)
        canonical["lookahead_final_status"] = la.get("final_status", "ERROR")

    # ═══════ P2: Round1 JSON (not markdown) ═══════
    round1 = {}
    r1, err = _read_json(f_dir / "validation_reports/strategy_fix_round1.json")
    if err:
        round1["report_present"] = False
        errors.append(err)
    else:
        round1["report_present"] = True
        bi = r1.get("baseline_integrity", "FAIL")
        round1["baseline_integrity"] = bi
        if bi != "PASS":
            errors.append(f"round1 baseline_integrity = {bi}")
        bm = r1.get("baseline_metrics", {})
        for k in REQUIRED_CANONICAL_KEYS:
            if bm.get(k) != "PASS":
                errors.append(f"round1 baseline_metrics.{k} = {bm.get(k)}")
        selected = r1.get("selected_variants", [])
        if not selected:
            errors.append("round1 selected_variants is empty")
        for sv in selected:
            laf = sv.get("lookahead_final_status", "?")
            if laf not in VALID_LA_FINAL:
                errors.append(f"round1 variant {sv.get('variant')} LA status = {laf}")

    summary = {
        "schema_version": SCHEMA_VERSION,
        "run_id": run_id,
        "head_sha": head_sha,
        "atos_job_result": atos_job_result,
        "freqtrade_job_result": freqtrade_job_result,
        "canonical": canonical,
        "round1": round1,
        "live": "FORBIDDEN",
        "errors": errors,
    }
    return summary, errors


def summary_pass(summary, errors):
    if errors:
        return False
    if summary.get("atos_job_result") != "success":
        return False
    if summary.get("freqtrade_job_result") != "success":
        return False
    can = summary.get("canonical", {})
    for k in REQUIRED_CANONICAL_KEYS:
        v = can.get(k)
        if v is None or v == "ERROR":
            return False
    if can.get("lookahead_final_status") not in VALID_LA_FINAL:
        return False
    r1 = summary.get("round1", {})
    if r1.get("baseline_integrity") != "PASS":
        return False
    return True
