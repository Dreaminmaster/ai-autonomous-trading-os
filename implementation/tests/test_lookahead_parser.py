"""Tests for lookahead_parser using real Freqtrade 2026.6 outputs."""
from atos.lookahead_parser import parse_lookahead_result, parse_table_row

# Real CI outputs from run 28715989732 artifact
FREQTRADE_2026_TABLE_NO_BIAS = """
                                                               Lookahead Analysis
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┓
┃                  filename ┃             strategy ┃ has_bias ┃ total_signals ┃ biased_entry_signals ┃ biased_exit_signals ┃ biased_indicators ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━┩
│ ai_supervised_strategy.py │ AISupervisedStrategy │       No │            20 │                    0 │                   0 │                   │
└───────────────────────────┴──────────────────────┴──────────┴───────────────┴──────────────────────┴─────────────────────┴───────────────────┘
"""

FREQTRADE_LOG_NO_BIAS = " => AISupervisedStrategy : no bias detected!\n"

FREQTRADE_TABLE_BIAS = """
│ ai_supervised_strategy.py │ AISupervisedStrategy │      Yes │            20 │                   18 │                  16 │                   │
"""

FREQTRADE_NO_DATA = "No data for BTC/USDT, spot, 5m found. Terminating."

FREQTRADE_TOO_FEW = "│ ai_supervised_strategy.py │ AISupervisedStrategy │ too few trades caught (0/10).Test failed. │"


def test_real_freqtrade_table_no_bias_passes():
    result = parse_lookahead_result(FREQTRADE_2026_TABLE_NO_BIAS)
    assert result["status"] == "PASS"
    assert result["has_bias"] is False
    assert result["total_signals"] == 20
    assert result["biased_entry_signals"] == 0
    assert result["biased_exit_signals"] == 0

def test_real_no_bias_log_passes():
    result = parse_lookahead_result(FREQTRADE_LOG_NO_BIAS)
    assert result["status"] == "PASS"
    assert result["has_bias"] is False

def test_bias_table_fails():
    result = parse_lookahead_result(FREQTRADE_TABLE_BIAS)
    assert result["status"] == "FAIL"
    assert result["has_bias"] is True
    assert result["biased_entry_signals"] == 18

def test_no_data_errors():
    result = parse_lookahead_result(FREQTRADE_NO_DATA)
    assert result["status"] == "ERROR"
    assert result["has_bias"] is None

def test_too_few_trades_errors():
    result = parse_lookahead_result(FREQTRADE_TOO_FEW)
    assert result["status"] == "ERROR"

def test_unparseable_output_errors():
    result = parse_lookahead_result("garbage output")
    assert result["status"] == "ERROR"

def test_empty_output_errors():
    result = parse_lookahead_result("")
    assert result["status"] == "ERROR"

def test_no_bias_table_row():
    result = parse_table_row(FREQTRADE_2026_TABLE_NO_BIAS)
    assert result is not None
    assert result["has_bias"] is False
    assert result["total_signals"] == 20

def test_bias_table_row():
    result = parse_table_row(FREQTRADE_TABLE_BIAS)
    assert result["status"] == "FAIL"
    assert result["has_bias"] is True

def test_too_few_table_row():
    result = parse_table_row(FREQTRADE_TOO_FEW)
    assert result is not None
    assert result["status"] == "ERROR"
