"""Pure, deterministic C7A beta-neutral funding-dispersion primitives.

The implementation accepts caller-supplied rows only. It contains no downloader,
network client, exchange account, order, paper, shadow, or live execution path.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping, Sequence

from atos.c7a_contract import (
    INSTRUMENTS,
    MAXIMUM_BETA,
    MAXIMUM_GROSS_NOTIONAL,
    MINIMUM_BETA,
    MINIMUM_POSITIVE_DAYS,
    MINIMUM_PROJECTED_CARRY_28D,
    MINIMUM_R_SQUARED,
    ONE_SIDE_COSTS,
    C7AError,
    aligned_mark_returns,
    assert_synthetic_only,
    finite,
    funding_daily_sums,
    validate_scored_decision,
)


@dataclass(frozen=True)
class Regression:
    alpha: float
    beta: float
    r_squared: float


@dataclass(frozen=True)
class C7ADecision:
    decision_time: str
    eligible: bool
    reason: str
    high_funding_instrument: str | None
    low_funding_instrument: str | None
    funding_sums_28d: Mapping[str, float]
    beta: float | None
    r_squared: float | None
    long_weight: float
    short_weight: float
    projected_carry_28d: float
    positive_daily_spreads: int
    target_weights: Mapping[str, float]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def estimate_ols_beta(
    dependent: Sequence[float], independent: Sequence[float]
) -> Regression:
    if len(dependent) != len(independent) or len(dependent) < 2:
        raise C7AError(
            "aligned return lengths must match and contain at least two values"
        )
    y = tuple(finite(value, "dependent return") for value in dependent)
    x = tuple(finite(value, "independent return") for value in independent)
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    sxx = sum((value - mean_x) ** 2 for value in x)
    syy = sum((value - mean_y) ** 2 for value in y)
    if sxx <= 0 or syy <= 0:
        raise C7AError("OLS requires positive independent and dependent variance")
    sxy = sum(
        (xv - mean_x) * (yv - mean_y)
        for xv, yv in zip(x, y, strict=True)
    )
    beta = sxy / sxx
    alpha = mean_y - beta * mean_x
    residual_ss = sum(
        (yv - (alpha + beta * xv)) ** 2
        for xv, yv in zip(x, y, strict=True)
    )
    r_squared = 1.0 - residual_ss / syy
    if not all(math.isfinite(value) for value in (alpha, beta, r_squared)):
        raise C7AError("non-finite OLS result")
    r_squared = min(1.0, max(0.0, r_squared))
    return Regression(alpha=alpha, beta=beta, r_squared=r_squared)


def _cash_decision(
    *,
    decision_iso: str,
    reason: str,
    funding_sums: Mapping[str, float],
    high: str | None = None,
    low: str | None = None,
    beta: float | None = None,
    r_squared: float | None = None,
    projected_carry: float = 0.0,
    positive_days: int = 0,
) -> C7ADecision:
    return C7ADecision(
        decision_time=decision_iso,
        eligible=False,
        reason=reason,
        high_funding_instrument=high,
        low_funding_instrument=low,
        funding_sums_28d=dict(funding_sums),
        beta=beta,
        r_squared=r_squared,
        long_weight=0.0,
        short_weight=0.0,
        projected_carry_28d=projected_carry,
        positive_daily_spreads=positive_days,
        target_weights={instrument: 0.0 for instrument in INSTRUMENTS},
    )


def compute_decision(
    *,
    decision_time: Any,
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    execution_metadata: Mapping[str, Any],
) -> C7ADecision:
    assert_synthetic_only(execution_metadata)
    decision = validate_scored_decision(decision_time)
    if set(mark_rows) != set(INSTRUMENTS) or set(funding_rows) != set(
        INSTRUMENTS
    ):
        raise C7AError("C7A instrument set mismatch")

    returns = {
        instrument: aligned_mark_returns(
            mark_rows[instrument],
            decision_time=decision,
            label=f"mark:{instrument}",
        )
        for instrument in INSTRUMENTS
    }
    funding = {
        instrument: funding_daily_sums(
            funding_rows[instrument],
            decision_time=decision,
            label=f"funding:{instrument}",
        )
        for instrument in INSTRUMENTS
    }
    funding_sums = {
        instrument: value[0] for instrument, value in funding.items()
    }
    decision_iso = decision.isoformat().replace("+00:00", "Z")

    if funding_sums[INSTRUMENTS[0]] == funding_sums[INSTRUMENTS[1]]:
        return _cash_decision(
            decision_iso=decision_iso,
            reason="FUNDING_TIE",
            funding_sums=funding_sums,
        )

    high = max(INSTRUMENTS, key=lambda instrument: funding_sums[instrument])
    low = INSTRUMENTS[0] if high == INSTRUMENTS[1] else INSTRUMENTS[1]
    regression = estimate_ols_beta(returns[low], returns[high])
    if not (MINIMUM_BETA <= regression.beta <= MAXIMUM_BETA):
        return _cash_decision(
            decision_iso=decision_iso,
            reason="BETA_OUT_OF_RANGE",
            funding_sums=funding_sums,
            high=high,
            low=low,
            beta=regression.beta,
            r_squared=regression.r_squared,
        )
    if regression.r_squared < MINIMUM_R_SQUARED:
        return _cash_decision(
            decision_iso=decision_iso,
            reason="R_SQUARED_BELOW_MINIMUM",
            funding_sums=funding_sums,
            high=high,
            low=low,
            beta=regression.beta,
            r_squared=regression.r_squared,
        )

    long_weight = MAXIMUM_GROSS_NOTIONAL / (1.0 + regression.beta)
    short_weight = (
        MAXIMUM_GROSS_NOTIONAL * regression.beta / (1.0 + regression.beta)
    )
    projected_carry = (
        short_weight * funding_sums[high] - long_weight * funding_sums[low]
    )
    high_daily = funding[high][1]
    low_daily = funding[low][1]
    daily_spreads = tuple(
        short_weight * high_rate - long_weight * low_rate
        for high_rate, low_rate in zip(high_daily, low_daily, strict=True)
    )
    positive_days = sum(value > 0 for value in daily_spreads)

    conditions = (
        funding_sums[high] > 0,
        projected_carry > MINIMUM_PROJECTED_CARRY_28D,
        positive_days >= MINIMUM_POSITIVE_DAYS,
    )
    if not all(conditions):
        if funding_sums[high] <= 0:
            reason = "HIGH_FUNDING_NOT_POSITIVE"
        elif projected_carry <= MINIMUM_PROJECTED_CARRY_28D:
            reason = "PROJECTED_CARRY_BELOW_MINIMUM"
        else:
            reason = "POSITIVE_DAILY_SPREAD_COUNT_BELOW_MINIMUM"
        return _cash_decision(
            decision_iso=decision_iso,
            reason=reason,
            funding_sums=funding_sums,
            high=high,
            low=low,
            beta=regression.beta,
            r_squared=regression.r_squared,
            projected_carry=projected_carry,
            positive_days=positive_days,
        )

    return C7ADecision(
        decision_time=decision_iso,
        eligible=True,
        reason="ELIGIBLE",
        high_funding_instrument=high,
        low_funding_instrument=low,
        funding_sums_28d=funding_sums,
        beta=regression.beta,
        r_squared=regression.r_squared,
        long_weight=long_weight,
        short_weight=short_weight,
        projected_carry_28d=projected_carry,
        positive_daily_spreads=positive_days,
        target_weights={low: long_weight, high: -short_weight},
    )


def target_turnover(
    current_weights: Mapping[str, float], target_weights: Mapping[str, float]
) -> float:
    if set(current_weights) != set(INSTRUMENTS) or set(target_weights) != set(
        INSTRUMENTS
    ):
        raise C7AError("turnover instrument set mismatch")
    return sum(
        abs(
            finite(target_weights[item], f"target {item}")
            - finite(current_weights[item], f"current {item}")
        )
        for item in INSTRUMENTS
    )


def should_resize(
    current_weights: Mapping[str, float], target_weights: Mapping[str, float]
) -> bool:
    current_gross = sum(
        abs(finite(current_weights[item], f"current {item}"))
        for item in INSTRUMENTS
    )
    turnover = target_turnover(current_weights, target_weights)
    if current_gross == 0:
        return turnover > 0
    return turnover >= current_gross * 0.10


def round_trip_cost_fraction(*, cost_label: str = "1.0x") -> float:
    try:
        cost = ONE_SIDE_COSTS[cost_label]
    except KeyError as exc:
        raise C7AError(f"unsupported C7A cost label: {cost_label}") from exc
    return 2.0 * MAXIMUM_GROSS_NOTIONAL * cost


def apply_hourly_accounting(
    *,
    equity: float,
    signed_weights: Mapping[str, float],
    simple_mark_returns: Mapping[str, float],
    funding_rates: Mapping[str, float],
    traded_turnover: float = 0.0,
    cost_label: str = "1.0x",
) -> dict[str, float]:
    starting_equity = finite(equity, "equity")
    if starting_equity <= 0:
        raise C7AError("equity must be positive")
    if set(signed_weights) != set(INSTRUMENTS):
        raise C7AError("accounting weight instrument set mismatch")
    if set(simple_mark_returns) != set(INSTRUMENTS) or set(
        funding_rates
    ) != set(INSTRUMENTS):
        raise C7AError("accounting input instrument set mismatch")
    turnover = finite(traded_turnover, "traded turnover")
    if turnover < 0:
        raise C7AError("traded turnover cannot be negative")
    try:
        one_side_cost = ONE_SIDE_COSTS[cost_label]
    except KeyError as exc:
        raise C7AError(f"unsupported C7A cost label: {cost_label}") from exc

    price_fraction = 0.0
    funding_fraction = 0.0
    gross = 0.0
    for instrument in INSTRUMENTS:
        weight = finite(signed_weights[instrument], f"weight {instrument}")
        mark_return = finite(
            simple_mark_returns[instrument], f"mark return {instrument}"
        )
        funding_rate = finite(
            funding_rates[instrument], f"funding rate {instrument}"
        )
        gross += abs(weight)
        price_fraction += weight * mark_return
        funding_fraction += -weight * funding_rate
    if gross > MAXIMUM_GROSS_NOTIONAL + 1e-12:
        raise C7AError("gross notional exceeds frozen C7A cap")
    cost_fraction = turnover * one_side_cost
    ending_equity = starting_equity * (
        1.0 + price_fraction + funding_fraction - cost_fraction
    )
    if not math.isfinite(ending_equity) or ending_equity <= 0:
        raise C7AError("non-positive or non-finite ending equity")
    return {
        "starting_equity": starting_equity,
        "price_pnl": starting_equity * price_fraction,
        "funding_pnl": starting_equity * funding_fraction,
        "trading_cost": starting_equity * cost_fraction,
        "ending_equity": ending_equity,
    }
