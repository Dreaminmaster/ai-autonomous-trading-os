from __future__ import annotations

from math import isfinite
from typing import Any

import pandas as pd

from .c3a_residual_common import (
    ANNUAL_BARS, POLICY_IDS, STARTING_EQUITY, C3AError, CellResult, Trade,
    _ensure_finite, _equity_returns, _max_drawdown, _profit_factor, _sharpe, _timestamp,
)


def _eligible_assets(policy_id: str) -> tuple[str, ...]:
    if policy_id == "C3AEthResidualReversion":
        return ("ETH",)
    if policy_id == "C3ASolResidualReversion":
        return ("SOL",)
    if policy_id == "C3AStrongestLaggardResidualReversion":
        return ("ETH", "SOL")
    raise C3AError(f"unknown policy: {policy_id}")


def _entry_asset(row: pd.Series, policy_id: str) -> str | None:
    if not bool(row.get("btc_regime_on", False)):
        return None
    candidates: list[tuple[float, str]] = []
    for asset in _eligible_assets(policy_id):
        value = row.get(f"{asset}_z")
        if value is None or pd.isna(value):
            continue
        z = float(value)
        if z <= -2.0:
            candidates.append((z, asset))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    return candidates[0][1]


def simulate_window(
    indicators: pd.DataFrame,
    policy_id: str,
    window_id: str,
    start: str,
    end: str,
    cost_label: str,
    cost_rate: float,
) -> CellResult:
    if policy_id not in POLICY_IDS:
        raise C3AError(f"unknown policy {policy_id}")
    start_timestamp = _timestamp(start)
    end_timestamp = _timestamp(end)
    window = indicators.loc[
        (indicators.index >= start_timestamp) & (indicators.index < end_timestamp)
    ].copy()
    if window.empty:
        raise C3AError(f"empty window {window_id}")
    if window.index[-1] >= end_timestamp:
        raise C3AError("window includes exclusive boundary")
    cash = STARTING_EQUITY
    quantity = 0.0
    asset: str | None = None
    entry_time: pd.Timestamp | None = None
    entry_price = 0.0
    entry_notional = 0.0
    entry_cost = 0.0
    held_bars = 0
    earliest_entry_open_index = 0
    pending_entry: str | None = None
    pending_exit_reason: str | None = None
    trades: list[Trade] = []
    equity: list[float] = [STARTING_EQUITY]
    turnover_contributions: list[float] = []
    exposed_bars = 0
    index_values = list(window.index)

    for position, timestamp in enumerate(index_values):
        row = window.loc[timestamp]
        if pending_exit_reason is not None and asset is not None:
            open_price = _ensure_finite("exit open", row[f"{asset}_open"])
            pre_trade_equity = cash + quantity * open_price
            exit_notional = quantity * open_price
            exit_cost = cost_rate * exit_notional
            cash += exit_notional - exit_cost
            turnover_contributions.append(exit_notional / pre_trade_equity)
            net_pnl = exit_notional - exit_cost - entry_notional - entry_cost
            trades.append(
                Trade(
                    asset=asset,
                    entry_time=entry_time.isoformat() if entry_time is not None else "",
                    exit_time=timestamp.isoformat(),
                    entry_price=entry_price,
                    exit_price=open_price,
                    quantity=quantity,
                    entry_notional=entry_notional,
                    entry_cost=entry_cost,
                    exit_notional=exit_notional,
                    exit_cost=exit_cost,
                    net_pnl=net_pnl,
                    reason=pending_exit_reason,
                    held_bars=held_bars,
                )
            )
            quantity = 0.0
            asset = None
            entry_time = None
            entry_price = 0.0
            entry_notional = 0.0
            entry_cost = 0.0
            held_bars = 0
            earliest_entry_open_index = position + 6
            pending_exit_reason = None
        elif pending_entry is not None and asset is None:
            if position < earliest_entry_open_index:
                raise C3AError("entry executed before cooldown completed")
            open_price = _ensure_finite("entry open", row[f"{pending_entry}_open"])
            pre_trade_equity = cash
            notional = 0.5 * pre_trade_equity / (1.0 + 0.5 * cost_rate)
            cost = cost_rate * notional
            new_quantity = notional / open_price
            new_cash = cash - notional - cost
            post_equity = new_cash + new_quantity * open_price
            if new_cash < -1e-9 or new_quantity < 0 or not isfinite(post_equity):
                raise C3AError("invalid entry accounting")
            if new_quantity * open_price > 0.5 * post_equity + 1e-8:
                raise C3AError("post-cost asset share exceeds 50%")
            cash = max(new_cash, 0.0)
            quantity = new_quantity
            asset = pending_entry
            entry_time = timestamp
            entry_price = open_price
            entry_notional = notional
            entry_cost = cost
            held_bars = 0
            turnover_contributions.append(notional / pre_trade_equity)
            pending_entry = None

        if asset is not None:
            close_price = _ensure_finite("held close", row[f"{asset}_close"])
            close_equity = cash + quantity * close_price
            exposed_bars += 1
            held_bars += 1
        else:
            close_equity = cash
        close_equity = _ensure_finite("close equity", close_equity)
        if cash < -1e-9 or quantity < -1e-12:
            raise C3AError("negative portfolio state")
        equity.append(close_equity)

        has_next_open = position + 1 < len(index_values)
        if not has_next_open:
            continue

        if asset is not None:
            z_value = row.get(f"{asset}_z")
            normalization = z_value is not None and not pd.isna(z_value) and float(z_value) >= -0.25
            regime_exit = not bool(row.get("btc_regime_on", False))
            time_exit = held_bars >= 18
            price_stop = float(row[f"{asset}_close"]) / entry_price - 1.0 <= -0.06
            if normalization:
                pending_exit_reason = "residual_normalization"
            elif regime_exit:
                pending_exit_reason = "regime_exit"
            elif time_exit:
                pending_exit_reason = "time_exit"
            elif price_stop:
                pending_exit_reason = "price_stop"
        elif position + 1 >= earliest_entry_open_index:
            pending_entry = _entry_asset(row, policy_id)

    if asset is not None:
        timestamp = index_values[-1]
        close_price = _ensure_finite("terminal close", window.loc[timestamp, f"{asset}_close"])
        pre_trade_equity = cash + quantity * close_price
        exit_notional = quantity * close_price
        exit_cost = cost_rate * exit_notional
        cash += exit_notional - exit_cost
        turnover_contributions.append(exit_notional / pre_trade_equity)
        net_pnl = exit_notional - exit_cost - entry_notional - entry_cost
        trades.append(
            Trade(
                asset=asset,
                entry_time=entry_time.isoformat() if entry_time is not None else "",
                exit_time=timestamp.isoformat(),
                entry_price=entry_price,
                exit_price=close_price,
                quantity=quantity,
                entry_notional=entry_notional,
                entry_cost=entry_cost,
                exit_notional=exit_notional,
                exit_cost=exit_cost,
                net_pnl=net_pnl,
                reason="terminal_liquidation",
                held_bars=held_bars,
            )
        )
        equity.append(_ensure_finite("terminal equity", cash))

    final_equity = _ensure_finite("final equity", cash)
    if final_equity <= 0:
        raise C3AError("final equity must be positive")
    returns = _equity_returns(equity)
    bars = len(window)
    annualized_turnover = sum(turnover_contributions) * ANNUAL_BARS / bars
    return CellResult(
        policy_id=policy_id,
        window_id=window_id,
        cost_label=cost_label,
        cost_rate=cost_rate,
        start=start_timestamp.isoformat(),
        end=end_timestamp.isoformat(),
        starting_equity=STARTING_EQUITY,
        final_equity=final_equity,
        net_return=final_equity / STARTING_EQUITY - 1.0,
        max_drawdown=_max_drawdown(equity),
        sharpe=_sharpe(returns),
        profit_factor=_profit_factor(trades),
        closed_trades=len(trades),
        annualized_one_way_turnover=annualized_turnover,
        exposure=exposed_bars / bars,
        bars=bars,
        turnover_contributions=tuple(turnover_contributions),
        trades=tuple(trades),
        equity=tuple(equity),
        returns=returns,
    )


