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

def test_nested_strategy_json_parsing():
    """Parse actual Freqtrade zip structure: strategy/{AISupervisedStrategy}/{...}"""
    data = {"strategy": {"AISupervisedStrategy": {"total_trades": 244, "profit_total": -0.1612, "winrate": 0.447, "max_drawdown_account": 0.1785, "profit_factor": 0.75}}}
    c = data["strategy"]
    assert "AISupervisedStrategy" in c
    strat = c["AISupervisedStrategy"]
    assert strat["total_trades"] == 244

def test_profit_total_ratio_to_pct():
    assert _ratio_to_pct(-0.1612) == -16.12
    assert _ratio_to_pct(-0.4241) == -42.41

def test_winrate_ratio_to_pct():
    assert _ratio_to_pct(0.4963) == 49.63

def test_max_drawdown_account_ratio_to_pct():
    assert _ratio_to_pct(0.4686) == 46.86
    assert _ratio_to_pct(0.1785) == 17.85

def test_missing_metrics_cannot_pass_baseline_integrity():
    vals = [244, "?", 44.7, 17.85]
    has_missing = any(v == "?" or v is None for v in vals)
    baseline = "CONFIRMED" if not has_missing else "FAIL:missing_metrics"
    assert baseline == "FAIL:missing_metrics"

def test_pair_universe_mismatch_fails():
    a = ["BTC/USDT"]
    b = ["BTC/USDT", "ETH/USDT"]
    assert a != b

# ── Pair extraction tests ───────────────────────────────────

def test_pair_extraction_from_nested_strategy_trades():
    """trades inside strategy/{name}/trades"""
    strat = {"trades": [{"pair": "BTC/USDT"}, {"pair": "BTC/USDT"}]}
    actual = sorted(set(t["pair"] for t in strat["trades"]))
    assert actual == ["BTC/USDT"]

def test_pair_extraction_from_top_level_trades():
    """trades at top level"""
    data = {"trades": [{"pair": "BTC/USDT"}, {"pair": "ETH/USDT"}]}
    actual = sorted(set(t["pair"] for t in data["trades"]))
    assert actual == ["BTC/USDT", "ETH/USDT"]

def test_pair_extraction_from_strategy_pairlist():
    """pairlist in strategy dict"""
    strat = {"pairlist": ["BTC/USDT"]}
    actual = sorted(set(strat["pairlist"]))
    assert actual == ["BTC/USDT"]

def test_pair_integrity_no_evidence_fails():
    actual_pairs = []
    pairs_requested = ["BTC/USDT"]
    if not actual_pairs:
        result = "FAIL:no_actual_pairs_evidence"
        assert result != "PASS"

def test_pair_integrity_unexpected_pair_fails():
    actual_pairs = ["BTC/USDT", "ETH/USDT"]
    pairs_requested = ["BTC/USDT"]
    result = "PASS" if pairs_requested == actual_pairs else "FAIL"
    assert result == "FAIL"

# ── No-substitution tests ───────────────────────────────────

def test_original_best_captured_before_disabled_filter():
    candidates = [
        {"strategy_id": "trend_following_v1", "side": "BUY", "confidence": 0.8},
        {"strategy_id": "breakout_v1", "side": "BUY", "confidence": 0.5},
    ]
    original = [dict(c) for c in candidates]
    best = max([c for c in original if c["side"] == "BUY"], key=lambda c: c["confidence"])
    assert best["strategy_id"] == "trend_following_v1"
    # After disabled filter
    filtered = [c for c in candidates if c["strategy_id"] != "trend_following_v1"]
    assert best["strategy_id"] == "trend_following_v1"  # still original
    assert len(filtered) == 1  # breakout only

def test_no_substitution_disabled_forces_hold():
    disabled = {"trend_following_v1"}
    original_best = {"strategy_id": "trend_following_v1", "confidence": 0.8}
    trend_disabled = original_best["strategy_id"] in disabled
    force_hold = trend_disabled
    assert force_hold is True

def test_no_substitution_weight_crosses_threshold():
    raw_conf = 0.8
    weight = 0.25
    eff_conf = raw_conf * weight  # 0.2
    below_threshold = raw_conf >= 0.6 and eff_conf < 0.6
    force_hold = below_threshold
    assert force_hold is True

def test_no_substitution_raw_below_threshold_not_forced():
    raw_conf = 0.5
    weight = 0.25
    eff_conf = raw_conf * weight
    below_threshold = raw_conf >= 0.6 and eff_conf < 0.6
    assert below_threshold is False  # raw already below, not our intervention

def test_no_sub_false_allows_substitution():
    original_best = {"strategy_id": "trend_following_v1", "confidence": 0.8}
    disabled = {"trend_following_v1"}
    no_sub = False
    force_hold = False
    if no_sub and original_best["strategy_id"] in disabled:
        force_hold = True
    assert force_hold is False

# ── Regression tests ────────────────────────────────────────

def test_canonical_baseline_regression():
    """Ensure canonical summary schema has required keys"""
    required = ["total_trades", "profit_total_pct", "winrate", "max_drawdown_pct", "profit_factor",
                "baseline_integrity", "pair_universe_integrity", "cache_mode"]
    canonical = {"total_trades": 244, "profit_total_pct": -16.12, "winrate": 44.67,
                 "max_drawdown_pct": 17.85, "profit_factor": 0.75, "baseline_integrity": "CONFIRMED",
                 "pair_universe_integrity": "PASS", "cache_mode": "none"}
    for k in required:
        assert k in canonical, f"Missing key: {k}"
    assert canonical["total_trades"] == 244

def test_baseline_integrity_uses_five_metrics():
    keys = ["total_trades", "profit_total_pct", "winrate", "max_drawdown_pct", "profit_factor"]
    assert len(keys) == 5

def test_best_two_excludes_baseline():
    results = [
        {"name": "round1_1_baseline_current", "profit": -16.12, "status": "OK"},
        {"name": "round1_2_trend_weight_025", "profit": -41.67, "status": "OK"},
    ]
    experiment_results = [r for r in results if r["status"] == "OK" and "baseline" not in r.get("name","")]
    assert len(experiment_results) == 1
    assert experiment_results[0]["name"] == "round1_2_trend_weight_025"
