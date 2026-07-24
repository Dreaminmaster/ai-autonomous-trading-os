"""Physically separate retained-evidence reviewer for synthetic C7A decisions.

This module intentionally imports neither the C7A producer nor its contract module.
It recomputes a decision from retained primitive arrays and compares the result.
"""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
MINIMUM_BETA = 0.50
MAXIMUM_BETA = 2.00
MINIMUM_R_SQUARED = 0.50
MAXIMUM_GROSS_NOTIONAL = 0.50
MINIMUM_PROJECTED_CARRY_28D = 0.00225
MINIMUM_POSITIVE_DAYS = 19


def _finite_sequence(
    value: Any, *, length: int, label: str, errors: list[str]
) -> tuple[float, ...]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != length
    ):
        errors.append(f"{label} must contain exactly {length} values")
        return ()
    output: list[float] = []
    for item in value:
        try:
            number = float(item)
        except (TypeError, ValueError):
            errors.append(f"{label} contains non-numeric value")
            return ()
        if not math.isfinite(number):
            errors.append(f"{label} contains non-finite value")
            return ()
        output.append(number)
    return tuple(output)


def _regression(
    y: Sequence[float], x: Sequence[float]
) -> tuple[float, float, float] | None:
    mean_x = sum(x) / len(x)
    mean_y = sum(y) / len(y)
    sxx = sum((value - mean_x) ** 2 for value in x)
    syy = sum((value - mean_y) ** 2 for value in y)
    if sxx <= 0 or syy <= 0:
        return None
    sxy = sum(
        (xv - mean_x) * (yv - mean_y)
        for xv, yv in zip(x, y, strict=True)
    )
    beta = sxy / sxx
    alpha = mean_y - beta * mean_x
    residual = sum(
        (yv - alpha - beta * xv) ** 2
        for xv, yv in zip(x, y, strict=True)
    )
    r_squared = min(1.0, max(0.0, 1.0 - residual / syy))
    return alpha, beta, r_squared


