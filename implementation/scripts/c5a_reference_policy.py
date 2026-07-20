"""Independent C5A signal, sizing, and solver recomputation."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

from .c5a_reference_contract import (
    ABLATION_ID,
    CANDIDATE_ID,
    C5AReferenceError,
    C5AMarket,
    SPOT_INSTRUMENTS,
    _ecdf_percentile,
    _finite,
    _raw_features,
)


def _waterfill_weights(
    eligible: Sequence[str],
    volatility: Mapping[str, float],
    config: Mapping[str, Any],
) -> dict[str, float]:
    active = sorted(str(item) for item in eligible)
    if len(active) < 2:
        raise C5AReferenceError("water-filling requires at least two eligible assets")
    remaining = float(config["total_invested_weight"])
    cap = float(config["per_asset_weight_cap"])
    weights = {spot: 0.0 for spot in SPOT_INSTRUMENTS}
    while active:
        denominator = sum(1.0 / float(volatility[spot]) for spot in active)
        if denominator <= 0 or not math.isfinite(denominator):
            raise C5AReferenceError("invalid inverse-volatility denominator")
        provisional = {
            spot: remaining * (1.0 / float(volatility[spot])) / denominator
            for spot in active
        }
        over = [spot for spot in active if provisional[spot] > cap]
        if not over:
            for spot in active:
                weights[spot] = provisional[spot]
            break
        for spot in sorted(over):
            weights[spot] = cap
            remaining -= cap
            active.remove(spot)
            if remaining < -1e-12:
                raise C5AReferenceError("capped allocation over-assigned")
    if abs(sum(weights.values()) - float(config["total_invested_weight"])) > 1e-12:
        raise C5AReferenceError("capped allocation does not sum to invested target")
    if any(value < -1e-12 or value > cap + 1e-12 for value in weights.values()):
        raise C5AReferenceError("capped allocation violates asset bounds")
    return {spot: max(0.0, float(value)) for spot, value in weights.items() if value > 0}


def signal_snapshot(
    market: C5AMarket,
    calibration: Mapping[str, Any],
    *,
    execution_index: int,
    policy_id: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if policy_id not in {CANDIDATE_ID, ABLATION_ID}:
        raise C5AReferenceError(f"unknown C5A policy: {policy_id}")
    execution_time = market.timestamps[execution_index]
    if execution_time.weekday() != 0 or execution_time.hour != 0:
        raise C5AReferenceError("C5A execution must be Monday 00 UTC")
    features = _raw_features(market, execution_index=execution_index, config=config)
    observations = calibration.get("observations")
    if not isinstance(observations, Mapping):
        raise C5AReferenceError("invalid C5A calibration object")
    rows: list[dict[str, Any]] = []
    eligible: list[str] = []
    for spot in SPOT_INSTRUMENTS:
        basis_percentile = _ecdf_percentile(
            observations[spot]["basis_7d"], features[spot]["basis_7d"]
        )
        participation_percentile = _ecdf_percentile(
            observations[spot]["participation_7d"],
            features[spot]["participation_7d"],
        )
        crowding_score = max(basis_percentile, participation_percentile)
        positive_trend = features[spot]["trend_28d"] > 0
        not_crowded = crowding_score < float(config["crowding_percentile_threshold"])
        selected_eligible = positive_trend and (
            not_crowded if policy_id == CANDIDATE_ID else True
        )
        if selected_eligible:
            eligible.append(spot)
        rows.append(
            {
                "instrument": spot,
                **features[spot],
                "basis_percentile": basis_percentile,
                "participation_percentile": participation_percentile,
                "crowding_score": crowding_score,
                "positive_trend": positive_trend,
                "not_crowded": not_crowded,
                "eligible": selected_eligible,
            }
        )
    btc_positive = features["BTC-USDT"]["trend_28d"] > 0
    risk_on = btc_positive and len(eligible) >= 2
    target_weights = (
        _waterfill_weights(
            eligible,
            {spot: features[spot]["rv_28d"] for spot in SPOT_INSTRUMENTS},
            config,
        )
        if risk_on
        else {}
    )
    if risk_on and abs(sum(target_weights.values()) - 0.80) > 1e-12:
        raise C5AReferenceError("risk-on target does not invest exactly 80%")
    return {
        "execution_time": execution_time.isoformat(),
        "signal_time": market.timestamps[execution_index - 1].isoformat(),
        "policy_id": policy_id,
        "btc_positive_trend": btc_positive,
        "eligible_instruments": eligible,
        "eligible_count": len(eligible),
        "risk_on": risk_on,
        "target_weights": target_weights,
        "target_cash_weight": 0.20 if risk_on else 1.0,
        "rows": rows,
    }


def solve_post_cost(
    equity_before: float,
    current_values: Mapping[str, float],
    target_weights: Mapping[str, float],
    fee_rate: float,
) -> dict[str, Any]:
    equity_before = _finite(equity_before, "equity before")
    fee_rate = _finite(fee_rate, "fee rate")
    if equity_before <= 0 or fee_rate < 0:
        raise C5AReferenceError("invalid post-cost solver inputs")
    current = {
        spot: _finite(current_values.get(spot, 0.0), f"current value {spot}")
        for spot in SPOT_INSTRUMENTS
    }
    weights = {
        spot: _finite(target_weights.get(spot, 0.0), f"target weight {spot}")
        for spot in SPOT_INSTRUMENTS
    }
    if any(value < 0 for value in current.values()) or any(value < 0 for value in weights.values()):
        raise C5AReferenceError("negative current value or target weight")
    if sum(weights.values()) > 1.0 + 1e-12:
        raise C5AReferenceError("target weights exceed one")

    def equation(value: float) -> float:
        return (
            value
            + fee_rate
            * sum(abs(weights[spot] * value - current[spot]) for spot in SPOT_INSTRUMENTS)
            - equity_before
        )

    lower, upper = 0.0, equity_before
    if equation(lower) > 1e-12 or equation(upper) < -1e-12:
        raise C5AReferenceError("post-cost root is not bracketed")
    midpoint = upper
    iterations = 0
    for iterations in range(1, 201):
        midpoint = (lower + upper) / 2.0
        residual = equation(midpoint)
        if abs(residual) <= 1e-12 or upper - lower <= 1e-12:
            break
        if residual > 0:
            upper = midpoint
        else:
            lower = midpoint
    else:
        raise C5AReferenceError("post-cost root did not converge")
    target_values = {spot: weights[spot] * midpoint for spot in SPOT_INSTRUMENTS}
    trade_deltas = {
        spot: target_values[spot] - current[spot] for spot in SPOT_INSTRUMENTS
    }
    fees = {spot: fee_rate * abs(trade_deltas[spot]) for spot in SPOT_INSTRUMENTS}
    total_fee = sum(fees.values())
    cash = midpoint - sum(target_values.values())
    residual = equity_before - total_fee - midpoint
    if cash < -1e-12 or abs(residual) > 1e-9:
        raise C5AReferenceError("post-cost accounting identity failure")
    return {
        "equity_before": equity_before,
        "equity_after": midpoint,
        "target_values": target_values,
        "trade_deltas": trade_deltas,
        "fees": fees,
        "total_fee": total_fee,
        "cash": max(0.0, cash),
        "residual": residual,
        "iterations": iterations,
    }


def _weights(
    cash: float,
    quantities: Mapping[str, float],
    prices: Mapping[str, float],
) -> tuple[float, dict[str, float], float]:
    values = {spot: float(quantities[spot]) * float(prices[spot]) for spot in SPOT_INSTRUMENTS}
    equity = float(cash) + sum(values.values())
    if not math.isfinite(equity) or equity <= 0:
        raise C5AReferenceError("invalid marked equity")
    asset_weights = {spot: values[spot] / equity for spot in SPOT_INSTRUMENTS}
    cash_weight = float(cash) / equity
    if abs(sum(asset_weights.values()) + cash_weight - 1.0) > 1e-12:
        raise C5AReferenceError("current weights do not reconcile")
    return equity, asset_weights, cash_weight


def one_way_distance(
    current_asset_weights: Mapping[str, float],
    current_cash_weight: float,
    target_asset_weights: Mapping[str, float],
    target_cash_weight: float,
) -> float:
    result = 0.5 * (
        sum(
            abs(float(target_asset_weights.get(spot, 0.0)) - float(current_asset_weights.get(spot, 0.0)))
            for spot in SPOT_INSTRUMENTS
        )
        + abs(float(target_cash_weight) - float(current_cash_weight))
    )
    if not math.isfinite(result) or result < -1e-12:
        raise C5AReferenceError("invalid one-way distance")
    return max(0.0, result)