def comparator_cell(
    frame: pd.DataFrame,
    comparator_id: str,
    window_id: str,
    start: str,
    end: str,
    cost_label: str,
    cost_rate: float,
) -> dict[str, Any]:
    start_timestamp = _timestamp(start)
    end_timestamp = _timestamp(end)
    window = frame.loc[(frame.index >= start_timestamp) & (frame.index < end_timestamp)]
    if window.empty:
        raise C3AError(f"empty comparator window {window_id}")
    if comparator_id == "Cash":
        final_equity = STARTING_EQUITY
        trades = 0
        max_drawdown = 0.0
    else:
        asset = comparator_id.removesuffix("BuyAndHold")
        entry_price = _ensure_finite("comparator entry", window.iloc[0][f"{asset}_open"])
        exit_price = _ensure_finite("comparator exit", window.iloc[-1][f"{asset}_close"])
        entry_notional = STARTING_EQUITY / (1.0 + cost_rate)
        quantity = entry_notional / entry_price
        final_equity = quantity * exit_price * (1.0 - cost_rate)
        trades = 1
        max_drawdown = _max_drawdown(
            [STARTING_EQUITY]
            + [quantity * float(value) for value in window[f"{asset}_close"]]
            + [final_equity]
        )
    return {
        "comparator_id": comparator_id,
        "window_id": window_id,
        "cost_label": cost_label,
        "cost_rate": cost_rate,
        "start": start_timestamp.isoformat(),
        "end": end_timestamp.isoformat(),
        "starting_equity": STARTING_EQUITY,
        "final_equity": final_equity,
        "net_return": final_equity / STARTING_EQUITY - 1.0,
        "max_drawdown": max_drawdown,
        "closed_trades": trades,
        "bars": len(window),
    }
