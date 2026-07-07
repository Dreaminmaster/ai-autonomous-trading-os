"""Evidence summary generator contract tests."""
import json, tempfile, pathlib, pytest
from atos.evidence_summary import generate_summary, summary_pass

def _mk(*dirs_files):
    base = tempfile.mkdtemp()
    for item in dirs_files:
        p = pathlib.Path(base) / item["path"]
        p.parent.mkdir(parents=True, exist_ok=True)
        if item.get("content"):
            p.write_text(item["content"] if isinstance(item["content"], str) else json.dumps(item["content"]))
    return base

def test_valid_artifacts_pass():
    d = _mk(
        {"path": "pytest.log", "content": "97 passed in 0.57s\n"},
        {"path": "no_secret_scan.log", "content": "No secret leakage detected.\n"},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_summary.json",
         "content": {"total_trades": 244, "profit_total_pct": -16.12, "winrate": 44.67, "max_drawdown_pct": 17.85, "profit_factor": 0.75}},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json",
         "content": {"final_status": "PASS", "parser_status": "PASS", "has_bias": False, "freqtrade_returncode": 0}},
        {"path": "validation_reports/strategy_fix_round1.md", "content": "Baseline integrity: PASS\n"\\n"},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    assert summary_pass(s, err) is True

def test_missing_canonical_fails():
    d = _mk(
        {"path": "pytest.log", "content": "passed\n"},
        {"path": "no_secret_scan.log", "content": "No secret leakage detected.\n"},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    assert summary_pass(s, err) is False

def test_invalid_json_fails():
    d = _mk(
        {"path": "pytest.log", "content": "passed\n"},
        {"path": "no_secret_scan.log", "content": "No secret leakage detected.\n"},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_summary.json", "content": "not json {{{"},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    assert summary_pass(s, err) is False

def test_missing_la_fails():
    d = _mk(
        {"path": "pytest.log", "content": "passed\n"},
        {"path": "no_secret_scan.log", "content": "No secret leakage detected.\n"},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_summary.json",
         "content": {"total_trades": 244, "profit_total_pct": -16.12, "winrate": 44.67, "max_drawdown_pct": 17.85, "profit_factor": 0.75}},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    assert summary_pass(s, err) is False

def test_la_error_fails():
    d = _mk(
        {"path": "pytest.log", "content": "passed\n"},
        {"path": "no_secret_scan.log", "content": "No secret leakage detected.\n"},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_summary.json",
         "content": {"total_trades": 244, "profit_total_pct": -16.12, "winrate": 44.67, "max_drawdown_pct": 17.85, "profit_factor": 0.75}},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json",
         "content": {"final_status": "ERROR", "parser_status": "ERROR", "has_bias": None}},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    assert summary_pass(s, err) is False

def test_la_pass_with_rc_anomaly_passes():
    d = _mk(
        {"path": "pytest.log", "content": "passed\n"},
        {"path": "no_secret_scan.log", "content": "No secret leakage detected.\n"},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_summary.json",
         "content": {"total_trades": 244, "profit_total_pct": -16.12, "winrate": 44.67, "max_drawdown_pct": 17.85, "profit_factor": 0.75}},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json",
         "content": {"final_status": "PASS_WITH_RC_ANOMALY", "parser_status": "PASS", "has_bias": False}},
        {"path": "validation_reports/strategy_fix_round1.md", "content": "Baseline integrity: PASS
"},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    assert summary_pass(s, err) is True

def test_no_question_mark_in_output():
    d = _mk(
        {"path": "pytest.log", "content": "passed\n"},
        {"path": "no_secret_scan.log", "content": "No secret leakage detected.\n"},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_summary.json",
         "content": {"total_trades": 244, "profit_total_pct": -16.12, "winrate": 44.67, "max_drawdown_pct": 17.85, "profit_factor": 0.75}},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json",
         "content": {"final_status": "PASS", "parser_status": "PASS", "has_bias": False}},
        {"path": "validation_reports/strategy_fix_round1.md", "content": "Baseline integrity: PASS\n""},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    output = json.dumps(s)
    assert "?" not in output

def test_no_literal_plus_empty_quote():
    d = _mk(
        {"path": "pytest.log", "content": "passed\n"},
        {"path": "no_secret_scan.log", "content": "No secret leakage detected.\n"},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_summary.json",
         "content": {"total_trades": 244, "profit_total_pct": -16.12, "winrate": 44.67, "max_drawdown_pct": 17.85, "profit_factor": 0.75}},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json",
         "content": {"final_status": "PASS", "parser_status": "PASS", "has_bias": False}},
        {"path": "validation_reports/strategy_fix_round1.md", "content": "Baseline integrity: PASS\n""},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    output = json.dumps(s)
    assert '\" + \"\" +' not in output

def test_atos_failure_fails():
    d = _mk(
        {"path": "pytest.log", "content": "0 passed, 97 failed\n"},
        {"path": "no_secret_scan.log", "content": "SECRET LEAKED\n"},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    assert summary_pass(s, err) is False

def test_malformed_artifact_fails():
    d = _mk(
        {"path": "pytest.log", "content": "passed\n"},
        {"path": "no_secret_scan.log", "content": "No secret leakage detected.\n"},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_summary.json", "content": '\x00\x01\x02'},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    assert summary_pass(s, err) is False

def test_required_evidence_complete_passes():
    d = _mk(
        {"path": "pytest.log", "content": "97 passed in 0.57s\n"},
        {"path": "no_secret_scan.log", "content": "No secret leakage detected.\n"},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_summary.json",
         "content": {"total_trades": 244, "profit_total_pct": -16.12, "winrate": 44.67, "max_drawdown_pct": 17.85, "profit_factor": 0.75}},
        {"path": "freqtrade_data/backtest_results/canonical_baseline_la_lookahead_status.json",
         "content": {"final_status": "PASS", "parser_status": "PASS", "has_bias": False, "freqtrade_returncode": 0}},
        {"path": "validation_reports/strategy_fix_round1.md", "content": "Baseline integrity: PASS\n""},
    )
    s, err = generate_summary("abc123", "run1", d, d)
    assert summary_pass(s, err) is True
    assert s["canonical"]["trades"] == 244
    assert s["canonical"]["profit_total_pct"] == -16.12
