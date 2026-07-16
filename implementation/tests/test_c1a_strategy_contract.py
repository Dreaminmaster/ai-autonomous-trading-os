from __future__ import annotations

import ast
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "implementation" / "freqtrade_data" / "strategies" / "c1a_common.py"
CONFIG = ROOT / "implementation" / "config" / "c1a_strategy_family_screen.json"
CONTRACT = (
    ROOT
    / "docs"
    / "architecture"
    / "phase-c"
    / "c1a-family-screen"
    / "C1A_STRATEGY_FAMILY_SCREEN_CONTRACT_V1.md"
)
FAMILIES = {"C1ARegimeBreakout", "C1ATrendPullback", "C1ADualMomentum"}


def _tree() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def _classes() -> dict[str, ast.ClassDef]:
    return {
        node.name: node
        for node in _tree().body
        if isinstance(node, ast.ClassDef)
    }


def _class_assignments(class_name: str) -> dict[str, ast.expr]:
    result: dict[str, ast.expr] = {}
    for node in _classes()[class_name].body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    result[target.id] = node.value
    return result


def test_config_freezes_screen_boundary_costs_and_families() -> None:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert config["required_base_sha"] == "967497fe726452a60fb6d0e84c10f027873951bf"
    assert set(config["strategies"]) == FAMILIES
    assert config["pairs"] == ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    assert config["timeframe"] == "1h"
    assert config["informative_timeframe"] == "1d"
    assert config["economic_boundary_exclusive"] == "2024-10-01T00:00:00Z"
    assert config["expected_fee_rate"] == 0.0015
    assert config["fee_multipliers"] == [1.0, 1.5, 2.0]
    assert config["slippage_rate"] == 0.0
    assert config["live"] == "FORBIDDEN"
    assert config["holdout_state"] == "HOLDOUT_CLOSED"
    assert config["confirmation_opened"] is False
    assert [item["id"] for item in config["screen_windows"]] == ["S1", "S2", "S3"]
    assert [item["id"] for item in config["reserved_confirmation_windows"]] == [
        "C1",
        "C2",
        "C3",
    ]


def test_all_three_candidates_inherit_fixed_backtest_only_base() -> None:
    classes = _classes()
    assert FAMILIES.issubset(classes)
    base = _class_assignments("_C1ABase")
    assert ast.literal_eval(base["can_short"]) is False
    assert ast.literal_eval(base["timeframe"]) == "1h"
    assert ast.literal_eval(base["startup_candle_count"]) == 1499
    assert ast.literal_eval(base["minimal_roi"]) == {}
    assert ast.literal_eval(base["stoploss"]) == -0.30
    source = SOURCE.read_text(encoding="utf-8").lower()
    for forbidden in (
        "decimalparameter",
        "intparameter",
        "hyperopt",
        "requests.",
        "openai",
        "dry_run = false",
        "can_short = true",
    ):
        assert forbidden not in source


def test_daily_context_is_combined_before_single_informative_merge() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    function = next(
        node
        for node in _tree().body
        if isinstance(node, ast.FunctionDef) and node.name == "merge_daily_context"
    )
    calls = [
        node
        for node in ast.walk(function)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "merge_informative_pair"
    ]
    assert len(calls) == 1
    assert 'validate="one_to_one"' in source
    assert 'timeframe=DAILY_TIMEFRAME' in source


def test_breakout_extrema_exclude_current_candle_and_entry_is_event_based() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert 'dataframe["high"].shift(1).rolling(480).max()' in source
    assert 'dataframe["low"].shift(1).rolling(240).min()' in source
    assert 'dataframe["close"].shift(1) <= dataframe["donchian_high_480"].shift(1)' in source
    assert 'dataframe["close"].shift(1) >= dataframe["donchian_low_240"].shift(1)' in source
    assert "2.5 * entry_atr" in source
    assert "timeframe_to_prev_date" in source
    assert "stoploss_from_absolute" in source


def test_pullback_constants_and_time_stop_are_frozen() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert 'dataframe["rsi14_1h"] <= 35.0' in source
    assert 'dataframe["rsi14_1h"] >= 55.0' in source
    assert "timedelta(hours=168)" in source
    assert '"c1a_168h_time_stop"' in source


def test_dual_momentum_waives_only_btc_self_comparison() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "if pair != BTC_PAIR:" in source
    assert 'dataframe["pair_return_20d_1d"] > dataframe["btc_return_20d_1d"]' in source
    assert "condition & ~condition.shift(1).fillna(False)" in source
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    indicators = config["startup_analysis"]["required_indicators"]["C1ADualMomentum"]
    assert "pair_return_20d_1d" in indicators
    assert "pair_return_60d_1d" in indicators
    assert "btc_return_20d_1d" in indicators


def test_contract_and_config_preserve_confirmation_and_holdout_closure() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    config_text = CONFIG.read_text(encoding="utf-8")
    assert "No Hyperopt or parameter search is allowed in C1A" in contract
    assert "confirmation_opened = false" in contract
    assert "HOLDOUT_CLOSED" in contract
    assert "LIVE FORBIDDEN" in contract
    assert "2025-07-01" in contract and "2026-07-01" in contract
    assert "2026-07-01" not in config_text
    assert "20241001-2025" not in config_text
