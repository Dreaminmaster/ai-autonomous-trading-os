from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from scripts.c6a_reference_gate import reference_gate

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def aggregate(*, return_value: str, sharpe: str = "1.4") -> dict:
    return {
        "aggregate_return": Decimal(return_value),
        "window_returns": {f"W{i}": Decimal("0.03") for i in range(1, 6)},
        "window_pnl": {f"W{i}": Decimal("20") for i in range(1, 6)},
        "weekly_pnl": {f"week-{i:03d}": Decimal("1") for i in range(130)},
        "statistics": {
            "annualized_weekly_sharpe": float(sharpe),
            "psr_probability": 0.98,
        },
        "maximum_drawdown": Decimal("0.06"),
        "annualized_one_way_turnover": Decimal("4"),
        "funding_cost_coverage": Decimal("3"),
        "active_weeks_total": 80,
        "active_weeks_by_window": {f"W{i}": 16 for i in range(1, 6)},
        "active_funding_settlements": 300,
        "collateral_buffer_breaches": 0,
        "hedge_breaches": 0,
        "asset_pnl": {"BTC": Decimal("55"), "ETH": Decimal("45")},
    }


def candidate_set(expected: dict) -> dict[str, dict]:
    return {
        "1.0x": expected,
        "1.5x": aggregate(return_value="0.10"),
        "2.0x": aggregate(return_value="0.05"),
    }


def always_on() -> dict:
    return {
        **aggregate(return_value="0.10", sharpe="1.2"),
        "maximum_drawdown": Decimal("0.08"),
        "annualized_one_way_turnover": Decimal("5"),
    }


def test_independent_gate_selects_only_complete_pass() -> None:
    decision = reference_gate(
        candidate_by_cost=candidate_set(aggregate(return_value="0.15")),
        always_on_expected=always_on(),
        config=config(),
    )
    assert decision["status"] == "SELECTED"
    assert decision["selected_policy"] == "C6AMarketNeutralFundingCarry"
    assert all(decision["checks"].values())


def test_independent_gate_rejects_failed_window_and_incremental_value() -> None:
    expected = aggregate(return_value="0.10", sharpe="1.2")
    expected["window_returns"]["W3"] = Decimal("-0.001")
    decision = reference_gate(
        candidate_by_cost={
            "1.0x": expected,
            "1.5x": aggregate(return_value="0.05", sharpe="1.2"),
            "2.0x": aggregate(return_value="0", sharpe="1.2"),
        },
        always_on_expected={
            **aggregate(return_value="0.10", sharpe="1.2"),
            "maximum_drawdown": Decimal("0.05"),
            "annualized_one_way_turnover": Decimal("3"),
        },
        config=config(),
    )
    assert decision["status"] == "REJECTED"
    assert decision["selected_policy"] is None
    assert "all_windows_positive" in decision["rejection_reasons"]
    assert "return_delta_vs_always_on" in decision["rejection_reasons"]
    assert "sharpe_delta_vs_always_on" in decision["rejection_reasons"]
    assert "drawdown_not_worse_than_always_on" in decision["rejection_reasons"]
    assert "turnover_not_worse_than_always_on" in decision["rejection_reasons"]


def test_undefined_statistics_and_funding_denominator_reject_without_exception() -> None:
    expected = aggregate(return_value="0")
    expected["statistics"] = None
    expected["funding_cost_coverage"] = None
    comparator = always_on()
    comparator["statistics"] = None
    decision = reference_gate(
        candidate_by_cost=candidate_set(expected),
        always_on_expected=comparator,
        config=config(),
    )
    assert decision["status"] == "REJECTED"
    assert decision["selected_policy"] is None
    assert decision["rejection_reasons"] == (
        "candidate_weekly_statistics",
        "always_on_weekly_statistics",
        "funding_cost_coverage_denominator",
    )


def test_zero_positive_concentration_denominators_reject_without_exception() -> None:
    expected = aggregate(return_value="0")
    expected["asset_pnl"] = {"BTC": Decimal("0"), "ETH": Decimal("-1")}
    expected["window_pnl"] = {f"W{i}": Decimal("0") for i in range(1, 6)}
    expected["weekly_pnl"] = {f"week-{i:03d}": Decimal("0") for i in range(130)}
    decision = reference_gate(
        candidate_by_cost=candidate_set(expected),
        always_on_expected=always_on(),
        config=config(),
    )
    assert decision["status"] == "REJECTED"
    assert decision["selected_policy"] is None
    assert decision["rejection_reasons"] == (
        "positive_asset_concentration_denominator",
        "positive_window_concentration_denominator",
        "positive_week_concentration_denominator",
    )
