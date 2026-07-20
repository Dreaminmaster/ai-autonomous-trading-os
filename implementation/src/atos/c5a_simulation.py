"""C5A independent-half spot simulation and accounting."""
from __future__ import annotations

import math
from datetime import timedelta
from typing import Any, Mapping, Sequence

from .c5a_contract import (
    COST_LABELS,
    SPOT_INSTRUMENTS,
    C5AError,
    C5AMarket,
    _finite,
    _index_of,
    _timestamp,
    validate_config,
    window_decision_times,
)
from .c5a_policy import (
    _weights,
    one_way_distance,
    signal_snapshot,
    solve_post_cost,
)


def _max_drawdown(equity: Sequence[float]) -> float:
    peak = -math.inf
    result = 0.0
    for raw in equity:
        value = _finite(raw, "equity")
        if value <= 0:
            raise C5AError("equity must remain positive")
        peak = max(peak, value)
        result = max(result, 1.0 - value / peak)
    return result


def simulate_policy_half(
    market: C5AMarket,
    calibration: Mapping[str, Any],
    *,
    policy_id: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    if cost_label not in COST_LABELS:
        raise C5AError("unknown C5A cost label")
    start, end = _timestamp(window["start"]), _timestamp(window["end"])
    indices = [
        index for index, stamp in enumerate(market.timestamps) if start <= stamp < end
    ]
    if len(indices) != 546:
        raise C5AError(f"C5A half-window bar count mismatch: {len(indices)}")
    decisions = {
        _index_of(market, stamp): stamp for stamp in window_decision_times(window)
    }
    fee_rate = float(config["cost_rates"][cost_label])
    cash = float(config["starting_equity"])
    quantities = {spot: 0.0 for spot in SPOT_INSTRUMENTS}
    contributions = {spot: 0.0 for spot in SPOT_INSTRUMENTS}
    equity_curve = [cash]
    equity_returns: list[float] = []
    turnover: list[float] = []
    decision_rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    weekly: list[dict[str, Any]] = []
    exposed_bars = 0
    active_rebalances = 0
    previous_close: dict[str, float] | None = None
    previous_equity = cash
    week_start_equity: float | None = None
    week_start_time: str | None = None

    for local_index, index in enumerate(indices):
        timestamp = market.timestamps[index]
        final_bar = local_index == len(indices) - 1
        open_prices = {spot: float(market.spot_open[spot][index]) for spot in SPOT_INSTRUMENTS}
        close_prices = {spot: float(market.spot_close[spot][index]) for spot in SPOT_INSTRUMENTS}

        boundary_gap_pnl = 0.0
        if previous_close is not None:
            for spot in SPOT_INSTRUMENTS:
                pnl = quantities[spot] * (open_prices[spot] - previous_close[spot])
                contributions[spot] += pnl
                boundary_gap_pnl += pnl

        equity_at_open, current_weights, current_cash_weight = _weights(
            cash, quantities, open_prices
        )
        if index in decisions:
            if week_start_equity is not None:
                raise C5AError("prior weekly bucket did not close")
            week_start_equity = previous_equity
            week_start_time = (
                timestamp.isoformat()
                if local_index == 0
                else market.timestamps[index - 1].isoformat()
            )
            snapshot = signal_snapshot(
                market,
                calibration,
                execution_index=index,
                policy_id=policy_id,
                config=config,
            )
            target_weights = dict(snapshot["target_weights"])
            target_cash = float(snapshot["target_cash_weight"])
            distance = one_way_distance(
                current_weights, current_cash_weight, target_weights, target_cash
            )
            execute = distance >= float(config["no_trade_one_way_distance"])
            decision = {
                **snapshot,
                "window_id": str(window["id"]),
                "cost_label": cost_label,
                "equity_at_open": equity_at_open,
                "current_asset_weights": current_weights,
                "current_cash_weight": current_cash_weight,
                "one_way_distance": distance,
                "executed_rebalance": execute,
                "boundary_gap_pnl": boundary_gap_pnl,
            }
            if execute:
                current_values = {
                    spot: quantities[spot] * open_prices[spot]
                    for spot in SPOT_INSTRUMENTS
                }
                solved = solve_post_cost(
                    equity_at_open, current_values, target_weights, fee_rate
                )
                quantities_before = dict(quantities)
                for spot in SPOT_INSTRUMENTS:
                    contributions[spot] -= solved["fees"][spot]
                    target_value = solved["target_values"][spot]
                    quantities[spot] = (
                        target_value / open_prices[spot] if target_value > 0 else 0.0
                    )
                cash = float(solved["cash"])
                turnover.append(distance)
                active_rebalances += 1
                event = {
                    "kind": "SCHEDULED_REBALANCE",
                    "time": timestamp.isoformat(),
                    "window_id": str(window["id"]),
                    "policy_id": policy_id,
                    "cost_label": cost_label,
                    "price_field": "open",
                    "prices": open_prices,
                    "quantities_before": quantities_before,
                    "current_values": current_values,
                    "current_asset_weights": current_weights,
                    "current_cash_weight": current_cash_weight,
                    "target_weights": target_weights,
                    "target_cash_weight": target_cash,
                    "one_way_turnover": distance,
                    "target_values": solved["target_values"],
                    "trade_deltas": solved["trade_deltas"],
                    "fees": solved["fees"],
                    "total_fee": solved["total_fee"],
                    "equity_before": solved["equity_before"],
                    "equity_after": solved["equity_after"],
                    "cash_after": solved["cash"],
                    "quantities_after": dict(quantities),
                    "solver_iterations": solved["iterations"],
                    "solver_residual": solved["residual"],
                    "boundary_gap_pnl": boundary_gap_pnl,
                }
                events.append(event)
                decision["event_sequence"] = len(events) - 1
            else:
                turnover.append(0.0)
                decision["event_sequence"] = None
            decision_rows.append(decision)

        bar_exposed = any(quantity > 0 for quantity in quantities.values())
        if bar_exposed:
            exposed_bars += 1
        for spot in SPOT_INSTRUMENTS:
            contributions[spot] += quantities[spot] * (
                close_prices[spot] - open_prices[spot]
            )
        close_equity = cash + sum(
            quantities[spot] * close_prices[spot] for spot in SPOT_INSTRUMENTS
        )

        if final_bar and any(quantity > 0 for quantity in quantities.values()):
            equity_before, asset_weights, cash_weight = _weights(
                cash, quantities, close_prices
            )
            terminal_distance = one_way_distance(
                asset_weights, cash_weight, {}, 1.0
            )
            current_values = {
                spot: quantities[spot] * close_prices[spot]
                for spot in SPOT_INSTRUMENTS
            }
            solved = solve_post_cost(equity_before, current_values, {}, fee_rate)
            quantities_before = dict(quantities)
            for spot in SPOT_INSTRUMENTS:
                contributions[spot] -= solved["fees"][spot]
                quantities[spot] = 0.0
            cash = float(solved["cash"])
            close_equity = cash
            turnover.append(terminal_distance)
            events.append(
                {
                    "kind": "TERMINAL_LIQUIDATION",
                    "time": timestamp.isoformat(),
                    "window_id": str(window["id"]),
                    "policy_id": policy_id,
                    "cost_label": cost_label,
                    "price_field": "close",
                    "prices": close_prices,
                    "quantities_before": quantities_before,
                    "current_values": current_values,
                    "current_asset_weights": asset_weights,
                    "current_cash_weight": cash_weight,
                    "target_weights": {},
                    "target_cash_weight": 1.0,
                    "one_way_turnover": terminal_distance,
                    "target_values": solved["target_values"],
                    "trade_deltas": solved["trade_deltas"],
                    "fees": solved["fees"],
                    "total_fee": solved["total_fee"],
                    "equity_before": solved["equity_before"],
                    "equity_after": solved["equity_after"],
                    "cash_after": solved["cash"],
                    "quantities_after": dict(quantities),
                    "solver_iterations": solved["iterations"],
                    "solver_residual": solved["residual"],
                }
            )

        if not math.isfinite(close_equity) or close_equity <= 0:
            raise C5AError("invalid C5A close equity")
        bar_return = close_equity / equity_curve[-1] - 1.0
        equity_returns.append(bar_return)
        equity_curve.append(close_equity)

        if timestamp.weekday() == 6 and timestamp.hour == 20:
            if week_start_equity is None or week_start_time is None:
                raise C5AError("missing weekly start reference")
            weekly.append(
                {
                    "window_id": str(window["id"]),
                    "start_reference_time": week_start_time,
                    "start_reference_equity": week_start_equity,
                    "monday_execution_time": (timestamp - timedelta(days=6, hours=20)).isoformat(),
                    "end_time": timestamp.isoformat(),
                    "ending_equity": close_equity,
                    "net_pnl": close_equity - week_start_equity,
                    "net_return": close_equity / week_start_equity - 1.0,
                }
            )
            week_start_equity = None
            week_start_time = None

        previous_close = close_prices
        previous_equity = close_equity

    if week_start_equity is not None or week_start_time is not None:
        raise C5AError("unfinished weekly bucket")
    if len(weekly) != 13 or len(decision_rows) != 13:
        raise C5AError("C5A half evidence count mismatch")
    if any(quantity != 0.0 for quantity in quantities.values()):
        raise C5AError("C5A half did not finish in cash")
    final_equity = equity_curve[-1]
    if abs(sum(contributions.values()) - (final_equity - float(config["starting_equity"]))) > 1e-9:
        raise C5AError("C5A asset contribution reconciliation failure")
    if abs(sum(item["net_pnl"] for item in weekly) - (final_equity - float(config["starting_equity"]))) > 1e-9:
        raise C5AError("C5A weekly PnL reconciliation failure")
    return {
        "schema_version": 1,
        "stage": "C5A",
        "status": "PASS",
        "policy_id": policy_id,
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "fee_rate": fee_rate,
        "starting_equity": float(config["starting_equity"]),
        "final_equity": final_equity,
        "net_return": final_equity / float(config["starting_equity"]) - 1.0,
        "maximum_drawdown": _max_drawdown(equity_curve),
        "economic_bars": len(indices),
        "exposed_bars": exposed_bars,
        "exposure_ratio": exposed_bars / len(indices),
        "scheduled_decision_count": len(decision_rows),
        "active_rebalance_count": active_rebalances,
        "turnover_contributions": turnover,
        "equity_curve": equity_curve,
        "equity_returns": equity_returns,
        "asset_contributions": contributions,
        "weekly_buckets": weekly,
        "weekly_returns": [item["net_return"] for item in weekly],
        "weekly_pnl": [item["net_pnl"] for item in weekly],
        "decisions": decision_rows,
        "events": events,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }

