"""Production-path contract tests: call consume_lookahead_status (real consumer).

Version 2: corrected wrapper contract, immutability enforced.
"""
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
FAIL_JSON = {**PASS_JSON, "final_status": "FAIL", "has_bias": True}
ERROR_JSON = {**PASS_JSON, "final_status": "ERROR", "has_bias": None}

def _write(d, path):
    path.write_text(json.dumps(d))


# ── P2: Normal-path tests (wrapper_rc=0 → accept canonical verdict) ─

def test_wrapper0_accepts_pass():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(PASS_JSON, p)
    r = consume_lookahead_status(0, p)
    assert r["lookahead"] == "PASS"
    assert r["contract_status"] == "ok"


def test_wrapper0_accepts_pass_with_rc_anomaly():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(PASS_ANOMALY_JSON, p)
    r = consume_lookahead_status(0, p)
    assert r["lookahead"] == "PASS_WITH_RC_ANOMALY"
    assert r["contract_status"] == "ok"


def test_wrapper_nonzero_pass_is_contract_mismatch():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(PASS_JSON, p)
    r = consume_lookahead_status(1, p)
    assert r["lookahead"] == "ERROR_CONTRACT_MISMATCH"
    assert r["contract_status"] == "mismatch"


def test_wrapper_nonzero_pass_anomaly_is_contract_mismatch():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(PASS_ANOMALY_JSON, p)
    r = consume_lookahead_status(1, p)
    assert r["lookahead"] == "ERROR_CONTRACT_MISMATCH"
    assert r["contract_status"] == "mismatch"


def test_wrapper0_fail_propagates():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(FAIL_JSON, p)
    r = consume_lookahead_status(0, p)
    assert r["lookahead"] == "ERROR_CONTRACT:FAIL"
    assert r["contract_status"] == "error"


def test_wrapper_nonzero_fail_propagates():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(FAIL_JSON, p)
    r = consume_lookahead_status(1, p)
    assert r["lookahead"] == "FAIL"
    assert r["contract_status"] == "ok"


def test_preserves_freqtrade_returncode():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(PASS_JSON, p)
    r = consume_lookahead_status(0, p)
    assert r["freqtrade_returncode"] == 0


# ── Exception-path tests ─────────────────────────────────────

def test_missing_json_errors():
    p = Path("/nonexistent/v_lookahead_status.json")
    r = consume_lookahead_status(0, p)
    assert r["lookahead"] == "ERROR_MISSING_EVIDENCE"


def test_invalid_json_errors():
    p = Path(tempfile.mkdtemp()) / "status.json"
    p.write_text("not json {")
    r = consume_lookahead_status(0, p)
    assert "MALFORMED" in r["lookahead"]


def test_unknown_schema_errors():
    p = Path(tempfile.mkdtemp()) / "status.json"
    d = dict(PASS_JSON)
    d["schema_version"] = 999
    _write(d, p)
    r = consume_lookahead_status(0, p)
    assert "UNKNOWN_SCHEMA" in r["lookahead"]


def test_bare_dict_no_schema_errors():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write({}, p)
    r = consume_lookahead_status(0, p)
    assert r["contract_status"] == "error"


# ── P3: Immutability test ────────────────────────────────────

def test_consumer_is_read_only():
    p = Path(tempfile.mkdtemp()) / "status.json"
    _write(PASS_JSON, p)
    original = p.read_bytes()
    _ = consume_lookahead_status(0, p)
    after = p.read_bytes()
    assert after == original, "Canonical status JSON must be IMMUTABLE"


# ── P4: Integration test ─────────────────────────────────────

def test_round1_integration_path():
    """Simulate Round1: consume, extract lookahead, verify schema."""
    p = Path(tempfile.mkdtemp()) / "round1_2_la_lookahead_status.json"
    _write(PASS_JSON, p)
    wrapper_rc = 0
    c = consume_lookahead_status(wrapper_rc, p)
    b_lookahead = c["lookahead"]
    assert b_lookahead == "PASS"
    assert b_lookahead != "PASS" or c["contract_status"] == "ok"
    # Verify original unchanged
    after = json.loads(p.read_text())
    assert after["schema_version"] == 1
    assert after["final_status"] == "PASS"