def review_decision_evidence(evidence: Mapping[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    if set(evidence) != {"decision", "mark_returns", "funding_daily_sums"}:
        errors.append("evidence section set mismatch")
    decision = evidence.get("decision")
    mark_returns = evidence.get("mark_returns")
    daily = evidence.get("funding_daily_sums")
    if not isinstance(decision, Mapping):
        errors.append("decision must be an object")
        decision = {}
    if not isinstance(mark_returns, Mapping) or set(mark_returns) != set(
        INSTRUMENTS
    ):
        errors.append("mark-return instrument set mismatch")
        mark_returns = {}
    if not isinstance(daily, Mapping) or set(daily) != set(INSTRUMENTS):
        errors.append("funding-daily instrument set mismatch")
        daily = {}

    returns = {
        instrument: _finite_sequence(
            mark_returns.get(instrument),
            length=672,
            label=f"returns:{instrument}",
            errors=errors,
        )
        for instrument in INSTRUMENTS
    }
    funding_daily = {
        instrument: _finite_sequence(
            daily.get(instrument),
            length=28,
            label=f"funding:{instrument}",
            errors=errors,
        )
        for instrument in INSTRUMENTS
    }
    if errors:
        return {
            "status": "FAIL",
            "errors": errors,
            "decision_recomputed": None,
        }

    sums = {
        instrument: sum(funding_daily[instrument])
        for instrument in INSTRUMENTS
    }
    if sums[INSTRUMENTS[0]] == sums[INSTRUMENTS[1]]:
        recomputed = {
            "eligible": False,
            "reason": "FUNDING_TIE",
            "high_funding_instrument": None,
            "low_funding_instrument": None,
            "funding_sums_28d": sums,
            "beta": None,
            "r_squared": None,
            "long_weight": 0.0,
            "short_weight": 0.0,
            "projected_carry_28d": 0.0,
            "positive_daily_spreads": 0,
            "target_weights": {instrument: 0.0 for instrument in INSTRUMENTS},
        }
    else:
        high = max(INSTRUMENTS, key=lambda instrument: sums[instrument])
        low = INSTRUMENTS[0] if high == INSTRUMENTS[1] else INSTRUMENTS[1]
        regression = _regression(returns[low], returns[high])
        if regression is None:
            errors.append("independent OLS variance invalid")
            return {
                "status": "FAIL",
                "errors": errors,
                "decision_recomputed": None,
            }
        _alpha, beta, r_squared = regression
        beta_valid = MINIMUM_BETA <= beta <= MAXIMUM_BETA
        r2_valid = r_squared >= MINIMUM_R_SQUARED
        if not beta_valid:
            long_weight = 0.0
            short_weight = 0.0
            projected = 0.0
            positive_days = 0
            eligible = False
            reason = "BETA_OUT_OF_RANGE"
        elif not r2_valid:
            long_weight = 0.0
            short_weight = 0.0
            projected = 0.0
            positive_days = 0
            eligible = False
            reason = "R_SQUARED_BELOW_MINIMUM"
        else:
            long_target = MAXIMUM_GROSS_NOTIONAL / (1.0 + beta)
            short_target = MAXIMUM_GROSS_NOTIONAL * beta / (1.0 + beta)
            projected = short_target * sums[high] - long_target * sums[low]
            positive_days = sum(
                short_target * high_rate - long_target * low_rate > 0
                for high_rate, low_rate in zip(
                    funding_daily[high], funding_daily[low], strict=True
                )
            )
            eligible = bool(
                sums[high] > 0
                and projected > MINIMUM_PROJECTED_CARRY_28D
                and positive_days >= MINIMUM_POSITIVE_DAYS
            )
            if sums[high] <= 0:
                reason = "HIGH_FUNDING_NOT_POSITIVE"
            elif projected <= MINIMUM_PROJECTED_CARRY_28D:
                reason = "PROJECTED_CARRY_BELOW_MINIMUM"
            elif positive_days < MINIMUM_POSITIVE_DAYS:
                reason = "POSITIVE_DAILY_SPREAD_COUNT_BELOW_MINIMUM"
            else:
                reason = "ELIGIBLE"
            long_weight = long_target if eligible else 0.0
            short_weight = short_target if eligible else 0.0
        recomputed = {
            "eligible": eligible,
            "reason": reason,
            "high_funding_instrument": high,
            "low_funding_instrument": low,
            "funding_sums_28d": sums,
            "beta": beta,
            "r_squared": r_squared,
            "long_weight": long_weight,
            "short_weight": short_weight,
            "projected_carry_28d": projected,
            "positive_daily_spreads": positive_days,
            "target_weights": (
                {low: long_weight, high: -short_weight}
                if eligible
                else {instrument: 0.0 for instrument in INSTRUMENTS}
            ),
        }

    observed_sums = decision.get("funding_sums_28d")
    if not isinstance(observed_sums, Mapping) or set(observed_sums) != set(
        INSTRUMENTS
    ):
        errors.append("decision funding-sum set mismatch")
    else:
        for instrument in INSTRUMENTS:
            try:
                if not math.isclose(
                    float(observed_sums[instrument]),
                    float(recomputed["funding_sums_28d"][instrument]),
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    errors.append(
                        f"decision funding-sum mismatch: {instrument}"
                    )
            except (TypeError, ValueError):
                errors.append(f"decision funding-sum mismatch: {instrument}")

    for key in (
        "eligible",
        "reason",
        "high_funding_instrument",
        "low_funding_instrument",
        "positive_daily_spreads",
    ):
        if decision.get(key) != recomputed[key]:
            errors.append(f"decision mismatch: {key}")
    for key in (
        "beta",
        "r_squared",
        "long_weight",
        "short_weight",
        "projected_carry_28d",
    ):
        observed = decision.get(key)
        expected = recomputed[key]
        if observed is None or expected is None:
            if observed != expected:
                errors.append(f"decision mismatch: {key}")
        else:
            try:
                if not math.isclose(
                    float(observed),
                    float(expected),
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    errors.append(f"decision mismatch: {key}")
            except (TypeError, ValueError):
                errors.append(f"decision mismatch: {key}")
    observed_weights = decision.get("target_weights")
    if not isinstance(observed_weights, Mapping) or set(observed_weights) != set(
        INSTRUMENTS
    ):
        errors.append("decision target-weight set mismatch")
    else:
        for instrument in INSTRUMENTS:
            try:
                if not math.isclose(
                    float(observed_weights[instrument]),
                    float(recomputed["target_weights"][instrument]),
                    rel_tol=1e-12,
                    abs_tol=1e-12,
                ):
                    errors.append(
                        f"decision target-weight mismatch: {instrument}"
                    )
            except (TypeError, ValueError):
                errors.append(f"decision target-weight mismatch: {instrument}")

    return {
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "decision_recomputed": recomputed,
        "real_data_authorized": False,
        "network_execution_authorized": False,
        "economic_run_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
