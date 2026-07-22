"""Frozen C6A statistics, concentration, and eligibility gates."""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import kurtosis, norm, skew

from atos.c6a_contract import C6AError, decimal_value


@dataclass(frozen=True)
class WeeklyStatistics:
    n: int
    mean: float
    sample_std: float
    weekly_sharpe: float
    annualized_weekly_sharpe: float
    unbiased_skewness: float
    unbiased_ordinary_kurtosis: float
    psr_numerator: float
    psr_denominator: float
    psr_z_score: float
    psr_probability: float
    weekly_statistic: str = "PSR_NOT_DSR"
    program_level_sequential_history_corrected: bool = False


def weekly_statistics(returns: Sequence[Any], *, require_n: int = 130) -> WeeklyStatistics:
    values = np.asarray([float(decimal_value(value, "weekly return")) for value in returns], dtype=float)
    if len(values) != require_n:
        raise C6AError(f"weekly return count must be {require_n}, found {len(values)}")
    if not np.isfinite(values).all():
        raise C6AError("weekly returns must be finite")
    sample_std = float(np.std(values, ddof=1))
    if not math.isfinite(sample_std) or sample_std <= 0:
        raise C6AError("weekly sample standard deviation must be positive")
    mean = float(np.mean(values))
    weekly_sharpe = mean / sample_std
    sample_skew = float(skew(values, bias=False))
    ordinary_kurtosis = float(kurtosis(values, fisher=False, bias=False))
    denominator_squared = (
        1.0
        - sample_skew * weekly_sharpe
        + ((ordinary_kurtosis - 1.0) / 4.0) * weekly_sharpe**2
    )
    if not math.isfinite(denominator_squared) or denominator_squared <= 0:
        raise C6AError("PSR denominator is non-positive")
    numerator = weekly_sharpe * math.sqrt(len(values) - 1)
    denominator = math.sqrt(denominator_squared)
    z_score = numerator / denominator
    probability = float(norm.cdf(z_score))
    fields = (
        mean,
        sample_std,
        weekly_sharpe,
        sample_skew,
        ordinary_kurtosis,
        numerator,
        denominator,
        z_score,
        probability,
    )
    if not all(math.isfinite(value) for value in fields):
        raise C6AError("non-finite weekly statistic")
    return WeeklyStatistics(
        n=len(values),
        mean=mean,
        sample_std=sample_std,
        weekly_sharpe=weekly_sharpe,
        annualized_weekly_sharpe=weekly_sharpe * math.sqrt(52),
        unbiased_skewness=sample_skew,
        unbiased_ordinary_kurtosis=ordinary_kurtosis,
        psr_numerator=numerator,
        psr_denominator=denominator,
        psr_z_score=z_score,
        psr_probability=probability,
    )


def maximum_drawdown(equity: Sequence[Any]) -> Decimal:
    values = [decimal_value(value, "equity") for value in equity]
    if not values or any(value <= 0 for value in values):
        raise C6AError("equity path must be non-empty and positive")
    peak = values[0]
    maximum = Decimal("0")
    for value in values:
        peak = max(peak, value)
        maximum = max(maximum, Decimal("1") - value / peak)
    return maximum


def annualized_one_way_turnover(
    normalized_event_turnover: Sequence[Any], *, scored_weeks: int = 130
) -> Decimal:
    if scored_weeks <= 0:
        raise C6AError("scored weeks must be positive")
    total = sum(
        (decimal_value(value, "normalized turnover") for value in normalized_event_turnover),
        Decimal("0"),
    )
    if total < 0:
        raise C6AError("turnover cannot be negative")
    return total / (Decimal(scored_weeks) / Decimal(52))


@dataclass(frozen=True)
class Concentration:
    positive_denominator: Decimal
    shares: Mapping[str, Decimal]
    maximum_share: Decimal
    top_three_share: Decimal


def positive_concentration(values: Mapping[str, Any]) -> Concentration:
    positive = {
        str(key): max(decimal_value(value, f"PnL {key}"), Decimal("0"))
        for key, value in values.items()
    }
    denominator = sum(positive.values(), Decimal("0"))
    if denominator <= 0:
        raise C6AError("positive concentration denominator is zero")
    shares = {key: value / denominator for key, value in positive.items()}
    ordered = sorted(shares.values(), reverse=True)
    return Concentration(
        positive_denominator=denominator,
        shares=shares,
        maximum_share=ordered[0],
        top_three_share=sum(ordered[:3], Decimal("0")),
    )


@dataclass(frozen=True)
class ComparatorMetrics:
    aggregate_return: Decimal
    annualized_weekly_sharpe: Decimal
    maximum_drawdown: Decimal
    annualized_turnover: Decimal


@dataclass(frozen=True)
class CandidateMetrics:
    window_returns: Mapping[str, Decimal]
    aggregate_returns_by_cost: Mapping[str, Decimal]
    annualized_weekly_sharpe: Decimal
    weekly_psr: Decimal
    maximum_drawdown: Decimal
    collateral_buffer_breaches: int
    hedge_breaches: int
    annualized_turnover: Decimal
    funding_cost_coverage: Decimal
    active_weeks_total: int
    active_weeks_by_window: Mapping[str, int]
    active_funding_settlements: int
    asset_pnl: Mapping[str, Decimal]
    window_pnl: Mapping[str, Decimal]
    week_pnl: Mapping[str, Decimal]
    always_on: ComparatorMetrics


@dataclass(frozen=True)
class GateDecision:
    status: str
    selected_policy: str | None
    checks: Mapping[str, bool]
    margins: Mapping[str, Decimal]
    rejection_reasons: tuple[str, ...]


