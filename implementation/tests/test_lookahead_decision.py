"""Shared decision engine tests."""
from atos.lookahead_decision import decide_lookahead

PASS_PARSED = {"status": "PASS", "has_bias": False, "evidence_source": "table"}
FAIL_PARSED = {"status": "FAIL", "has_bias": True, "evidence_source": "log"}
ERROR_PARSED = {"status": "ERROR", "has_bias": None, "evidence_source": "error"}


def test_same_input_same_decision():
    d1 = decide_lookahead(0, PASS_PARSED, "no bias detected")
    d2 = decide_lookahead(0, PASS_PARSED, "no bias detected")
    assert d1["final_status"] == d2["final_status"]


def test_rc0_pass():
    d = decide_lookahead(0, PASS_PARSED, "no bias detected\nhas_bias  │   No")
    assert d["final_status"] == "PASS"


def test_parser_fail_always_fails():
    d = decide_lookahead(0, FAIL_PARSED, "")
    assert d["final_status"] == "FAIL"


def test_parser_error_errors():
    d = decide_lookahead(0, ERROR_PARSED, "")
    assert d["final_status"] == "ERROR"


def test_nonzero_rc_explicit_no_bias_no_fatal():
    d = decide_lookahead(1, PASS_PARSED, "no bias detected")
    assert d["final_status"] == "PASS_WITH_RC_ANOMALY"


def test_nonzero_rc_no_bias_with_traceback_errors():
    d = decide_lookahead(1, PASS_PARSED, "no bias detected\nTraceback (most recent call last)")
    assert d["final_status"] == "ERROR"


def test_fatal_marker_terminating():
    d = decide_lookahead(0, PASS_PARSED, "Terminating due to error")
    assert d["final_status"] == "ERROR"


def test_fatal_marker_no_data():
    d = decide_lookahead(0, PASS_PARSED, "No data found for pair BTC/USDT")
    assert d["final_status"] == "ERROR"


def test_fatal_marker_timeoutexpired():
    d = decide_lookahead(0, PASS_PARSED, "TimeoutExpired: process exceeded 900s")
    assert d["final_status"] == "ERROR"


def test_explicit_no_bias_evidence_flag():
    d = decide_lookahead(0, PASS_PARSED, "no bias detected")
    assert d["explicit_no_bias_evidence"] is True

    d2 = decide_lookahead(0, FAIL_PARSED, "")
    assert d2["explicit_no_bias_evidence"] is False
