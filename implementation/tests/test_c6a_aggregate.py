from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from atos.c6a_aggregate import AggregateResult, aggregate_window_results, decide_candidate
from atos.c6a_metrics import weekly_statistics
from atos.c6a_replay import ReplayResult

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"
ZERO = Decimal("0")


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def window_result(window_id: str) -> dict:
    buckets = []
    for index in range(26):
        pnl = Decimal("10") if index == 25 else ZERO
        buckets.append(
            {
                "weekly_pnl": str(pnl),
                "weekly_return": str(Decimal("0.01") if index == 25 else ZERO),
                "active": index < 20,
            }
        )
    return {
        "policy_id": "C6AMarketNeutralFundingCarry",
        "cost_label": "1.0x",
        "window_id": window_id,
        "starting_equity": "1000",
        "final_equity": "1010",
        "net_return": "0.01",
        "maximum_drawdown": "0.02",
        "annualized_one_way_turnover": "0.4",
        "active_week_count": 20,
        "active_funding_settlements": 20,
        "collateral_buffer_breaches": 0,
        "hedge_breaches": 0,
        "asset_contributions": {"BTC": "6", "ETH": "4"},
        "components": {
            "spot_price_pnl": "0",
            "perpetual_price_pnl": "0",
            "funding_pnl": "12",
            "spot_cost": "1",
            "swap_cost": "1",
        },
        "weekly_buckets": buckets,
    }


def replay() -> ReplayResult:
    return ReplayResult(
        gross_funding_receipts=Decimal("5"),
        gross_funding_payments=Decimal("1"),
        net_funding_pnl=Decimal("4"),
        active_funding_settlements=20,
        normalized_turnover_events=(),
        annualized_one_way_turnover=Decimal("0.4"),
        funding_rows=(),
    )


def test_equal_capital_five_window_aggregation() -> None:
    aggregate = aggregate_window_results(
        [window_result(f"W{i}") for i in range(1, 6)],
        [replay() for _ in range(5)],
    )
    assert aggregate.aggregate_return == Decimal("0.01")
    assert len(aggregate.weekly_returns) == 130
    assert aggregate.statistics is not None
    assert aggregate.maximum_drawdown == Decimal("0.02")
    assert aggregate.annualized_one_way_turnover == Decimal("0.4")
    assert aggregate.gross_funding_receipts == Decimal("25")
    assert aggregate.gross_funding_payments == Decimal("5")
    assert aggregate.total_trading_costs == Decimal("10")
    assert aggregate.funding_cost_coverage == Decimal("2.5")
    assert aggregate.active_weeks_total == 100
    assert aggregate.asset_pnl == {"BTC": Decimal("30"), "ETH": Decimal("20")}


def aggregate_result(
    *,
    policy_id: str,
    cost_label: str,
    aggregate_return: str,
    sharpe_returns: list[Decimal],
) -> AggregateResult:
    stats = weekly_statistics(sharpe_returns)
    return AggregateResult(
        policy_id=policy_id,
        cost_label=cost_label,
        aggregate_return=Decimal(aggregate_return),
        window_returns={f"W{i}": Decimal("0.03") for i in range(1, 6)},
        window_pnl={f"W{i}": Decimal("20") for i in range(1, 6)},
        weekly_returns=tuple(sharpe_returns),
        weekly_pnl={f"week-{i:03d}": Decimal("1") for i in range(130)},
        statistics=stats,
        statistics_error=None,
        maximum_drawdown=Decimal("0.06"),
        annualized_one_way_turnover=Decimal("4"),
        gross_funding_receipts=Decimal("30"),
        gross_funding_payments=Decimal("2"),
        total_trading_costs=Decimal("10"),
        funding_cost_coverage=Decimal("3"),
        active_weeks_total=80,
        active_weeks_by_window={f"W{i}": 16 for i in range(1, 6)},
        active_funding_settlements=300,
        collateral_buffer_breaches=0,
        hedge_breaches=0,
        asset_pnl={"BTC": Decimal("55"), "ETH": Decimal("45")},
    )


def test_program_decision_uses_all_costs_and_always_on_delta() -> None:
    candidate_returns = [Decimal("0.003") + Decimal(i % 7 - 3) / Decimal("1000") for i in range(130)]
    always_returns = [Decimal("0.002") + Decimal(i % 7 - 3) / Decimal("1000") for i in range(130)]
    candidate = {
        "1.0x": aggregate_result(
            policy_id="C6AMarketNeutralFundingCarry",
            cost_label="1.0x",
            aggregate_return="0.15",
            sharpe_returns=candidate_returns,
        ),
        "1.5x": aggregate_result(
            policy_id="C6AMarketNeutralFundingCarry",
            cost_label="1.5x",
            aggregate_return="0.10",
            sharpe_returns=candidate_returns,
        ),
        "2.0x": aggregate_result(
            policy_id="C6AMarketNeutralFundingCarry",
            cost_label="2.0x",
            aggregate_return="0.05",
            sharpe_returns=candidate_returns,
        ),
    }
    always_on = aggregate_result(
        policy_id="AlwaysOnDeltaNeutralComparator",
        cost_label="1.0x",
        aggregate_return="0.10",
        sharpe_returns=always_returns,
    )
    always_on = AggregateResult(
        **{
            **always_on.__dict__,
            "maximum_drawdown": Decimal("0.08"),
            "annualized_one_way_turnover": Decimal("5"),
        }
    )
    decision = decide_candidate(
        candidate_by_cost=candidate,
        always_on_expected=always_on,
        config=config(),
    )
    assert decision.status == "SELECTED"
    assert decision.selected_policy == "C6AMarketNeutralFundingCarry"
    assert all(decision.checks.values())


def test_missing_weekly_statistics_fails_closed_not_selected() -> None:
    returns = [Decimal("0.003") + Decimal(i % 7 - 3) / Decimal("1000") for i in range(130)]
    expected = aggregate_result(
        policy_id="C6AMarketNeutralFundingCarry",
        cost_label="1.0x",
        aggregate_return="0.15",
        sharpe_returns=returns,
    )
    expected = AggregateResult(
        **{**expected.__dict__, "statistics": None, "statistics_error": "zero variance"}
    )
    candidate = {
        "1.0x": expected,
        "1.5x": AggregateResult(**{**expected.__dict__, "cost_label": "1.5x"}),
        "2.0x": AggregateResult(**{**expected.__dict__, "cost_label": "2.0x"}),
    }
    always_on = aggregate_result(
        policy_id="AlwaysOnDeltaNeutralComparator",
        cost_label="1.0x",
        aggregate_return="0.10",
        sharpe_returns=returns,
    )
    decision = decide_candidate(
        candidate_by_cost=candidate,
        always_on_expected=always_on,
        config=config(),
    )
    assert decision.status == "REJECTED"
    assert decision.selected_policy is None
    assert "candidate_weekly_statistics" in decision.rejection_reasons
