from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from atos.c6a_safe_aggregate_v2 import (
    UNDEFINED_WEEKLY_STATISTICS,
    aggregate_window_results_final,
    decide_candidate_safe,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def window(window_id: str, *, weekly_return: str = "0") -> dict:
    weekly = [
        {
            "weekly_return": weekly_return,
            "weekly_pnl": str(Decimal(weekly_return) * Decimal("1000")),
        }
        for _ in range(26)
    ]
    pnl = sum((Decimal(row["weekly_pnl"]) for row in weekly), Decimal("0"))
    return {
        "policy_id": "C6AMarketNeutralFundingCarry",
        "cost_label": "1.0x",
        "window_id": window_id,
        "final_equity": str(Decimal("1000") + pnl),
        "net_return": str(pnl / Decimal("1000")),
        "weekly_buckets": weekly,
        "events": [],
        "components": {
            "spot_price_pnl": "0",
            "perpetual_price_pnl": "0",
            "funding_pnl": "0",
            "spot_cost": "0",
            "swap_cost": "0",
        },
        "asset_contributions": {"BTC": "0", "ETH": "0"},
        "maximum_drawdown": "0",
        "annualized_one_way_turnover": "0",
        "active_week_count": 0,
        "active_funding_settlements": 0,
        "collateral_buffer_breaches": 0,
        "hedge_breaches": 0,
    }


def test_safe_aggregate_retains_zero_variance_as_null_statistics() -> None:
    result = aggregate_window_results_final(
        [window(f"W{i}") for i in range(1, 6)],
        [object() for _ in range(5)],
    )
    assert result.aggregate_return == 0
    assert result.statistics is None
    assert result.statistics_error == UNDEFINED_WEEKLY_STATISTICS
    assert result.funding_cost_coverage is None
    payload = result.to_dict()
    assert payload["statistics"] is None
    assert payload["statistics_error"] == "UNDEFINED_WEEKLY_VARIANCE"
    assert payload["funding_cost_coverage"] is None
    assert payload["c6b_state"] == "C6B_CLOSED"
    assert payload["live"] == "FORBIDDEN"


def test_safe_gate_rejects_zero_variance_without_crashing() -> None:
    aggregate = aggregate_window_results_final(
        [window(f"W{i}") for i in range(1, 6)],
        [object() for _ in range(5)],
    )
    candidate = {
        "1.0x": aggregate,
        "1.5x": aggregate,
        "2.0x": aggregate,
    }
    decision = decide_candidate_safe(
        candidate_by_cost=candidate,
        always_on_expected=aggregate,
        config=config(),
    )
    assert decision.status == "REJECTED"
    assert decision.selected_policy is None
    assert "candidate_weekly_statistics" in decision.rejection_reasons
    assert "always_on_weekly_statistics" in decision.rejection_reasons
    assert "funding_cost_coverage_denominator" in decision.rejection_reasons
    assert "positive_asset_concentration_denominator" in decision.rejection_reasons
    assert "positive_window_concentration_denominator" in decision.rejection_reasons
    assert "positive_week_concentration_denominator" in decision.rejection_reasons