def _d(value: Any, label: str) -> Decimal:
    return decimal_value(value, label)


def evaluate_gate(
    metrics: CandidateMetrics, config: Mapping[str, Any]
) -> GateDecision:
    gate = config.get("gate")
    if not isinstance(gate, Mapping):
        raise C6AError("missing C6A gate configuration")
    expected = metrics.aggregate_returns_by_cost.get("1.0x")
    stress = metrics.aggregate_returns_by_cost.get("1.5x")
    severe = metrics.aggregate_returns_by_cost.get("2.0x")
    if expected is None or stress is None or severe is None:
        raise C6AError("missing cost-scenario aggregate return")
    if set(metrics.window_returns) != {"W1", "W2", "W3", "W4", "W5"}:
        raise C6AError("window-return set mismatch")
    if set(metrics.active_weeks_by_window) != {"W1", "W2", "W3", "W4", "W5"}:
        raise C6AError("active-week window set mismatch")
    if set(metrics.asset_pnl) != {"BTC", "ETH"}:
        raise C6AError("asset-contribution set mismatch")

    asset_concentration = positive_concentration(metrics.asset_pnl)
    window_concentration = positive_concentration(metrics.window_pnl)
    week_concentration = positive_concentration(metrics.week_pnl)
    return_delta = expected - metrics.always_on.aggregate_return
    sharpe_delta = (
        metrics.annualized_weekly_sharpe
        - metrics.always_on.annualized_weekly_sharpe
    )

    checks = {
        "all_windows_positive": all(value > 0 for value in metrics.window_returns.values()),
        "aggregate_expected_return": expected
        > _d(gate["minimum_aggregate_return_exclusive"], "expected return gate"),
        "aggregate_1_5x_return": stress
        > _d(gate["minimum_aggregate_1_5x_return_exclusive"], "1.5x return gate"),
        "aggregate_2x_return": severe
        >= _d(gate["minimum_aggregate_2x_return"], "2x return gate"),
        "annualized_weekly_sharpe": metrics.annualized_weekly_sharpe
        >= _d(gate["minimum_annualized_weekly_sharpe"], "Sharpe gate"),
        "weekly_psr": metrics.weekly_psr
        >= _d(gate["minimum_weekly_psr"], "PSR gate"),
        "maximum_drawdown": metrics.maximum_drawdown
        <= _d(gate["maximum_drawdown"], "drawdown gate"),
        "zero_collateral_buffer_breaches": metrics.collateral_buffer_breaches == 0,
        "zero_hedge_breaches": metrics.hedge_breaches == 0,
        "annualized_turnover": metrics.annualized_turnover
        <= _d(gate["maximum_annualized_one_way_turnover"], "turnover gate"),
        "funding_cost_coverage": metrics.funding_cost_coverage
        >= _d(gate["minimum_funding_cost_coverage"], "funding coverage gate"),
        "active_weeks_total": metrics.active_weeks_total
        >= int(gate["minimum_active_weeks_total"]),
        "active_weeks_each_window": all(
            value >= int(gate["minimum_active_weeks_per_window"])
            for value in metrics.active_weeks_by_window.values()
        ),
        "active_funding_settlements": metrics.active_funding_settlements
        >= int(gate["minimum_active_funding_settlements"]),
        "both_assets_positive": all(value > 0 for value in metrics.asset_pnl.values()),
        "asset_concentration": asset_concentration.maximum_share
        <= _d(gate["maximum_positive_asset_pnl_share"], "asset concentration gate"),
        "window_concentration": window_concentration.maximum_share
        <= _d(gate["maximum_positive_window_pnl_share"], "window concentration gate"),
        "week_concentration": week_concentration.maximum_share
        <= _d(gate["maximum_positive_week_pnl_share"], "week concentration gate"),
        "top_three_week_concentration": week_concentration.top_three_share
        <= _d(
            gate["maximum_top_three_positive_week_pnl_share"],
            "top-three concentration gate",
        ),
        "return_delta_vs_always_on": return_delta
        > _d(
            gate["minimum_return_delta_vs_always_on_exclusive"],
            "return delta gate",
        ),
        "sharpe_delta_vs_always_on": sharpe_delta
        >= _d(gate["minimum_sharpe_delta_vs_always_on"], "Sharpe delta gate"),
        "drawdown_not_worse_than_always_on": metrics.maximum_drawdown
        <= metrics.always_on.maximum_drawdown,
        "turnover_not_worse_than_always_on": metrics.annualized_turnover
        <= metrics.always_on.annualized_turnover,
    }
    margins = {
        "expected_return_minus_zero": expected,
        "stress_return_minus_zero": stress,
        "severe_return_minus_zero": severe,
        "sharpe_margin": metrics.annualized_weekly_sharpe
        - _d(gate["minimum_annualized_weekly_sharpe"], "Sharpe gate"),
        "psr_margin": metrics.weekly_psr - _d(gate["minimum_weekly_psr"], "PSR gate"),
        "drawdown_headroom": _d(gate["maximum_drawdown"], "drawdown gate")
        - metrics.maximum_drawdown,
        "turnover_headroom": _d(
            gate["maximum_annualized_one_way_turnover"], "turnover gate"
        )
        - metrics.annualized_turnover,
        "return_delta_vs_always_on": return_delta,
        "sharpe_delta_vs_always_on": sharpe_delta,
    }
    rejection_reasons = tuple(key for key, value in checks.items() if not value)
    selected = not rejection_reasons
    return GateDecision(
        status="SELECTED" if selected else "REJECTED",
        selected_policy=config.get("candidate_id") if selected else None,
        checks=checks,
        margins=margins,
        rejection_reasons=rejection_reasons,
    )
