from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import pytest

from scripts import c6a_strict_finalizer as strict

ZERO = Decimal("0")


@dataclass
class Components:
    spot_price_pnl: Decimal = ZERO
    perpetual_price_pnl: Decimal = ZERO
    funding_pnl: Decimal = ZERO
    spot_cost: Decimal = ZERO
    swap_cost: Decimal = ZERO


def window(window_id: str, *, weekly_return: Decimal = ZERO) -> dict:
    weekly = [
        {
            "pnl": weekly_return * Decimal("1000"),
            "return": weekly_return,
        }
        for _ in range(26)
    ]
    pnl = sum((row["pnl"] for row in weekly), ZERO)
    return {
        "policy_id": "C6AMarketNeutralFundingCarry",
        "cost_label": "1.0x",
        "window_id": window_id,
        "final_equity": Decimal("1000") + pnl,
        "net_return": pnl / Decimal("1000"),
        "weekly": weekly,
        "maximum_drawdown": ZERO,
        "annualized_one_way_turnover": ZERO,
        "active_week_count": 0,
        "active_funding_settlements": 0,
        "collateral_buffer_breaches": 0,
        "hedge_breaches": 0,
        "asset_contributions": {"BTC": ZERO, "ETH": ZERO},
        "components": Components(),
        "events": [],
    }


def test_safe_reference_aggregate_retains_null_statistics_for_zero_variance() -> None:
    aggregate = strict.safe_reference_aggregate(
        [window(f"W{i}") for i in range(1, 6)]
    )
    assert aggregate["aggregate_return"] == 0
    assert aggregate["statistics"] is None
    assert "variance" in aggregate["statistics_error"]
    assert aggregate["funding_cost_coverage"] is None
    assert len(aggregate["weekly_returns"]) == 130
    assert len(aggregate["weekly_pnl"]) == 130


def production_from(reference: dict) -> dict:
    return {
        "policy_id": reference["policy_id"],
        "cost_label": reference["cost_label"],
        "aggregate_return": str(reference["aggregate_return"]),
        "window_returns": {
            key: str(value) for key, value in reference["window_returns"].items()
        },
        "window_pnl": {
            key: str(value) for key, value in reference["window_pnl"].items()
        },
        "weekly_returns": [str(value) for value in reference["weekly_returns"]],
        "weekly_pnl": {
            key: str(value) for key, value in reference["weekly_pnl"].items()
        },
        "statistics": reference["statistics"],
        "statistics_error": reference["statistics_error"],
        "maximum_drawdown": str(reference["maximum_drawdown"]),
        "annualized_one_way_turnover": str(
            reference["annualized_one_way_turnover"]
        ),
        "gross_funding_receipts": str(reference["gross_funding_receipts"]),
        "gross_funding_payments": str(reference["gross_funding_payments"]),
        "total_trading_costs": str(reference["total_trading_costs"]),
        "funding_cost_coverage": None,
        "active_weeks_total": reference["active_weeks_total"],
        "active_weeks_by_window": reference["active_weeks_by_window"],
        "active_funding_settlements": reference["active_funding_settlements"],
        "collateral_buffer_breaches": reference["collateral_buffer_breaches"],
        "hedge_breaches": reference["hedge_breaches"],
        "asset_pnl": {
            key: str(value) for key, value in reference["asset_pnl"].items()
        },
    }


def test_strict_aggregate_comparison_checks_gate_driving_fields() -> None:
    reference = strict.safe_reference_aggregate(
        [window(f"W{i}") for i in range(1, 6)]
    )
    production = production_from(reference)
    strict.compare_neutral_aggregate(production, reference, label="candidate/1.0x")

    production["active_funding_settlements"] = 1
    with pytest.raises(strict.C6AStrictFinalizerError, match="active_funding_settlements"):
        strict.compare_neutral_aggregate(
            production, reference, label="candidate/1.0x"
        )


def test_strict_aggregate_comparison_rejects_nonnull_undefined_statistics() -> None:
    reference = strict.safe_reference_aggregate(
        [window(f"W{i}") for i in range(1, 6)]
    )
    production = production_from(reference)
    production["statistics"] = {"annualized_weekly_sharpe": 0}
    with pytest.raises(strict.C6AStrictFinalizerError, match="statistics must be null"):
        strict.compare_neutral_aggregate(
            production, reference, label="candidate/1.0x"
        )
