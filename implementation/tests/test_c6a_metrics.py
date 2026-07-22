from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from atos.c6a_contract import C6AError
from atos.c6a_metrics import (
    CandidateMetrics,
    ComparatorMetrics,
    annualized_one_way_turnover,
    evaluate_gate,
    maximum_drawdown,
    positive_concentration,
    weekly_statistics,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def passing_metrics() -> CandidateMetrics:
    return CandidateMetrics(
        window_returns={f"W{i}": Decimal("0.03") for i in range(1, 6)},
        aggregate_returns_by_cost={
            "1.0x": Decimal("0.15"),
            "1.5x": Decimal("0.10"),
            "2.0x": Decimal("0.05"),
        },
        annualized_weekly_sharpe=Decimal("1.40"),
        weekly_psr=Decimal("0.98"),
        maximum_drawdown=Decimal("0.06"),
        collateral_buffer_breaches=0,
        hedge_breaches=0,
        annualized_turnover=Decimal("4.0"),
        funding_cost_coverage=Decimal("3.0"),
        active_weeks_total=80,
        active_weeks_by_window={f"W{i}": 16 for i in range(1, 6)},
        active_funding_settlements=300,
        asset_pnl={"BTC": Decimal("55"), "ETH": Decimal("45")},
        window_pnl={f"W{i}": Decimal("20") for i in range(1, 6)},
        week_pnl={f"week-{i:03d}": Decimal("1") for i in range(130)},
        always_on=ComparatorMetrics(
            aggregate_return=Decimal("0.10"),
            annualized_weekly_sharpe=Decimal("1.20"),
            maximum_drawdown=Decimal("0.08"),
            annualized_turnover=Decimal("5.0"),
        ),
    )


def test_weekly_statistics_retains_psr_not_dsr_fields() -> None:
    returns = [Decimal("0.003") + Decimal(i % 7 - 3) / Decimal("1000") for i in range(130)]
    result = weekly_statistics(returns)
    assert result.n == 130
    assert result.sample_std > 0
    assert result.annualized_weekly_sharpe > 0
    assert 0 <= result.psr_probability <= 1
    assert result.weekly_statistic == "PSR_NOT_DSR"
    assert result.program_level_sequential_history_corrected is False


def test_weekly_statistics_requires_all_130_weeks_and_variance() -> None:
    with pytest.raises(C6AError, match="count"):
        weekly_statistics([Decimal("0.01")] * 129)
    with pytest.raises(C6AError, match="standard deviation"):
        weekly_statistics([Decimal("0.01")] * 130)


def test_drawdown_and_turnover_are_program_definitions() -> None:
    assert maximum_drawdown(["100", "120", "90", "135"]) == Decimal("0.25")
    assert annualized_one_way_turnover(["0.1"] * 10) == Decimal("0.4")
    with pytest.raises(C6AError):
        maximum_drawdown(["100", "0"])


def test_positive_concentration_retains_exact_shares() -> None:
    result = positive_concentration({"a": "7", "b": "2", "c": "1", "d": "-99"})
    assert result.positive_denominator == Decimal("10")
    assert result.maximum_share == Decimal("0.7")
    assert result.top_three_share == Decimal("1")
    with pytest.raises(C6AError, match="denominator"):
        positive_concentration({"a": "0", "b": "-1"})


def test_frozen_gate_selects_only_when_every_check_passes() -> None:
    decision = evaluate_gate(passing_metrics(), config())
    assert decision.status == "SELECTED"
    assert decision.selected_policy == "C6AMarketNeutralFundingCarry"
    assert decision.rejection_reasons == ()
    assert all(decision.checks.values())


def test_relatively_good_but_ineligible_result_is_rejected() -> None:
    base = passing_metrics()
    failed = CandidateMetrics(
        **{
            **base.__dict__,
            "window_returns": {**base.window_returns, "W3": Decimal("-0.001")},
            "asset_pnl": {"BTC": Decimal("100"), "ETH": Decimal("-1")},
            "annualized_turnover": Decimal("6.01"),
        }
    )
    decision = evaluate_gate(failed, config())
    assert decision.status == "REJECTED"
    assert decision.selected_policy is None
    assert "all_windows_positive" in decision.rejection_reasons
    assert "both_assets_positive" in decision.rejection_reasons
    assert "asset_concentration" in decision.rejection_reasons
    assert "annualized_turnover" in decision.rejection_reasons


def test_always_on_incremental_gates_are_strict() -> None:
    base = passing_metrics()
    no_increment = CandidateMetrics(
        **{
            **base.__dict__,
            "always_on": ComparatorMetrics(
                aggregate_return=base.aggregate_returns_by_cost["1.0x"],
                annualized_weekly_sharpe=Decimal("1.35"),
                maximum_drawdown=Decimal("0.05"),
                annualized_turnover=Decimal("3.5"),
            ),
        }
    )
    decision = evaluate_gate(no_increment, config())
    assert "return_delta_vs_always_on" in decision.rejection_reasons
    assert "sharpe_delta_vs_always_on" in decision.rejection_reasons
    assert "drawdown_not_worse_than_always_on" in decision.rejection_reasons
    assert "turnover_not_worse_than_always_on" in decision.rejection_reasons
