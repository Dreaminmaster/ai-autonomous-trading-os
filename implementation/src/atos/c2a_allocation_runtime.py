"""Bound C2A runtime with fail-closed no-trade target normalization.

The original C2A engine remains the single implementation of policies, ledgers,
aggregation, comparators, gates, and ranking.  This module replaces only its
trade-target executor before exporting the runtime API.  The replacement is
source-bound and tested because retaining an in-band current weight can make the
naive mixed target vector sum above one even when the requested target is valid.
"""
from __future__ import annotations

from typing import Any, Mapping

from . import c2a_allocation as _base

C2AAllocationError = _base.C2AAllocationError
PortfolioState = _base.PortfolioState
POLICIES = _base.POLICIES
PAIR_ORDER = _base.PAIR_ORDER
COST_LABELS = _base.COST_LABELS
EPSILON = _base.EPSILON


def _normalized_targets(
    current: Mapping[str, float],
    targets: Mapping[str, float],
    no_trade_band: float,
) -> dict[str, float]:
    requested = {
        pair: _base._finite(targets.get(pair, 0.0), f"target {pair}")
        for pair in PAIR_ORDER
    }
    if any(value < -EPSILON or value > 1.0 + EPSILON for value in requested.values()):
        raise C2AAllocationError("target weight outside [0,1]")
    if sum(requested.values()) > 1.0 + EPSILON:
        raise C2AAllocationError("requested targets exceed one")

    frozen = {
        pair
        for pair in PAIR_ORDER
        if abs(requested[pair] - current[pair]) < no_trade_band
    }
    result = {
        pair: current[pair] if pair in frozen else requested[pair]
        for pair in PAIR_ORDER
    }
    frozen_total = sum(result[pair] for pair in frozen)
    changed = [pair for pair in PAIR_ORDER if pair not in frozen]
    changed_total = sum(result[pair] for pair in changed)
    available = max(0.0, 1.0 - frozen_total)
    if changed_total > available + EPSILON and changed_total > 0:
        scale = available / changed_total
        for pair in changed:
            result[pair] *= scale
    if sum(result.values()) > 1.0 + 1e-8:
        raise C2AAllocationError("normalized targets exceed one")
    return result


def _execute_target(
    state: PortfolioState,
    prices: Mapping[str, float],
    targets: Mapping[str, float],
    *,
    fee_rate: float,
    no_trade_band: float,
    turnover_cap: float | None,
) -> dict[str, Any]:
    price = {
        pair: _base._finite(prices[pair], f"price {pair}")
        for pair in PAIR_ORDER
    }
    if any(value <= 0 for value in price.values()):
        raise C2AAllocationError("prices must be positive")
    pre_equity = state.cash + sum(
        state.units[pair] * price[pair] for pair in PAIR_ORDER
    )
    if pre_equity <= 0:
        raise C2AAllocationError("non-positive pre-trade equity")

    current_values = {
        pair: state.units[pair] * price[pair] for pair in PAIR_ORDER
    }
    current_weights = {
        pair: current_values[pair] / pre_equity for pair in PAIR_ORDER
    }
    desired = _normalized_targets(current_weights, targets, no_trade_band)
    deltas = {
        pair: desired[pair] * pre_equity - current_values[pair]
        for pair in PAIR_ORDER
    }
    requested_turnover = sum(abs(value) for value in deltas.values()) / pre_equity
    cap_scaled = False
    if turnover_cap is not None:
        cap = _base._finite(turnover_cap, "turnover cap")
        if cap < 0:
            raise C2AAllocationError("turnover cap must be nonnegative")
        if requested_turnover > cap + EPSILON:
            scale = cap / requested_turnover
            deltas = {pair: value * scale for pair, value in deltas.items()}
            cap_scaled = True

    fee = _base._finite(fee_rate, "fee rate")
    if fee < 0:
        raise C2AAllocationError("fee rate must be nonnegative")
    executed = {pair: 0.0 for pair in PAIR_ORDER}
    fees = {pair: 0.0 for pair in PAIR_ORDER}

    for pair in PAIR_ORDER:
        delta = deltas[pair]
        if delta >= -EPSILON:
            continue
        notional = min(-delta, state.units[pair] * price[pair])
        state.units[pair] -= notional / price[pair]
        charge = notional * fee
        state.cash += notional - charge
        executed[pair] -= notional
        fees[pair] += charge

    requested_buys = {
        pair: max(0.0, deltas[pair]) for pair in PAIR_ORDER
    }
    buy_total = sum(requested_buys.values())
    buy_scale = (
        1.0
        if buy_total <= EPSILON
        else min(1.0, state.cash / (buy_total * (1.0 + fee)))
    )
    for pair in PAIR_ORDER:
        notional = requested_buys[pair] * buy_scale
        if notional <= EPSILON:
            continue
        charge = notional * fee
        state.cash -= notional + charge
        state.units[pair] += notional / price[pair]
        executed[pair] += notional
        fees[pair] += charge

    if state.cash < -1e-7 or any(
        state.units[pair] < -1e-12 for pair in PAIR_ORDER
    ):
        raise C2AAllocationError("negative post-trade state")
    state.cash = max(0.0, state.cash)
    turnover = sum(abs(value) for value in executed.values()) / pre_equity
    if turnover_cap is not None and turnover > float(turnover_cap) + 1e-7:
        raise C2AAllocationError("executed turnover exceeds cap")
    return {
        "pre_trade_equity": pre_equity,
        "requested_targets": {
            pair: float(targets.get(pair, 0.0)) for pair in PAIR_ORDER
        },
        "adjusted_targets": desired,
        "current_weights": current_weights,
        "requested_turnover": requested_turnover,
        "turnover_ratio": turnover,
        "cap_scaled": cap_scaled,
        "buy_scale": buy_scale,
        "executed_notional": executed,
        "fees": fees,
        "fee_total": sum(fees.values()),
        "nonzero": sum(abs(value) for value in executed.values()) > EPSILON,
    }


_base._execute_target = _execute_target

validate_config = _base.validate_config
prepare_market = _base.prepare_market
simulate_window = _base.simulate_window
simulate_buy_hold = _base.simulate_buy_hold
aggregate_policy = _base.aggregate_policy
aggregate_comparator = _base.aggregate_comparator
decide = _base.decide
