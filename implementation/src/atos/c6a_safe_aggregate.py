"""Production C6A aggregation and gate with explicit undefined-stat handling.

A candidate that never trades, or otherwise produces zero weekly variance,
must be economically rejected rather than crashing the authoritative run.  This
module preserves the frozen aggregate/gate semantics while representing
undefined statistics and zero positive-concentration denominators as explicit
failed checks.  The independent strict finalizer recomputes the same outcome
without importing this module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from atos.c6a_contract import C6AError, decimal_value
from atos.c6a_metrics import GateDecision, WeeklyStatistics, weekly_statistics

ZERO = Decimal("0")
ONE = Decimal("1")
WINDOW_IDS = ("W1", "W2", "W3", "W4", "W5")
COST_LABELS = ("1.0x", "1.5x", "2.0x")


@dataclass(frozen=True)
class SafeAggregateResult:
    policy_id: str
    cost_label: str
    aggregate_return: Decimal
    window_returns: Mapping[str, Decimal]
    window_pnl: Mapping[str, Decimal]
    weekly_returns: tuple[Decimal, ...]
    weekly_pnl: Mapping[str, Decimal]
    statistics: WeeklyStatistics | None
    statistics_error: str | None
    maximum_drawdown: Decimal
    annualized_one_way_turnover: Decimal
    gross_funding_receipts: Decimal
    gross_funding_payments: Decimal
    total_trading_costs: Decimal
    funding_cost_coverage: Decimal | None
    active_weeks_total: int
    active_weeks_by_window: Mapping[str, int]
    active_funding_settlements: int
    collateral_buffer_breaches: int
    hedge_breaches: int
    asset_pnl: Mapping[str, Decimal]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "stage": "C6A",
            "status": "PASS",
            "policy_id": self.policy_id,
            "cost_label": self.cost_label,
            "aggregate_return": str(self.aggregate_return),
            "window_returns": {
                key: str(value) for key, value in self.window_returns.items()
            },
            "window_pnl": {key: str(value) for key, value in self.window_pnl.items()},
            "weekly_returns": [str(value) for value in self.weekly_returns],
            "weekly_pnl": {key: str(value) for key, value in self.weekly_pnl.items()},
            "statistics": None if self.statistics is None else asdict(self.statistics),
            "statistics_error": self.statistics_error,
            "maximum_drawdown": str(self.maximum_drawdown),
            "annualized_one_way_turnover": str(
                self.annualized_one_way_turnover
            ),
            "gross_funding_receipts": str(self.gross_funding_receipts),
            "gross_funding_payments": str(self.gross_funding_payments),
            "total_trading_costs": str(self.total_trading_costs),
            "funding_cost_coverage": (
                None
                if self.funding_cost_coverage is None
                else str(self.funding_cost_coverage)
            ),
            "active_weeks_total": self.active_weeks_total,
            "active_weeks_by_window": dict(self.active_weeks_by_window),
            "active_funding_settlements": self.active_funding_settlements,
            "collateral_buffer_breaches": self.collateral_buffer_breaches,
            "hedge_breaches": self.hedge_breaches,
            "asset_pnl": {key: str(value) for key, value in self.asset_pnl.items()},
            "selectable": self.policy_id == "C6AMarketNeutralFundingCarry",
            "c6b_state": "C6B_CLOSED",
            "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
            "holdout_state": "HOLDOUT_CLOSED",
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live": "FORBIDDEN",
        }


def _decimal(value: Any, label: str) -> Decimal:
    return decimal_value(value, label)


def aggregate_window_results_safe(
    results: Sequence[Mapping[str, Any]], replays: Sequence[Any]
) -> SafeAggregateResult:
    if len(results) != 5 or len(replays) != 5:
        raise C6AError("C6A safe aggregate requires five windows and replays")
    by_id = {str(row.get("window_id")): row for row in results}
    if set(by_id) != set(WINDOW_IDS) or len(by_id) != len(results):
        raise C6AError("C6A safe aggregate window set mismatch")
    ordered = [by_id[window] for window in WINDOW_IDS]
    identities = {
        (str(row.get("policy_id")), str(row.get("cost_label"))) for row in ordered
    }
    if len(identities) != 1:
        raise C6AError("C6A safe aggregate mixes policy or cost")
    policy_id, cost_label = next(iter(identities))
    weekly_rows = [bucket for row in ordered for bucket in row["weekly_buckets"]]
    if len(weekly_rows) != 130:
        raise C6AError("C6A safe aggregate weekly count mismatch")
    weekly_returns = tuple(
        _decimal(bucket["weekly_return"], "weekly return") for bucket in weekly_rows
    )
    try:
        statistics = weekly_statistics(weekly_returns)
        statistics_error = None
    except C6AError as exc:
        statistics = None
        statistics_error = str(exc)
    final_equities = [_decimal(row["final_equity"], "final equity") for row in ordered]
    window_returns = {
        row["window_id"]: _decimal(row["net_return"], "window return")
        for row in ordered
    }
    window_pnl = {
        row["window_id"]: _decimal(row["final_equity"], "final equity")
        - Decimal("1000")
        for row in ordered
    }
    weekly_pnl = {
        f"{row['window_id']}-week-{index:02d}": _decimal(
            bucket["weekly_pnl"], "weekly PnL"
        )
        for row in ordered
        for index, bucket in enumerate(row["weekly_buckets"])
    }
    if sum(window_pnl.values(), ZERO) != sum(weekly_pnl.values(), ZERO):
        raise C6AError("C6A safe aggregate window/weekly PnL mismatch")
    receipts = ZERO
    payments = ZERO
    for row in ordered:
        for event in row.get("events", []):
            if isinstance(event, Mapping) and event.get("kind") == "FUNDING":
                pnl = _decimal(event.get("pnl"), "funding event PnL")
                receipts += max(pnl, ZERO)
                payments += max(-pnl, ZERO)
    total_costs = sum(
        (
            _decimal(row["components"]["spot_cost"], "spot cost")
            + _decimal(row["components"]["swap_cost"], "swap cost")
            for row in ordered
        ),
        ZERO,
    )
    asset_pnl = {"BTC": ZERO, "ETH": ZERO}
    for row in ordered:
        contributions = row.get("asset_contributions")
        if not isinstance(contributions, Mapping) or set(contributions) != set(asset_pnl):
            raise C6AError("C6A safe aggregate asset contribution set mismatch")
        for asset in asset_pnl:
            asset_pnl[asset] += _decimal(
                contributions[asset], f"{asset} contribution"
            )
    return SafeAggregateResult(
        policy_id=policy_id,
        cost_label=cost_label,
        aggregate_return=sum(final_equities, ZERO) / Decimal("5000") - ONE,
        window_returns=window_returns,
        window_pnl=window_pnl,
        weekly_returns=weekly_returns,
        weekly_pnl=weekly_pnl,
        statistics=statistics,
        statistics_error=statistics_error,
        maximum_drawdown=max(
            _decimal(row["maximum_drawdown"], "maximum drawdown")
            for row in ordered
        ),
        annualized_one_way_turnover=sum(
            (
                _decimal(
                    row["annualized_one_way_turnover"], "annualized turnover"
                )
                for row in ordered
            ),
            ZERO,
        )
        / Decimal("5"),
        gross_funding_receipts=receipts,
        gross_funding_payments=payments,
        total_trading_costs=total_costs,
        funding_cost_coverage=None if total_costs == 0 else receipts / total_costs,
        active_weeks_total=sum(int(row["active_week_count"]) for row in ordered),
        active_weeks_by_window={
            row["window_id"]: int(row["active_week_count"]) for row in ordered
        },
        active_funding_settlements=sum(
            int(row["active_funding_settlements"]) for row in ordered
        ),
        collateral_buffer_breaches=sum(
            int(row["collateral_buffer_breaches"]) for row in ordered
        ),
        hedge_breaches=sum(int(row["hedge_breaches"]) for row in ordered),
        asset_pnl=asset_pnl,
    )


def _positive_shares(values: Mapping[str, Decimal]) -> tuple[Decimal, Decimal] | None:
    positive = sorted((max(value, ZERO) for value in values.values()), reverse=True)
    denominator = sum(positive, ZERO)
    if denominator <= 0:
        return None
    return positive[0] / denominator, sum(positive[:3], ZERO) / denominator


def decide_candidate_safe(
    *,
    candidate_by_cost: Mapping[str, SafeAggregateResult],
    always_on_expected: SafeAggregateResult,
    config: Mapping[str, Any],
) -> GateDecision:
    if set(candidate_by_cost) != set(COST_LABELS):
        raise C6AError("C6A safe gate cost set mismatch")
    expected = candidate_by_cost["1.0x"]
    stress = candidate_by_cost["1.5x"]
    severe = candidate_by_cost["2.0x"]
    undefined: list[str] = []
    if expected.statistics is None:
        undefined.append("candidate_weekly_statistics")
    if always_on_expected.statistics is None:
        undefined.append("always_on_weekly_statistics")
    if expected.funding_cost_coverage is None:
        undefined.append("funding_cost_coverage_denominator")
    asset_share = _positive_shares(expected.asset_pnl)
    window_share = _positive_shares(expected.window_pnl)
    week_share = _positive_shares(expected.weekly_pnl)
    if asset_share is None:
        undefined.append("positive_asset_concentration_denominator")
    if window_share is None:
        undefined.append("positive_window_concentration_denominator")
    if week_share is None:
        undefined.append("positive_week_concentration_denominator")
    if undefined:
        unique = tuple(dict.fromkeys(undefined))
        return GateDecision(
            status="REJECTED",
            selected_policy=None,
            checks={reason: False for reason in unique},
            margins={},
            rejection_reasons=unique,
        )
    assert expected.statistics is not None
    assert always_on_expected.statistics is not None
    assert expected.funding_cost_coverage is not None
    assert asset_share is not None and window_share is not None and week_share is not None
    gate = config["gate"]
    return_delta = expected.aggregate_return - always_on_expected.aggregate_return
    sharpe_delta = Decimal(str(expected.statistics.annualized_weekly_sharpe)) - Decimal(
        str(always_on_expected.statistics.annualized_weekly_sharpe)
    )
    checks = {
        "all_windows_positive": all(value > 0 for value in expected.window_returns.values()),
        "aggregate_expected_return": expected.aggregate_return
        > _decimal(gate["minimum_aggregate_return_exclusive"], "return gate"),
        "aggregate_1_5x_return": stress.aggregate_return
        > _decimal(gate["minimum_aggregate_1_5x_return_exclusive"], "stress gate"),
        "aggregate_2x_return": severe.aggregate_return
        >= _decimal(gate["minimum_aggregate_2x_return"], "severe gate"),
        "annualized_weekly_sharpe": Decimal(
            str(expected.statistics.annualized_weekly_sharpe)
        )
        >= _decimal(gate["minimum_annualized_weekly_sharpe"], "Sharpe gate"),
        "weekly_psr": Decimal(str(expected.statistics.psr_probability))
        >= _decimal(gate["minimum_weekly_psr"], "PSR gate"),
        "maximum_drawdown": expected.maximum_drawdown
        <= _decimal(gate["maximum_drawdown"], "drawdown gate"),
        "zero_collateral_buffer_breaches": expected.collateral_buffer_breaches == 0,
        "zero_hedge_breaches": expected.hedge_breaches == 0,
        "annualized_turnover": expected.annualized_one_way_turnover
        <= _decimal(gate["maximum_annualized_one_way_turnover"], "turnover gate"),
        "funding_cost_coverage": expected.funding_cost_coverage
        >= _decimal(gate["minimum_funding_cost_coverage"], "coverage gate"),
        "active_weeks_total": expected.active_weeks_total
        >= int(gate["minimum_active_weeks_total"]),
        "active_weeks_each_window": all(
            value >= int(gate["minimum_active_weeks_per_window"])
            for value in expected.active_weeks_by_window.values()
        ),
        "active_funding_settlements": expected.active_funding_settlements
        >= int(gate["minimum_active_funding_settlements"]),
        "both_assets_positive": all(value > 0 for value in expected.asset_pnl.values()),
        "asset_concentration": asset_share[0]
        <= _decimal(gate["maximum_positive_asset_pnl_share"], "asset share"),
        "window_concentration": window_share[0]
        <= _decimal(gate["maximum_positive_window_pnl_share"], "window share"),
        "week_concentration": week_share[0]
        <= _decimal(gate["maximum_positive_week_pnl_share"], "week share"),
        "top_three_week_concentration": week_share[1]
        <= _decimal(
            gate["maximum_top_three_positive_week_pnl_share"], "top-three share"
        ),
        "return_delta_vs_always_on": return_delta
        > _decimal(
            gate["minimum_return_delta_vs_always_on_exclusive"], "return delta"
        ),
        "sharpe_delta_vs_always_on": sharpe_delta
        >= _decimal(gate["minimum_sharpe_delta_vs_always_on"], "Sharpe delta"),
        "drawdown_not_worse_than_always_on": expected.maximum_drawdown
        <= always_on_expected.maximum_drawdown,
        "turnover_not_worse_than_always_on": expected.annualized_one_way_turnover
        <= always_on_expected.annualized_one_way_turnover,
    }
    margins = {
        "expected_return_minus_zero": expected.aggregate_return,
        "stress_return_minus_zero": stress.aggregate_return,
        "severe_return_minus_zero": severe.aggregate_return,
        "return_delta_vs_always_on": return_delta,
        "sharpe_delta_vs_always_on": sharpe_delta,
    }
    reasons = tuple(key for key, passed in checks.items() if not passed)
    return GateDecision(
        status="SELECTED" if not reasons else "REJECTED",
        selected_policy=(
            str(config["candidate_id"]) if not reasons else None
        ),
        checks=checks,
        margins=margins,
        rejection_reasons=reasons,
    )
