"""C6A five-window aggregation and frozen program-level decision."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

from atos.c6a_contract import C6AError, decimal_value
from atos.c6a_metrics import (
    CandidateMetrics,
    ComparatorMetrics,
    GateDecision,
    WeeklyStatistics,
    evaluate_gate,
    weekly_statistics,
)
from atos.c6a_replay import ReplayResult

ZERO = Decimal("0")
WINDOW_IDS = ("W1", "W2", "W3", "W4", "W5")
COST_LABELS = ("1.0x", "1.5x", "2.0x")


@dataclass(frozen=True)
class AggregateResult:
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
            "policy_id": self.policy_id,
            "cost_label": self.cost_label,
            "aggregate_return": str(self.aggregate_return),
            "window_returns": {key: str(value) for key, value in self.window_returns.items()},
            "window_pnl": {key: str(value) for key, value in self.window_pnl.items()},
            "weekly_returns": [str(value) for value in self.weekly_returns],
            "weekly_pnl": {key: str(value) for key, value in self.weekly_pnl.items()},
            "statistics": None if self.statistics is None else asdict(self.statistics),
            "statistics_error": self.statistics_error,
            "maximum_drawdown": str(self.maximum_drawdown),
            "annualized_one_way_turnover": str(self.annualized_one_way_turnover),
            "gross_funding_receipts": str(self.gross_funding_receipts),
            "gross_funding_payments": str(self.gross_funding_payments),
            "total_trading_costs": str(self.total_trading_costs),
            "funding_cost_coverage": (
                None if self.funding_cost_coverage is None else str(self.funding_cost_coverage)
            ),
            "active_weeks_total": self.active_weeks_total,
            "active_weeks_by_window": dict(self.active_weeks_by_window),
            "active_funding_settlements": self.active_funding_settlements,
            "collateral_buffer_breaches": self.collateral_buffer_breaches,
            "hedge_breaches": self.hedge_breaches,
            "asset_pnl": {key: str(value) for key, value in self.asset_pnl.items()},
        }


def aggregate_window_results(
    window_results: Sequence[Mapping[str, Any]],
    replay_results: Sequence[ReplayResult],
) -> AggregateResult:
    if len(window_results) != 5 or len(replay_results) != 5:
        raise C6AError("C6A aggregate requires five window results and five replays")
    by_window = {str(row.get("window_id")): row for row in window_results}
    if tuple(sorted(by_window)) != WINDOW_IDS or len(by_window) != 5:
        raise C6AError("C6A aggregate window set mismatch")
    ordered = [by_window[window_id] for window_id in WINDOW_IDS]
    policy_ids = {str(row.get("policy_id")) for row in ordered}
    cost_labels = {str(row.get("cost_label")) for row in ordered}
    if len(policy_ids) != 1 or len(cost_labels) != 1:
        raise C6AError("C6A aggregate mixes policy or cost labels")
    policy_id = next(iter(policy_ids))
    cost_label = next(iter(cost_labels))
    if cost_label not in COST_LABELS:
        raise C6AError("unknown C6A aggregate cost label")

    final_equities: list[Decimal] = []
    window_returns: dict[str, Decimal] = {}
    window_pnl: dict[str, Decimal] = {}
    weekly_returns: list[Decimal] = []
    weekly_pnl: dict[str, Decimal] = {}
    maximum_dd = ZERO
    turnover_values: list[Decimal] = []
    active_weeks: dict[str, int] = {}
    active_funding = 0
    collateral_breaches = 0
    hedge_breaches = 0
    asset_pnl = {"BTC": ZERO, "ETH": ZERO}
    total_costs = ZERO

    for row in ordered:
        window_id = str(row["window_id"])
        if decimal_value(row.get("starting_equity"), "window starting equity") != Decimal("1000"):
            raise C6AError("each C6A window must start from exactly 1000 USDT")
        final = decimal_value(row.get("final_equity"), "window final equity")
        retained_return = decimal_value(row.get("net_return"), "window return")
        if retained_return != final / Decimal("1000") - Decimal("1"):
            raise C6AError("window return/final-equity mismatch")
        buckets = row.get("weekly_buckets")
        if not isinstance(buckets, list) or len(buckets) != 26:
            raise C6AError("each C6A window must retain 26 weekly buckets")
        final_equities.append(final)
        window_returns[window_id] = retained_return
        window_pnl[window_id] = final - Decimal("1000")
        for index, bucket in enumerate(buckets):
            key = f"{window_id}-week-{index:02d}"
            weekly_returns.append(decimal_value(bucket.get("weekly_return"), "weekly return"))
            weekly_pnl[key] = decimal_value(bucket.get("weekly_pnl"), "weekly PnL")
        maximum_dd = max(maximum_dd, decimal_value(row.get("maximum_drawdown"), "drawdown"))
        turnover_values.append(
            decimal_value(row.get("annualized_one_way_turnover"), "window turnover")
        )
        active_weeks[window_id] = int(row.get("active_week_count", -1))
        active_funding += int(row.get("active_funding_settlements", -1))
        collateral_breaches += int(row.get("collateral_buffer_breaches", -1))
        hedge_breaches += int(row.get("hedge_breaches", -1))
        contributions = row.get("asset_contributions")
        if not isinstance(contributions, Mapping) or set(contributions) != {"BTC", "ETH"}:
            raise C6AError("window asset-contribution set mismatch")
        for asset in asset_pnl:
            asset_pnl[asset] += decimal_value(contributions[asset], f"{asset} contribution")
        components = row.get("components")
        if not isinstance(components, Mapping):
            raise C6AError("window components missing")
        total_costs += decimal_value(components.get("spot_cost"), "spot costs")
        total_costs += decimal_value(components.get("swap_cost"), "swap costs")

    if len(weekly_returns) != 130 or len(weekly_pnl) != 130:
        raise C6AError("C6A aggregate weekly count mismatch")
    if sum(window_pnl.values(), ZERO) != sum(weekly_pnl.values(), ZERO):
        raise C6AError("C6A aggregate window/weekly PnL mismatch")
    aggregate_return = sum(final_equities, ZERO) / Decimal("5000") - Decimal("1")
    if aggregate_return != sum(window_pnl.values(), ZERO) / Decimal("5000"):
        raise C6AError("C6A equal-capital aggregate return mismatch")

    statistics: WeeklyStatistics | None
    statistics_error: str | None
    try:
        statistics = weekly_statistics(weekly_returns)
        statistics_error = None
    except C6AError as exc:
        statistics = None
        statistics_error = str(exc)

    receipts = sum((row.gross_funding_receipts for row in replay_results), ZERO)
    payments = sum((row.gross_funding_payments for row in replay_results), ZERO)
    replay_active = sum(row.active_funding_settlements for row in replay_results)
    if replay_active != active_funding:
        raise C6AError("aggregate active funding count differs from replay")
    replay_turnover = sum((row.annualized_one_way_turnover for row in replay_results), ZERO) / Decimal("5")
    retained_turnover = sum(turnover_values, ZERO) / Decimal("5")
    if replay_turnover != retained_turnover:
        raise C6AError("aggregate turnover differs from replay")
    coverage = None if total_costs == 0 else receipts / total_costs

    return AggregateResult(
        policy_id=policy_id,
        cost_label=cost_label,
        aggregate_return=aggregate_return,
        window_returns=window_returns,
        window_pnl=window_pnl,
        weekly_returns=tuple(weekly_returns),
        weekly_pnl=weekly_pnl,
        statistics=statistics,
        statistics_error=statistics_error,
        maximum_drawdown=maximum_dd,
        annualized_one_way_turnover=retained_turnover,
        gross_funding_receipts=receipts,
        gross_funding_payments=payments,
        total_trading_costs=total_costs,
        funding_cost_coverage=coverage,
        active_weeks_total=sum(active_weeks.values()),
        active_weeks_by_window=active_weeks,
        active_funding_settlements=active_funding,
        collateral_buffer_breaches=collateral_breaches,
        hedge_breaches=hedge_breaches,
        asset_pnl=asset_pnl,
    )


def decide_candidate(
    *,
    candidate_by_cost: Mapping[str, AggregateResult],
    always_on_expected: AggregateResult,
    config: Mapping[str, Any],
) -> GateDecision:
    if set(candidate_by_cost) != set(COST_LABELS):
        raise C6AError("candidate aggregate cost set mismatch")
    expected = candidate_by_cost["1.0x"]
    if any(row.policy_id != config.get("candidate_id") for row in candidate_by_cost.values()):
        raise C6AError("candidate aggregate policy identity mismatch")
    if always_on_expected.policy_id != "AlwaysOnDeltaNeutralComparator":
        raise C6AError("always-on comparator identity mismatch")
    fail_closed: list[str] = []
    if expected.statistics is None:
        fail_closed.append("candidate_weekly_statistics")
    if always_on_expected.statistics is None:
        fail_closed.append("always_on_weekly_statistics")
    if expected.funding_cost_coverage is None:
        fail_closed.append("funding_cost_coverage_denominator")
    if not any(value > 0 for value in expected.asset_pnl.values()):
        fail_closed.append("positive_asset_concentration_denominator")
    if not any(value > 0 for value in expected.window_pnl.values()):
        fail_closed.append("positive_window_concentration_denominator")
    if not any(value > 0 for value in expected.weekly_pnl.values()):
        fail_closed.append("positive_week_concentration_denominator")
    if fail_closed:
        return GateDecision(
            status="REJECTED",
            selected_policy=None,
            checks={reason: False for reason in fail_closed},
            margins={},
            rejection_reasons=tuple(fail_closed),
        )
    assert expected.statistics is not None
    assert always_on_expected.statistics is not None
    assert expected.funding_cost_coverage is not None
    metrics = CandidateMetrics(
        window_returns=expected.window_returns,
        aggregate_returns_by_cost={
            label: candidate_by_cost[label].aggregate_return for label in COST_LABELS
        },
        annualized_weekly_sharpe=Decimal(str(expected.statistics.annualized_weekly_sharpe)),
        weekly_psr=Decimal(str(expected.statistics.psr_probability)),
        maximum_drawdown=expected.maximum_drawdown,
        collateral_buffer_breaches=expected.collateral_buffer_breaches,
        hedge_breaches=expected.hedge_breaches,
        annualized_turnover=expected.annualized_one_way_turnover,
        funding_cost_coverage=expected.funding_cost_coverage,
        active_weeks_total=expected.active_weeks_total,
        active_weeks_by_window=expected.active_weeks_by_window,
        active_funding_settlements=expected.active_funding_settlements,
        asset_pnl=expected.asset_pnl,
        window_pnl=expected.window_pnl,
        week_pnl=expected.weekly_pnl,
        always_on=ComparatorMetrics(
            aggregate_return=always_on_expected.aggregate_return,
            annualized_weekly_sharpe=Decimal(
                str(always_on_expected.statistics.annualized_weekly_sharpe)
            ),
            maximum_drawdown=always_on_expected.maximum_drawdown,
            annualized_turnover=always_on_expected.annualized_one_way_turnover,
        ),
    )
    return evaluate_gate(metrics, config)
