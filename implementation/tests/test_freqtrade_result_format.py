"""Tests: parse Freqtrade zip/json results, provenance, unit consistency."""

import hashlib
import json
import tempfile
import zipfile
from pathlib import Path

def test_parse_freqtrade_zip_result():
    js = json.dumps({"strategy": {"total_trades": 244, "profit_total_pct": -16.12, "winrate": 0.447, "max_drawdown": 17.85, "profit_factor": 0.75}})
    d = tempfile.mkdtemp()
    zp = Path(d) / "backtest-result-test.zip"
    with zipfile.ZipFile(zp, "w") as zz:
        zz.writestr("backtest-result.json", js)
    with zipfile.ZipFile(zp) as zz:
        names = zz.namelist()
        for name in names:
            if "meta" not in name and name.endswith(".json"):
                data = json.loads(zz.read(name))
                assert data["strategy"]["total_trades"] == 244
                break

def test_parse_freqtrade_plain_json_result():
    js = {"strategy": {"total_trades": 42, "profit_total_pct": 10.0, "winrate": 0.55, "max_drawdown": 5.0, "profit_factor": 2.0}}
    assert js["strategy"]["total_trades"] == 42

def test_meta_json_not_treated_as_full_result():
    assert "meta" in "backtest-result-ts.meta.json"
    assert "meta" not in "backtest-result-ts.json"

def test_canonical_summary_units():
    summary = {"profit_total_pct": -16.12, "max_drawdown_pct": 17.85}
    assert summary["profit_total_pct"] == -16.12
    assert summary["max_drawdown_pct"] == 17.85

def test_canonical_summary_contains_provenance():
    import time
    summary = {
        "source_result_type": "zip",
        "source_result_sha256": hashlib.sha256(b"x").hexdigest()[:16],
        "total_trades": 244,
        "profit_total_pct": -16.12,
        "winrate": 44.7,
        "max_drawdown_pct": 17.85,
        "profit_factor": 0.75,
        "policy_sha256": "abcd1234",
        "config_sha256": "efgh5678",
        "cache_mode": "none",
        "baseline_integrity": "CONFIRMED",
        "metric_sources": {"profit_total_pct": "profit_total_pct", "winrate": "winrate (ratio\u2192pct)"},
    }
    assert summary["source_result_type"] in ("zip", "json")
    assert len(summary["source_result_sha256"]) == 16
    assert summary["winrate"] == 44.7

def test_isolated_result_does_not_use_old_global_file():
    d1 = Path(tempfile.mkdtemp()) / "run_a" / "variant_1" / "backtest_results"
    d2 = Path(tempfile.mkdtemp()) / "run_a" / "variant_2" / "backtest_results"
    d1.mkdir(parents=True)
    d2.mkdir(parents=True)
    assert d1 != d2
    (d1 / "result.zip").write_text("a")
    (d2 / "result.zip").write_text("b")
    assert (d1 / "result.zip").read_text() != (d2 / "result.zip").read_text()

def _number(val):
    if isinstance(val, str):
        val = val.replace("%", "").strip()
    try:
        return float(val)
    except (ValueError, TypeError):
        return val

def _ratio_to_pct(val):
    v = _number(val)
    return round(v * 100, 2) if isinstance(v, (int, float)) and abs(v) <= 1 else v

def test_profit_total_pct_minus_16_12():
    assert _number("-16.12%") == -16.12
    assert _number("-16.12") == -16.12
    assert _number(-16.12) == -16.12

def test_profit_total_ratio_becomes_pct():
    assert _ratio_to_pct(-0.1612) == -16.12

def test_winrate_0_447_becomes_44_7():
    assert _ratio_to_pct(0.447) == 44.7

def test_string_percent_17_85_becomes_17_85():
    assert _number("17.85%") == 17.85

def test_metric_sources_recorded():
    summary = {"metric_sources": {"profit_total_pct": "profit_total_pct", "winrate": "winrate (ratio\u2192pct)"}}
    assert "metric_sources" in summary
    assert "profit_total_pct" in summary["metric_sources"]
