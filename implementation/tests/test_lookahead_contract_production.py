"""Production-path contract tests: call consume_lookahead_status (real consumer)."""
import json
import tempfile
from pathlib import Path
from atos.lookahead_contract import consume_lookahead_status


PASS_JSON = {
    "schema_version": 1,
    "freqtrade_returncode": 0,
    "parser_status": "PASS",
    "has_bias": False,
    "evidence_source": "table",
    "final_status": "PASS",
    "reason": "parser PASS, rc=0",
}

PASS_ANOMALY_JSON = {**PASS_JSON, "final_status": "PASS_WITH_RC_ANOMALY", "freqtrade_returncode": 1}
FAIL_JSON = {**PASS_JSON, "final_status": "FAIL", "has_bias": True, "freqtrade_returncode": 0}
ERROR_JSON = {**PASS_JSON, "final_status": "ERROR", "has_bias": None}

def _write(d, path):
    path.write_text(json.dumps(d))


# ── P1: Normal-path tests ───────────────────────────────────

def test_consumer_accepts_wrapper0_pass():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(PASS_JSON, p)
    r = consume_lookahead_status(0, p)
    assert r["lookahead"] == "PASS"
    assert r["contract_status"] == "ok"


def test_consumer_accepts_pass_with_rc_anomaly():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(PASS_ANOMALY_JSON, p)
    r = consume_lookahead_status(1, p)
    assert r["lookahead"] == "PASS_WITH_RC_ANOMALY"
    assert r["contract_status"] == "mismatch"


def test_consumer_wrapper_nonzero_fail_propagates():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(FAIL_JSON, p)
    r = consume_lookahead_status(1, p)
    assert r["lookahead"] == "FAIL"
    assert r["contract_status"] == "ok"


def test_consumer_preserves_freqtrade_returncode():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(PASS_JSON, p)
    r = consume_lookahead_status(0, p)
    assert r["freqtrade_returncode"] == 0


# ── P2: Exception-path tests ─────────────────────────────────

def test_consumer_missing_json_errors():
    p = Path("/nonexistent/variant_la.json")
    r = consume_lookahead_status(0, p)
    assert r["lookahead"] == "ERROR_MISSING_EVIDENCE"
    assert r["contract_status"] == "error"


def test_consumer_invalid_json_errors():
    p = Path(tempfile.mkdtemp()) / "status.json"
    p.write_text("not json {{{")
    r = consume_lookahead_status(0, p)
    assert r["contract_status"] == "error"
    assert "MALFORMED" in r["lookahead"]


def test_consumer_unknown_schema_errors():
    p = Path(tempfile.mkdtemp()) / "status.json"
    d = dict(PASS_JSON)
    d["schema_version"] = 999
    _write(d, p)
    r = consume_lookahead_status(0, p)
    assert r["contract_status"] == "error"
    assert "UNKNOWN_SCHEMA" in r["lookahead"]


def test_consumer_bare_dict_no_schema_errors():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write({}, p)
    r = consume_lookahead_status(0, p)
    assert r["contract_status"] == "error"


def test_consumer_wrapper1_error_json_propagates():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(ERROR_JSON, p)
    r = consume_lookahead_status(1, p)
    assert r["lookahead"] == "ERROR"
    assert r["contract_status"] == "ok"


def test_consumer_has_bias_preserved():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(FAIL_JSON, p)
    r = consume_lookahead_status(0, p)
    assert r["has_bias"] is True
