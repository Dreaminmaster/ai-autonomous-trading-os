"""Deterministic C3A residual mean-reversion research engine.

This module implements only the frozen public-data development screen. It does not
contain exchange, account, paper, shadow, private API, or live execution paths.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


POLICIES = (
    "C3AEthResidualReversion",
    "C3ASolResidualReversion",
    "C3AStrongestLaggardResidualReversion",
)
PAIR_ORDER = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
COMPARATORS = ("cash", "btc_buy_hold", "eth_buy_hold", "sol_buy_hold")
COST_LABELS = ("1.0x", "1.5x", "2.0x")
ALIASES = {"BTC/USDT": "BTC", "ETH/USDT": "ETH", "SOL/USDT": "SOL"}
ASSET_PAIRS = {"ETH": "ETH/USDT", "SOL": "SOL/USDT"}
EPSILON = 1e-10
ANNUAL_FOUR_HOUR_BARS = 365 * 6


class C3AResidualError(RuntimeError):
    """Raised when a frozen C3A invariant or accounting rule fails."""


def _finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise C3AResidualError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C3AResidualError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise C3AResidualError(f"{label} must be finite")
    return result


def _timestamp(value: Any) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except Exception as exc:  # pragma: no cover - pandas exception type varies
        raise C3AResidualError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        return parsed.tz_localize("UTC")
    return parsed.tz_convert("UTC")


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("schema_version") != 1 or config.get("stage") != "C3A":
        raise C3AResidualError("C3A config identity drift")
    if config.get("live") != "FORBIDDEN" or config.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C3AResidualError("C3A safety state drift")
    if config.get("confirmation_opened") is not False:
        raise C3AResidualError("C3A confirmation must remain closed")
    if config.get("required_design_main_sha") != "f8bacea9785dc51783a51ba06948402dfed1a08f":
        raise C3AResidualError("C3A design-main identity drift")
    if config.get("pairs") != list(PAIR_ORDER):
        raise C3AResidualError("C3A pair universe drift")
    if config.get("policies") != list(POLICIES):
        raise C3AResidualError("C3A policy set drift")
    if config.get("comparators") != list(COMPARATORS):
        raise C3AResidualError("C3A comparator set drift")
    if config.get("timeframe") != "4h":
        raise C3AResidualError("C3A timeframe drift")
    if config.get("download_timerange") != "20230901-20241001":
        raise C3AResidualError("C3A download timerange drift")
    if config.get("economic_boundary_exclusive") != "2024-10-01T00:00:00Z":
        raise C3AResidualError("C3A boundary drift")
    if int(config.get("startup_history_candles", 0)) != 450:
        raise C3AResidualError("C3A startup coverage drift")
    if _finite(config.get("starting_equity"), "starting equity") != 1000.0:
        raise C3AResidualError("C3A starting equity drift")
    if _finite(config.get("position_target"), "position target") != 0.5:
        raise C3AResidualError("C3A position target drift")

    expected_windows = [
        {"id": "S1", "start": "2024-01-01T00:00:00Z", "end": "2024-04-01T00:00:00Z"},
        {"id": "S2", "start": "2024-04-01T00:00:00Z", "end": "2024-07-01T00:00:00Z"},
        {"id": "S3", "start": "2024-07-01T00:00:00Z", "end": "2024-10-01T00:00:00Z"},
    ]
    if config.get("screen_windows") != expected_windows:
        raise C3AResidualError("C3A screen window drift")
    rates = config.get("cost_rates")
    if not isinstance(rates, Mapping) or list(rates) != list(COST_LABELS):
        raise C3AResidualError("C3A cost labels drift")
    if [_finite(rates[label], f"cost {label}") for label in COST_LABELS] != [0.0015, 0.00225, 0.003]:
        raise C3AResidualError("C3A cost rates drift")

    signal = config.get("signal")
    if not isinstance(signal, Mapping):
        raise C3AResidualError("C3A signal config missing")
    expected_signal = {
        "beta_lookback": 180,
        "beta_min": 0.25,
        "beta_max": 2.5,
        "residual_horizon": 6,
        "zscore_lookback": 180,
        "btc_sma_bars": 300,
        "entry_zscore": -2.0,
        "exit_zscore": -0.25,
    }
    for key, expected in expected_signal.items():
        actual = signal.get(key)
        if isinstance(expected, int):
            if int(actual) != expected:
                raise C3AResidualError(f"C3A signal drift: {key}")
        elif _finite(actual, key) != expected:
            raise C3AResidualError(f"C3A signal drift: {key}")

    lifecycle = config.get("lifecycle")
    if not isinstance(lifecycle, Mapping):
        raise C3AResidualError("C3A lifecycle config missing")
    if int(lifecycle.get("time_exit_bars", 0)) != 18:
        raise C3AResidualError("C3A time-exit drift")
    if _finite(lifecycle.get("price_stop_ratio"), "price stop") != -0.06:
        raise C3AResidualError("C3A price-stop drift")
    if int(lifecycle.get("cooldown_bars", 0)) != 6:
        raise C3AResidualError("C3A cooldown drift")


def prepare_market(candles_by_pair: Mapping[str, Sequence[Mapping[str, Any]]]) -> pd.DataFrame:
    """Return an exact, strictly aligned BTC/ETH/SOL four-hour market frame."""
    if set(candles_by_pair) != set(PAIR_ORDER):
        raise C3AResidualError("market data pair set mismatch")

    frames: dict[str, pd.DataFrame] = {}
    reference_index: pd.DatetimeIndex | None = None
    for pair in PAIR_ORDER:
        rows = candles_by_pair[pair]
        if not rows:
            raise C3AResidualError(f"no candles for {pair}")
        frame = pd.DataFrame([dict(row) for row in rows])
        if not {"date", "open", "close"}.issubset(frame.columns):
            raise C3AResidualError(f"{pair} missing required candle columns")
        frame = frame.loc[:, ["date", "open", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="raise")
        if frame["date"].duplicated().any():
            raise C3AResidualError(f"duplicate candle for {pair}")
        if not frame["date"].is_monotonic_increasing:
            raise C3AResidualError(f"unordered candle sequence for {pair}")
        frame = frame.set_index("date")
        for field in ("open", "close"):
            frame[field] = pd.to_numeric(frame[field], errors="raise").astype(float)
            if not np.isfinite(frame[field]).all() or (frame[field] <= 0).any():
                raise C3AResidualError(f"invalid {field} prices for {pair}")
        if reference_index is None:
            reference_index = frame.index
        elif not frame.index.equals(reference_index):
            raise C3AResidualError(f"misaligned timestamp sequence for {pair}")
        alias = ALIASES[pair]
        frame.columns = [f"{alias}_open", f"{alias}_close"]
        frames[pair] = frame

    market = pd.concat([frames[pair] for pair in PAIR_ORDER], axis=1)
    if market.empty or market.isna().any().any():
        raise C3AResidualError("aligned market data is empty or incomplete")
    return market


def compute_indicators(market: pd.DataFrame, config: Mapping[str, Any]) -> pd.DataFrame:
    """Compute frozen residual signals with all estimation windows excluding the current value."""
    validate_config(config)
    required = {f"{alias}_{field}" for alias in ("BTC", "ETH", "SOL") for field in ("open", "close")}
    if not required.issubset(market.columns):
        raise C3AResidualError("market frame missing required columns")
    result = market.copy()
    signal = config["signal"]
    beta_lookback = int(signal["beta_lookback"])
    residual_horizon = int(signal["residual_horizon"])
    z_lookback = int(signal["zscore_lookback"])
    btc_returns = np.log(result["BTC_close"]).diff()

    for asset in ("ETH", "SOL"):
        asset_returns = np.log(result[f"{asset}_close"]).diff()
        lag_asset = asset_returns.shift(1)
        lag_btc = btc_returns.shift(1)
        mean_asset = lag_asset.rolling(beta_lookback, min_periods=beta_lookback).mean()
        mean_btc = lag_btc.rolling(beta_lookback, min_periods=beta_lookback).mean()
        covariance = (lag_asset * lag_btc).rolling(beta_lookback, min_periods=beta_lookback).mean()
        covariance = covariance - mean_asset * mean_btc
        variance = (lag_btc * lag_btc).rolling(beta_lookback, min_periods=beta_lookback).mean()
        variance = variance - mean_btc * mean_btc
        valid_variance = variance.where(np.isfinite(variance) & (variance > 0))
        beta = (covariance / valid_variance).clip(float(signal["beta_min"]), float(signal["beta_max"]))
        residual = asset_returns - beta * btc_returns
        cumulative = residual.rolling(residual_horizon, min_periods=residual_horizon).sum()
        reference = cumulative.shift(1)
        reference_mean = reference.rolling(z_lookback, min_periods=z_lookback).mean()
        reference_std = reference.rolling(z_lookback, min_periods=z_lookback).std(ddof=0)
        reference_std = reference_std.where(np.isfinite(reference_std) & (reference_std > 0))
        result[f"beta_{asset}"] = beta
        result[f"residual_{asset}"] = residual
        result[f"cumulative_residual_{asset}"] = cumulative
        result[f"z_{asset}"] = (cumulative - reference_mean) / reference_std

    sma_bars = int(signal["btc_sma_bars"])
    result["btc_sma"] = result["BTC_close"].rolling(sma_bars, min_periods=sma_bars).mean()
    result["btc_regime_on"] = result["BTC_close"] >= result["btc_sma"]
    return result


@dataclass
class Position:
    asset: str
    quantity: float
    entry_open: float
    entry_notional: float
    entry_fee: float
    entry_time: str
    held_bars: int = 0


def _max_drawdown(equity: Sequence[float]) -> float:
    if not equity:
        raise C3AResidualError("empty equity sequence")
    peak = -math.inf
    maximum = 0.0
    for raw in equity:
        value = _finite(raw, "equity")
        if value <= 0:
            raise C3AResidualError("equity must remain positive")
        peak = max(peak, value)
        maximum = max(maximum, 1.0 - value / peak)
    return maximum


def _returns(equity: Sequence[float]) -> list[float]:
    values = [_finite(value, "equity") for value in equity]
    return [values[index] / values[index - 1] - 1.0 for index in range(1, len(values))]


def _sharpe(returns: Sequence[float]) -> float | None:
    if len(returns) < 2:
        return None
    array = np.asarray(returns, dtype=float)
    if not np.isfinite(array).all():
        return None
    deviation = float(np.std(array, ddof=1))
    if deviation <= 0 or not math.isfinite(deviation):
        return None
    value = float(np.mean(array) / deviation * math.sqrt(ANNUAL_FOUR_HOUR_BARS))
    return value if math.isfinite(value) else None


def _profit_factor(trades: Sequence[Mapping[str, Any]]) -> float | str:
    pnl = [_finite(item.get("net_pnl"), "trade net pnl") for item in trades]
    gross_profit = sum(max(value, 0.0) for value in pnl)
    gross_loss = abs(sum(min(value, 0.0) for value in pnl))
    if gross_profit <= EPSILON:
        return 0.0
    if gross_loss <= EPSILON:
        return "Infinity"
    return gross_profit / gross_loss


def _positive_share(values: Sequence[float], *, top: int = 1) -> float:
    positive = sorted((max(0.0, _finite(value, "positive-share value")) for value in values), reverse=True)
    denominator = sum(positive)
    if denominator <= EPSILON:
        return 1.0
    return sum(positive[:top]) / denominator


def _entry_asset(policy: str, row: pd.Series, config: Mapping[str, Any]) -> str | None:
    if policy not in POLICIES:
        raise C3AResidualError(f"unknown C3A policy: {policy}")
    if not bool(row.get("btc_regime_on", False)):
        return None
    threshold = float(config["signal"]["entry_zscore"])
    eligible: list[tuple[float, str]] = []
    if policy in ("C3AEthResidualReversion", "C3AStrongestLaggardResidualReversion"):
        value = row.get("z_ETH")
        if value is not None and math.isfinite(float(value)) and float(value) <= threshold:
            eligible.append((float(value), "ETH"))
    if policy in ("C3ASolResidualReversion", "C3AStrongestLaggardResidualReversion"):
        value = row.get("z_SOL")
        if value is not None and math.isfinite(float(value)) and float(value) <= threshold:
            eligible.append((float(value), "SOL"))
    if not eligible:
        return None
    eligible.sort(key=lambda item: (item[0], 0 if item[1] == "ETH" else 1))
    return eligible[0][1]


def _trade_record(position: Position, *, exit_price: float, exit_fee: float, exit_time: str, reason: str) -> dict[str, Any]:
    proceeds = position.quantity * exit_price
    net_pnl = proceeds - exit_fee - position.entry_notional - position.entry_fee
    return {
        "asset": position.asset,
        "pair": ASSET_PAIRS[position.asset],
        "entry_time": position.entry_time,
        "exit_time": exit_time,
        "entry_open": position.entry_open,
        "exit_price": exit_price,
        "quantity": position.quantity,
        "entry_notional": position.entry_notional,
        "entry_fee": position.entry_fee,
        "exit_notional": proceeds,
        "exit_fee": exit_fee,
        "net_pnl": net_pnl,
        "held_bars": position.held_bars,
        "reason": reason,
    }


def simulate_window(
    market: pd.DataFrame,
    *,
    policy: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Simulate one independent policy/window/cost cell."""
    validate_config(config)
    if policy not in POLICIES or cost_label not in COST_LABELS:
        raise C3AResidualError("unknown policy or cost label")
    frame = compute_indicators(market, config)
    start = _timestamp(window["start"])
    end = _timestamp(window["end"])
    if end <= start:
        raise C3AResidualError("invalid screen window")
    economic = frame.loc[(frame.index >= start) & (frame.index < end)]
    if economic.empty:
        raise C3AResidualError("empty economic window")
    startup_rows = int((frame.index < start).sum())
    if startup_rows < int(config["startup_history_candles"]):
        raise C3AResidualError("insufficient startup coverage")
    expected_step = pd.Timedelta(hours=4)
    if any(current - previous != expected_step for previous, current in zip(economic.index, economic.index[1:])):
        raise C3AResidualError("economic window contains a four-hour gap")

    starting_equity = float(config["starting_equity"])
    fee_rate = float(config["cost_rates"][cost_label])
    cash = starting_equity
    position: Position | None = None
    pending: dict[str, Any] | None = None
    cooldown_exit_position: int | None = None
    events: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    turnover_contributions: list[float] = []
    equity_curve = [starting_equity]
    exposed_bars = 0
    global_positions = {timestamp: index for index, timestamp in enumerate(frame.index)}
    lifecycle = config["lifecycle"]

    for local_index, (timestamp, row) in enumerate(economic.iterrows()):
        global_index = global_positions[timestamp]
        is_final = local_index == len(economic) - 1

        if pending is not None:
            action = pending
            pending = None
            asset = action.get("asset")
            if action["kind"] == "EXIT":
                if position is None or asset != position.asset:
                    raise C3AResidualError("pending exit does not match the open position")
                price = _finite(row[f"{asset}_open"], "exit open")
                pre_equity = cash + position.quantity * price
                notional = position.quantity * price
                fee = fee_rate * notional
                cash += notional - fee
                turnover_contributions.append(notional / pre_equity)
                trade = _trade_record(
                    position,
                    exit_price=price,
                    exit_fee=fee,
                    exit_time=timestamp.isoformat(),
                    reason=str(action["reason"]),
                )
                trades.append(trade)
                events.append({
                    "kind": "EXIT",
                    "time": timestamp.isoformat(),
                    "asset": asset,
                    "reason": action["reason"],
                    "notional": notional,
                    "fee": fee,
                    "pre_trade_equity": pre_equity,
                })
                position = None
                cooldown_exit_position = global_index
            elif action["kind"] == "ENTRY":
                if position is not None:
                    raise C3AResidualError("entry attempted while a position is already open")
                price = _finite(row[f"{asset}_open"], "entry open")
                pre_equity = cash
                target = float(config["position_target"])
                notional = target * pre_equity / (1.0 + target * fee_rate)
                fee = fee_rate * notional
                quantity = notional / price
                cash -= notional + fee
                if cash < -1e-8 or quantity <= 0 or not math.isfinite(quantity):
                    raise C3AResidualError("invalid post-entry state")
                cash = max(0.0, cash)
                post_equity = cash + quantity * price
                asset_share = quantity * price / post_equity
                if asset_share > target + 1e-9:
                    raise C3AResidualError("post-cost position target exceeded")
                turnover_contributions.append(notional / pre_equity)
                position = Position(
                    asset=str(asset),
                    quantity=quantity,
                    entry_open=price,
                    entry_notional=notional,
                    entry_fee=fee,
                    entry_time=timestamp.isoformat(),
                )
                events.append({
                    "kind": "ENTRY",
                    "time": timestamp.isoformat(),
                    "asset": asset,
                    "notional": notional,
                    "fee": fee,
                    "pre_trade_equity": pre_equity,
                    "post_cost_asset_share": asset_share,
                })
            else:
                raise C3AResidualError("unknown pending action")

        close_equity = cash
        exposed = position is not None
        if position is not None:
            position.held_bars += 1
            close_price = _finite(row[f"{position.asset}_close"], "position close")
            close_equity += position.quantity * close_price
            exposed_bars += 1

        terminal = False
        if is_final and position is not None:
            terminal = True
            pre_equity = close_equity
            price = _finite(row[f"{position.asset}_close"], "terminal close")
            notional = position.quantity * price
            fee = fee_rate * notional
            cash += notional - fee
            turnover_contributions.append(notional / pre_equity)
            trade = _trade_record(
                position,
                exit_price=price,
                exit_fee=fee,
                exit_time=timestamp.isoformat(),
                reason="WINDOW_END",
            )
            trades.append(trade)
            events.append({
                "kind": "TERMINAL_LIQUIDATION",
                "time": timestamp.isoformat(),
                "asset": position.asset,
                "notional": notional,
                "fee": fee,
                "pre_trade_equity": pre_equity,
            })
            position = None
            close_equity = cash

        if close_equity <= 0 or not math.isfinite(close_equity) or cash < -1e-8:
            raise C3AResidualError("invalid equity state")
        equity_curve.append(close_equity)
        daily.append({
            "time": timestamp.isoformat(),
            "equity": close_equity,
            "cash": cash,
            "asset": position.asset if position else None,
            "quantity": position.quantity if position else 0.0,
            "exposed": exposed,
            "terminal": terminal,
        })

        if is_final:
            break

        if position is not None:
            z_value = row.get(f"z_{position.asset}")
            z_finite = z_value is not None and math.isfinite(float(z_value))
            gross_return = _finite(row[f"{position.asset}_close"], "position close") / position.entry_open - 1.0
            reason: str | None = None
            if z_finite and float(z_value) >= float(config["signal"]["exit_zscore"]):
                reason = "RESIDUAL_NORMALIZATION"
            elif not bool(row.get("btc_regime_on", False)):
                reason = "REGIME_EXIT"
            elif position.held_bars >= int(lifecycle["time_exit_bars"]):
                reason = "TIME_EXIT"
            elif gross_return <= float(lifecycle["price_stop_ratio"]):
                reason = "PRICE_STOP"
            if reason is not None:
                pending = {"kind": "EXIT", "asset": position.asset, "reason": reason}
        else:
            cooldown_complete = (
                cooldown_exit_position is None
                or global_index >= cooldown_exit_position + int(lifecycle["cooldown_bars"]) - 1
            )
            if cooldown_complete:
                asset = _entry_asset(policy, row, config)
                if asset is not None:
                    pending = {"kind": "ENTRY", "asset": asset, "reason": "EXTREME_NEGATIVE_RESIDUAL"}

    if position is not None or pending is not None:
        raise C3AResidualError("window did not terminate cleanly")
    final_equity = equity_curve[-1]
    return {
        "schema_version": 1,
        "stage": "C3A",
        "policy_id": policy,
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "fee_rate": fee_rate,
        "starting_equity": starting_equity,
        "final_equity": final_equity,
        "net_return": final_equity / starting_equity - 1.0,
        "maximum_drawdown": _max_drawdown(equity_curve),
        "closed_trades": len(trades),
        "profit_factor": _profit_factor(trades),
        "economic_bars": len(economic),
        "exposed_bars": exposed_bars,
        "exposure_ratio": exposed_bars / len(economic),
        "turnover_contributions": turnover_contributions,
        "annualized_one_way_turnover": sum(turnover_contributions) * ANNUAL_FOUR_HOUR_BARS / len(economic),
        "equity_returns": _returns(equity_curve),
        "equity_curve": equity_curve,
        "events": events,
        "trades": trades,
        "daily": daily,
        "status": "PASS",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def simulate_comparator(
    market: pd.DataFrame,
    *,
    comparator_id: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    if comparator_id not in COMPARATORS or cost_label not in COST_LABELS:
        raise C3AResidualError("unknown comparator or cost label")
    start = _timestamp(window["start"])
    end = _timestamp(window["end"])
    economic = market.loc[(market.index >= start) & (market.index < end)]
    if economic.empty:
        raise C3AResidualError("empty comparator window")
    starting = float(config["starting_equity"])
    fee_rate = float(config["cost_rates"][cost_label])
    equity = [starting]
    turnover: list[float] = []
    trade: dict[str, Any] | None = None

    if comparator_id == "cash":
        equity.extend([starting] * len(economic))
    else:
        asset = {"btc_buy_hold": "BTC", "eth_buy_hold": "ETH", "sol_buy_hold": "SOL"}[comparator_id]
        first_time = economic.index[0]
        first_open = _finite(economic.iloc[0][f"{asset}_open"], "comparator entry open")
        entry_notional = starting / (1.0 + fee_rate)
        entry_fee = entry_notional * fee_rate
        cash = starting - entry_notional - entry_fee
        quantity = entry_notional / first_open
        turnover.append(entry_notional / starting)
        for local_index, (timestamp, row) in enumerate(economic.iterrows()):
            close = _finite(row[f"{asset}_close"], "comparator close")
            marked = cash + quantity * close
            if local_index == len(economic) - 1:
                exit_notional = quantity * close
                exit_fee = exit_notional * fee_rate
                turnover.append(exit_notional / marked)
                cash += exit_notional - exit_fee
                marked = cash
                trade = {
                    "asset": asset,
                    "pair": ASSET_PAIRS.get(asset, "BTC/USDT"),
                    "entry_time": first_time.isoformat(),
                    "exit_time": timestamp.isoformat(),
                    "entry_notional": entry_notional,
                    "entry_fee": entry_fee,
                    "exit_notional": exit_notional,
                    "exit_fee": exit_fee,
                    "net_pnl": exit_notional - exit_fee - entry_notional - entry_fee,
                    "reason": "WINDOW_END",
                }
            equity.append(marked)

    final_equity = equity[-1]
    return {
        "schema_version": 1,
        "stage": "C3A",
        "comparator_id": comparator_id,
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "fee_rate": fee_rate,
        "starting_equity": starting,
        "final_equity": final_equity,
        "net_return": final_equity / starting - 1.0,
        "maximum_drawdown": _max_drawdown(equity),
        "closed_trades": 0 if trade is None else 1,
        "economic_bars": len(economic),
        "turnover_contributions": turnover,
        "equity_returns": _returns(equity),
        "trades": [] if trade is None else [trade],
        "status": "PASS",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def aggregate_policy(
    rows: Sequence[Mapping[str, Any]], *, policy: str, cost_label: str, config: Mapping[str, Any]
) -> dict[str, Any]:
    validate_config(config)
    selected = [row for row in rows if row.get("policy_id") == policy and row.get("cost_label") == cost_label]
    expected_ids = [window["id"] for window in config["screen_windows"]]
    if len(selected) != 3 or sorted(row.get("window_id") for row in selected) != sorted(expected_ids):
        raise C3AResidualError("aggregate policy requires exactly three independent windows")
    by_id = {str(row["window_id"]): row for row in selected}
    ordered = [by_id[identifier] for identifier in expected_ids]
    window_returns = {str(row["window_id"]): _finite(row["net_return"], "window return") for row in ordered}
    aggregate_return = math.prod(1.0 + value for value in window_returns.values()) - 1.0
    all_returns = [value for row in ordered for value in row["equity_returns"]]
    all_trades = [dict(trade) for row in ordered for trade in row["trades"]]
    all_turnover = [float(value) for row in ordered for value in row["turnover_contributions"]]
    total_bars = sum(int(row["economic_bars"]) for row in ordered)
    exposed_bars = sum(int(row["exposed_bars"]) for row in ordered)
    trade_pnl = [_finite(trade["net_pnl"], "trade pnl") for trade in all_trades]
    asset_pnl = {
        asset: sum(_finite(trade["net_pnl"], "trade pnl") for trade in all_trades if trade.get("asset") == asset)
        for asset in ("ETH", "SOL")
    }
    maximum_asset_share = _positive_share(list(asset_pnl.values()), top=1)
    return {
        "schema_version": 1,
        "stage": "C3A",
        "policy_id": policy,
        "cost_label": cost_label,
        "window_returns": window_returns,
        "minimum_window_net_return": min(window_returns.values()),
        "median_window_net_return": float(median(window_returns.values())),
        "positive_windows": sum(value > 0 for value in window_returns.values()),
        "aggregate_net_return": aggregate_return,
        "aggregate_sharpe": _sharpe(all_returns),
        "profit_factor": _profit_factor(all_trades),
        "maximum_window_drawdown": max(_finite(row["maximum_drawdown"], "window drawdown") for row in ordered),
        "closed_trades": len(all_trades),
        "minimum_window_closed_trades": min(int(row["closed_trades"]) for row in ordered),
        "economic_bars": total_bars,
        "exposed_bars": exposed_bars,
        "exposure_ratio": exposed_bars / total_bars,
        "annualized_one_way_turnover": sum(all_turnover) * ANNUAL_FOUR_HOUR_BARS / total_bars,
        "maximum_window_positive_pnl_share": _positive_share(
            [_finite(row["final_equity"], "final equity") - float(config["starting_equity"]) for row in ordered],
            top=1,
        ),
        "maximum_single_trade_positive_pnl_share": _positive_share(trade_pnl, top=1),
        "maximum_top_three_trade_positive_pnl_share": _positive_share(trade_pnl, top=3),
        "asset_pnl": asset_pnl,
        "maximum_asset_positive_pnl_share": maximum_asset_share,
        "trades": all_trades,
        "status": "PASS",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def aggregate_comparator(rows: Sequence[Mapping[str, Any]], comparator_id: str, cost_label: str) -> dict[str, Any]:
    selected = [
        row for row in rows if row.get("comparator_id") == comparator_id and row.get("cost_label") == cost_label
    ]
    if len(selected) != 3:
        raise C3AResidualError("aggregate comparator requires exactly three windows")
    selected.sort(key=lambda row: str(row["window_id"]))
    window_returns = {str(row["window_id"]): _finite(row["net_return"], "comparator return") for row in selected}
    return {
        "comparator_id": comparator_id,
        "cost_label": cost_label,
        "window_returns": window_returns,
        "aggregate_net_return": math.prod(1.0 + value for value in window_returns.values()) - 1.0,
        "maximum_window_drawdown": max(_finite(row["maximum_drawdown"], "comparator drawdown") for row in selected),
        "status": "PASS",
    }


def _profit_factor_at_least(value: Any, threshold: float) -> bool:
    if value == "Infinity":
        return True
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(numeric) and numeric >= threshold


def decide(aggregates: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    """Apply frozen C3A eligibility gates and deterministic ranking."""
    validate_config(config)
    gate = config["gate"]
    by_policy: dict[str, dict[str, Mapping[str, Any]]] = {policy: {} for policy in POLICIES}
    for row in aggregates:
        policy = row.get("policy_id")
        label = row.get("cost_label")
        if policy in by_policy and label in COST_LABELS:
            by_policy[str(policy)][str(label)] = row

    eligible: list[dict[str, Any]] = []
    decisions: dict[str, Any] = {}
    for policy in POLICIES:
        expected = by_policy[policy].get("1.0x")
        stress = by_policy[policy].get("1.5x")
        if expected is None or stress is None:
            raise C3AResidualError(f"missing expected/stress aggregate for {policy}")
        reasons: list[str] = []
        sharpe = expected.get("aggregate_sharpe")
        if int(expected["positive_windows"]) < int(gate["minimum_positive_windows"]):
            reasons.append("positive_windows")
        if _finite(expected["median_window_net_return"], "median return") <= 0:
            reasons.append("median_window_return")
        if _finite(expected["aggregate_net_return"], "aggregate return") <= 0:
            reasons.append("aggregate_expected_return")
        if _finite(stress["aggregate_net_return"], "stress return") < 0:
            reasons.append("aggregate_1_5x_return")
        if sharpe is None or _finite(sharpe, "aggregate sharpe") < float(gate["minimum_aggregate_sharpe"]):
            reasons.append("aggregate_sharpe")
        if not _profit_factor_at_least(expected.get("profit_factor"), float(gate["minimum_profit_factor"])):
            reasons.append("profit_factor")
        if _finite(expected["maximum_window_drawdown"], "drawdown") > float(gate["maximum_window_drawdown_ratio"]):
            reasons.append("maximum_window_drawdown")
        if int(expected["closed_trades"]) < int(gate["minimum_closed_trades"]):
            reasons.append("closed_trades")
        if int(expected["minimum_window_closed_trades"]) < int(gate["minimum_closed_trades_per_window"]):
            reasons.append("minimum_window_closed_trades")
        if _finite(expected["exposure_ratio"], "exposure") > float(gate["maximum_exposure_ratio"]):
            reasons.append("exposure")
        if _finite(expected["annualized_one_way_turnover"], "turnover") > float(gate["maximum_annualized_one_way_turnover"]):
            reasons.append("turnover")
        if _finite(expected["maximum_window_positive_pnl_share"], "window concentration") > float(gate["maximum_window_positive_pnl_share"]):
            reasons.append("window_concentration")
        if _finite(expected["maximum_single_trade_positive_pnl_share"], "single trade concentration") > float(gate["maximum_single_trade_positive_pnl_share"]):
            reasons.append("single_trade_concentration")
        if _finite(expected["maximum_top_three_trade_positive_pnl_share"], "top-three concentration") > float(gate["maximum_top_three_trade_positive_pnl_share"]):
            reasons.append("top_three_trade_concentration")
        if policy == "C3AStrongestLaggardResidualReversion":
            asset_pnl = expected.get("asset_pnl")
            if not isinstance(asset_pnl, Mapping) or _finite(asset_pnl.get("ETH"), "ETH pnl") <= 0:
                reasons.append("eth_contribution")
            if not isinstance(asset_pnl, Mapping) or _finite(asset_pnl.get("SOL"), "SOL pnl") <= 0:
                reasons.append("sol_contribution")
            if _finite(expected["maximum_asset_positive_pnl_share"], "asset concentration") > float(
                gate["strongest_laggard_maximum_asset_positive_pnl_share"]
            ):
                reasons.append("asset_concentration")
        item = {
            "policy_id": policy,
            "eligible": not reasons,
            "rejection_reasons": reasons,
            "expected": dict(expected),
            "stress_1_5x": dict(stress),
        }
        decisions[policy] = item
        if not reasons:
            eligible.append(item)

    eligible.sort(
        key=lambda item: (
            -_finite(item["expected"]["minimum_window_net_return"], "minimum return"),
            -_finite(item["expected"]["median_window_net_return"], "median return"),
            -_finite(item["stress_1_5x"]["aggregate_net_return"], "stress return"),
            _finite(item["expected"]["maximum_window_drawdown"], "drawdown"),
            _finite(item["expected"]["annualized_one_way_turnover"], "turnover"),
            item["policy_id"],
        )
    )
    ranking = [item["policy_id"] for item in eligible]
    return {
        "schema_version": 1,
        "stage": "C3A",
        "economic_result": "SELECTED" if ranking else "REJECTED",
        "selected_policy": ranking[0] if ranking else None,
        "ranking": ranking,
        "policy_decisions": decisions,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def run_screen(market: pd.DataFrame, config: Mapping[str, Any]) -> dict[str, Any]:
    """Run the complete deterministic 27-policy-row and 36-comparator-row screen."""
    validate_config(config)
    policy_rows = [
        simulate_window(market, policy=policy, window=window, cost_label=cost_label, config=config)
        for policy in POLICIES
        for window in config["screen_windows"]
        for cost_label in COST_LABELS
    ]
    comparator_rows = [
        simulate_comparator(
            market,
            comparator_id=comparator,
            window=window,
            cost_label=cost_label,
            config=config,
        )
        for comparator in COMPARATORS
        for window in config["screen_windows"]
        for cost_label in COST_LABELS
    ]
    if len(policy_rows) != 27 or len(comparator_rows) != 36:
        raise C3AResidualError("authoritative row-count invariant failed")
    aggregates = [
        aggregate_policy(policy_rows, policy=policy, cost_label=cost_label, config=config)
        for policy in POLICIES
        for cost_label in COST_LABELS
    ]
    comparator_aggregates = [
        aggregate_comparator(comparator_rows, comparator, cost_label)
        for comparator in COMPARATORS
        for cost_label in COST_LABELS
    ]
    return {
        "schema_version": 1,
        "stage": "C3A",
        "policy_rows": policy_rows,
        "comparator_rows": comparator_rows,
        "policy_aggregates": aggregates,
        "comparator_aggregates": comparator_aggregates,
        "decision": decide(aggregates, config),
        "counts": {
            "policy_rows": len(policy_rows),
            "comparator_rows": len(comparator_rows),
            "result_pointers": len(policy_rows) + len(comparator_rows),
            "result_exports": len(policy_rows) + len(comparator_rows),
        },
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
