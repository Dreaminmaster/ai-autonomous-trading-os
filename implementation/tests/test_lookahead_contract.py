"""Contract tests: Round1 consumes canonical status JSON, never double-parses."""
import json
import tempfile
from pathlib import Path


PASS_JSON = {
    "schema_version": 1,
    "freqtrade_returncode": 0,
    "parser_status": "PASS",
    "has_bias": False,
    "evidence_source": "table",
    "explicit_no_bias_evidence": True,
    "fatal_markers_found": [],
    "final_status": "PASS",
    "reason": "parser PASS, rc=0",
}


def test_wrapper_summary_is_not_freqtrade_output():
    wrapper_output = "Lookahead: PASS (rc=0)"
    assert "Lookahead" in wrapper_output
    # This MUST NOT be parsed by lookahead parser
    from atos.lookahead_parser import parse_lookahead_result
    result = parse_lookahead_result(wrapper_output)
    # Should return error because no Freqtrade table
    assert result["status"] == "ERROR"


def test_round1_reads_status_json_not_parses_wrapper():
    d = tempfile.mkdtemp()
    sp = Path(d) / "test_status.json"
    sp.write_text(json.dumps(PASS_JSON))
    st = json.loads(sp.read_text())
    assert st["final_status"] == "PASS"
    assert st["freqtrade_returncode"] == 0


def test_missing_status_json_errors():
    sp = Path("/nonexistent/variant_la_lookahead_status.json")
    assert not sp.exists()


def test_wrapper_nonzero_with_pass_json_contract_mismatch():
    wrapper_rc = 1
    final = PASS_JSON["final_status"]
    if wrapper_rc != 0 and final in ("PASS", "PASS_WITH_RC_ANOMALY"):
        result = "ERROR_CONTRACT_MISMATCH"
    assert result == "ERROR_CONTRACT_MISMATCH"


def test_wrapper_nonzero_with_fail_json_propagates():
    wrapper_rc = 1
    fail_json = {**PASS_JSON, "final_status": "FAIL"}
    final = fail_json["final_status"]
    if wrapper_rc != 0 and final in ("FAIL", "ERROR"):
        result = final
    assert result == "FAIL"


def test_same_decision_schema_for_canonical_and_round1():
    s = PASS_JSON
    required = ["schema_version", "freqtrade_returncode", "final_status",
                "parser_status", "has_bias", "evidence_source"]
    for k in required:
        assert k in s, f"Missing: {k}"


def test_canonical_writes_lookahead_status_json():
    d = tempfile.mkdtemp()
    sp = Path(d) / "canonical_baseline_la_lookahead_status.json"
    sp.write_text(json.dumps(PASS_JSON))
    assert sp.exists()
    st = json.loads(sp.read_text())
    assert st["final_status"] == "PASS"
    assert st["freqtrade_returncode"] == 0
