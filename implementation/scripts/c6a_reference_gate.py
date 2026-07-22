"""Independent C6A aggregate gate decision.

No production metrics, aggregate, or gate function is imported.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping

from atos.c6a_contract import C6AError, decimal_value

COST_LABELS = ("1.0x", "1.5x", "2.0x")
WINDOW_IDS = ("W1", "W2", "W3", "W4", "W5")


def _positive_shares(
    values: Mapping[str, Decimal], *, label: str
) -> tuple[Decimal, Decimal] | None:
    if not values:
        raise C6AError(f"reference {label} contribution set is empty")
    positive = sorted(
        (max(decimal_value(value, f"reference {label} contribution"), Decimal("0"))
         for value in values.values()),
        reverse=True,
    )
    denominator = sum(positive, Decimal("0"))
    if denominator <= 0:
        return None
    return positive[0] / denominator, sum(positive[:3], Decimal("0")) / denominator


def _rejected_for_undefined(*reasons: str) -> dict[str, Any]:
    unique = tuple(dict.fromkeys(reasons))
    return {
        "status": "REJECTED",
        "selected_policy": None,
        "checks": {reason: False for reason in unique},
        "rejection_reasons": unique,
    }


def reference_gate(
    *,
    candidate_by_cost: Mapping[str, Mapping[str, Any]],
    always_on_expected: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if set(candidate_by_cost) != set(COST_LABELS):
        raise C6AError("reference candidate cost set mismatch")
    expected = candidate_by_cost["1.0x"]
    stress = candidate_by_cost["1.5x"]
    severe = candidate_by_cost["2.0x"]
    if set(expected["window_returns"]) != set(WINDOW_IDS):
        raise C6AError("reference candidate window set mismatch")
    gate = config.get("gate")
    if not isinstance(gate, Mapping):
        raise C6AError("reference gate configuration missing")

    undefined: list[str] = []
    if expected.get("statistics") is None:
        undefined.append("candidate_weekly_statistics")
    if always_on_expected.get("statistics") is None:
        undefined.append("always_on_weekly_statistics")
    if expected.get("funding_cost_coverage") is None:
        undefined.append("funding_cost_coverage_denominator")

    asset_shares = _positive_shares(expected["asset_pnl"], label="asset")
    window_shares = _positive_shares(expected["window_pnl"], label="window")
    week_shares = _positive_shares(expected["weekly_pnl"], label="week")
    if asset_shares is None:
        undefined.append("positive_asset_concentration_denominator")
    if window_shares is None:
        undefined.append("positive_window_concentration_denominator")
    if week_shares is None:
        undefined.append("positive_week_concentration_denominator")
    if undefined:
        return _rejected_for_undefined(*undefined)

    assert asset_shares is not None
    assert window_shares is not None
    assert week_shares is not None
    asset_max, _ = asset_shares
    window_max, _ = window_shares
    week_max, week_top_three = week_shares
    expected_return = decimal_value(expected["aggregate_return"], "expected return")
    return_delta = expected_return - decimal_value(
        always_on_expected["aggregate_return"], "always-on return"
    )
    sharpe = Decimal(str(expected["statistics"]["annualized_weekly_sharpe"]))
    always_sharpe = Decimal(
        str(always_on_expected["statistics"]["annualized_weekly_sharpe"])
    )
    sharpe_delta = sharpe - always_sharpe
    checks = {
        "all_windows_positive": all(
            decimal_value(value, "window return") > 0
            for value in expected["window_returns"].values()
        ),
        "aggregate_expected_return": expected_return
        > decimal_value(gate["minimum_aggregate_return_exclusive"], "return gate"),
        "aggregate_1_5x_return": decimal_value(
            stress["aggregate_return"], "stress return"
        )
        > decimal_value(gate["minimum_aggregate_1_5x_return_exclusive"], "stress gate"),
        "aggregate_2x_return": decimal_value(
            severe["aggregate_return"], "severe return"
        )
        >= decimal_value(gate["minimum_aggregate_2x_return"], "severe gate"),
        "annualized_weekly_sharpe": sharpe
        >= decimal_value(gate["minimum_annualized_weekly_sharpe"], "Sharpe gate"),
        "weekly_psr": Decimal(str(expected["statistics"]["psr_probability"]))
        >= decimal_value(gate["minimum_weekly_psr"], "PSR gate"),
        "maximum_drawdown": decimal_value(
            expected["maximum_drawdown"], "maximum drawdown"
        )
        <= decimal_value(gate["maximum_drawdown"], "drawdown gate"),
        "zero_collateral_buffer_breaches": expected["collateral_buffer_breaches"] == 0,
        "zero_hedge_breaches": expected["hedge_breaches"] == 0,
        "annualized_turnover": decimal_value(
            expected["annualized_one_way_turnover"], "turnover"
        )
        <= decimal_value(
            gate["maximum_annualized_one_way_turnover"], "turnover gate"
        ),
        "funding_cost_coverage": decimal_value(
            expected["funding_cost_coverage"], "funding coverage"
        )
        >= decimal_value(gate["minimum_funding_cost_coverage"], "coverage gate"),
        "active_weeks_total": expected["active_weeks_total"]
        >= int(gate["minimum_active_weeks_total"]),
        "active_weeks_each_window": all(
            value >= int(gate["minimum_active_weeks_per_window"])
            for value in expected["active_weeks_by_window"].values()
        ),
        "active_funding_settlements": expected["active_funding_settlements"]
        >= int(gate["minimum_active_funding_settlements"]),
        "both_assets_positive": all(
            decimal_value(value, "asset PnL") > 0
            for value in expected["asset_pnl"].values()
        ),
        "asset_concentration": asset_max
        <= decimal_value(gate["maximum_positive_asset_pnl_share"], "asset share"),
        "window_concentration": window_max
        <= decimal_value(gate["maximum_positive_window_pnl_share"], "window share"),
        "week_concentration": week_max
        <= decimal_value(gate["maximum_positive_week_pnl_share"], "week share"),
        "top_three_week_concentration": week_top_three
        <= decimal_value(
            gate["maximum_top_three_positive_week_pnl_share"], "top-three share"
        ),
        "return_delta_vs_always_on": return_delta
        > decimal_value(
            gate["minimum_return_delta_vs_always_on_exclusive"], "return delta"
        ),
        "sharpe_delta_vs_always_on": sharpe_delta
        >= decimal_value(gate["minimum_sharpe_delta_vs_always_on"], "Sharpe delta"),
        "drawdown_not_worse_than_always_on": decimal_value(
            expected["maximum_drawdown"], "candidate drawdown"
        )
        <= decimal_value(always_on_expected["maximum_drawdown"], "always-on drawdown"),
        "turnover_not_worse_than_always_on": decimal_value(
            expected["annualized_one_way_turnover"], "candidate turnover"
        )
        <= decimal_value(
            always_on_expected["annualized_one_way_turnover"], "always-on turnover"
        ),
    }
    reasons = tuple(key for key, passed in checks.items() if not passed)
    return {
        "status": "SELECTED" if not reasons else "REJECTED",
        "selected_policy": config["candidate_id"] if not reasons else None,
        "checks": checks,
        "rejection_reasons": reasons,
        "return_delta_vs_always_on": return_delta,
        "sharpe_delta_vs_always_on": sharpe_delta,
    }
