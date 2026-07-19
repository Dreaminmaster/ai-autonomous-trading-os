"""Independent reference recomputation for the frozen C3A screen.

The authoritative engine is intentionally not imported here.  This module uses
plain arrays and explicit loops to independently reconstruct indicators,
orders, fills, ledgers, equity, metrics, comparators, gates, and ranking from
retained primitive candles.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np


POLICIES = (
    "C3AEthResidualReversion",
    "C3ASolResidualReversion",
    "C3AStrongestLaggardResidualReversion",
)
PAIR_ORDER = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
COMPARATORS = ("cash", "btc_buy_hold", "eth_buy_hold", "sol_buy_hold")
COST_LABELS = ("1.0x", "1.5x", "2.0x")
ALIASES = {"BTC/USDT": "BTC", "ETH/USDT": "ETH", "SOL/USDT": "SOL"}
PAIR_BY_ASSET = {"BTC": "BTC/USDT", "ETH": "ETH/USDT", "SOL": "SOL/USDT"}
ANNUAL_BARS = 365 * 6
EXPECTED_CONFIG_CANONICAL_SHA256 = "d279da6e12edb0080c18f512cb8f81738de5c43eeb3ba2c00e6c678132074192"


class C3AReferenceError(RuntimeError):
    pass


def _finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise C3AReferenceError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C3AReferenceError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise C3AReferenceError(f"{label} must be finite")
    return result


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise C3AReferenceError(f"invalid timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def verify_config(config: Mapping[str, Any]) -> None:
    digest = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if digest != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C3AReferenceError("retained C3A semantic configuration drift")


@dataclass(frozen=True)
class ReferenceMarket:
    timestamps: tuple[datetime, ...]
    opens: Mapping[str, np.ndarray]
    closes: Mapping[str, np.ndarray]


@dataclass
class ReferencePosition:
    asset: str
    quantity: float
    entry_open: float
    entry_notional: float
    entry_fee: float
    entry_time: str
    held_bars: int = 0


def reference_prepare_market(candles: Mapping[str, Sequence[Mapping[str, Any]]]) -> ReferenceMarket:
    if set(candles) != set(PAIR_ORDER):
        raise C3AReferenceError("reference pair set mismatch")
    reference: tuple[datetime, ...] | None = None
    opens: dict[str, np.ndarray] = {}
    closes: dict[str, np.ndarray] = {}
    for pair in PAIR_ORDER:
        rows = candles[pair]
        if not rows:
            raise C3AReferenceError(f"no retained rows for {pair}")
        timestamps = tuple(_timestamp(row.get("date")) for row in rows)
        if timestamps != tuple(sorted(timestamps)) or len(set(timestamps)) != len(timestamps):
            raise C3AReferenceError(f"invalid timestamp sequence for {pair}")
        if reference is None:
            reference = timestamps
        elif timestamps != reference:
            raise C3AReferenceError(f"misaligned retained timestamps for {pair}")
        alias = ALIASES[pair]
        open_values = np.asarray([_finite(row.get("open"), f"{pair} open") for row in rows], dtype=float)
        close_values = np.asarray([_finite(row.get("close"), f"{pair} close") for row in rows], dtype=float)
        if np.any(open_values <= 0) or np.any(close_values <= 0):
            raise C3AReferenceError(f"non-positive retained price for {pair}")
        opens[alias] = open_values
        closes[alias] = close_values
    assert reference is not None
    return ReferenceMarket(reference, opens, closes)


def reference_indicators(market: ReferenceMarket, config: Mapping[str, Any]) -> dict[str, np.ndarray]:
    verify_config(config)
    n = len(market.timestamps)
    signal = config["signal"]
    beta_n = int(signal["beta_lookback"])
    residual_n = int(signal["residual_horizon"])
    z_n = int(signal["zscore_lookback"])
    output: dict[str, np.ndarray] = {}

    returns: dict[str, np.ndarray] = {}
    for asset in ("BTC", "ETH", "SOL"):
        values = np.full(n, np.nan, dtype=float)
        values[1:] = np.log(market.closes[asset][1:] / market.closes[asset][:-1])
        returns[asset] = values

    for asset in ("ETH", "SOL"):
        beta = np.full(n, np.nan, dtype=float)
        residual = np.full(n, np.nan, dtype=float)
        cumulative = np.full(n, np.nan, dtype=float)
        zscore = np.full(n, np.nan, dtype=float)
        for index in range(n):
            if index >= beta_n + 1:
                alt_sample = returns[asset][index - beta_n : index]
                btc_sample = returns["BTC"][index - beta_n : index]
                if np.isfinite(alt_sample).all() and np.isfinite(btc_sample).all():
                    alt_mean = float(np.mean(alt_sample))
                    btc_mean = float(np.mean(btc_sample))
                    covariance = float(np.mean(alt_sample * btc_sample) - alt_mean * btc_mean)
                    variance = float(np.mean(btc_sample * btc_sample) - btc_mean * btc_mean)
                    if math.isfinite(variance) and variance > 0:
                        raw = covariance / variance
                        beta[index] = min(float(signal["beta_max"]), max(float(signal["beta_min"]), raw))
                        residual[index] = returns[asset][index] - beta[index] * returns["BTC"][index]
            if index >= residual_n - 1:
                sample = residual[index - residual_n + 1 : index + 1]
                if np.isfinite(sample).all():
                    cumulative[index] = float(np.sum(sample))
            if index >= z_n and math.isfinite(cumulative[index]):
                sample = cumulative[index - z_n : index]
                if np.isfinite(sample).all():
                    deviation = float(np.std(sample, ddof=0))
                    if math.isfinite(deviation) and deviation > 0:
                        zscore[index] = (cumulative[index] - float(np.mean(sample))) / deviation
        output[f"beta_{asset}"] = beta
        output[f"residual_{asset}"] = residual
        output[f"cumulative_residual_{asset}"] = cumulative
        output[f"z_{asset}"] = zscore

    sma_n = int(signal["btc_sma_bars"])
    sma = np.full(n, np.nan, dtype=float)
    regime = np.zeros(n, dtype=bool)
    for index in range(sma_n - 1, n):
        sma[index] = float(np.mean(market.closes["BTC"][index - sma_n + 1 : index + 1]))
        regime[index] = market.closes["BTC"][index] >= sma[index]
    output["btc_sma"] = sma
    output["btc_regime_on"] = regime
    return output


def _drawdown(equity: Sequence[float]) -> float:
    peak = -math.inf
    result = 0.0
    for raw in equity:
        value = _finite(raw, "equity")
        if value <= 0:
            raise C3AReferenceError("reference equity is non-positive")
        peak = max(peak, value)
        result = max(result, 1.0 - value / peak)
    return result


def _returns(equity: Sequence[float]) -> list[float]:
    values = [float(value) for value in equity]
    return [values[index] / values[index - 1] - 1.0 for index in range(1, len(values))]


def _sharpe(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    array = np.asarray(values, dtype=float)
    if not np.isfinite(array).all():
        return None
    deviation = float(np.std(array, ddof=1))
    if not math.isfinite(deviation) or deviation == 0.0:
        return None
    result = float(np.mean(array) / deviation * math.sqrt(ANNUAL_BARS))
    return result if math.isfinite(result) else None


def _profit_factor(trades: Sequence[Mapping[str, Any]]) -> float | str:
    pnl = [float(trade["net_pnl"]) for trade in trades]
    gross_profit = sum(max(value, 0.0) for value in pnl)
    gross_loss = abs(sum(min(value, 0.0) for value in pnl))
    if gross_profit == 0.0:
        return 0.0
    if gross_loss == 0.0:
        return "Infinity"
    return gross_profit / gross_loss


def _positive_share(values: Sequence[float], top: int) -> float:
    positive = sorted((max(0.0, float(value)) for value in values), reverse=True)
    denominator = sum(positive)
    return 1.0 if denominator == 0.0 else sum(positive[:top]) / denominator


def _entry_asset(policy: str, indicators: Mapping[str, np.ndarray], index: int, config: Mapping[str, Any]) -> str | None:
    if not bool(indicators["btc_regime_on"][index]):
        return None
    threshold = float(config["signal"]["entry_zscore"])
    candidates: list[tuple[float, str]] = []
    if policy in (POLICIES[0], POLICIES[2]):
        value = float(indicators["z_ETH"][index])
        if math.isfinite(value) and value <= threshold:
            candidates.append((value, "ETH"))
    if policy in (POLICIES[1], POLICIES[2]):
        value = float(indicators["z_SOL"][index])
        if math.isfinite(value) and value <= threshold:
            candidates.append((value, "SOL"))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], 0 if item[1] == "ETH" else 1))
    return candidates[0][1]


def _trade(position: ReferencePosition, price: float, fee: float, time: str, reason: str) -> dict[str, Any]:
    proceeds = position.quantity * price
    return {
        "asset": position.asset,
        "pair": PAIR_BY_ASSET[position.asset],
        "entry_time": position.entry_time,
        "exit_time": time,
        "entry_open": position.entry_open,
        "exit_price": price,
        "quantity": position.quantity,
        "entry_notional": position.entry_notional,
        "entry_fee": position.entry_fee,
        "exit_notional": proceeds,
        "exit_fee": fee,
        "net_pnl": proceeds - fee - position.entry_notional - position.entry_fee,
        "held_bars": position.held_bars,
        "reason": reason,
    }


def reference_simulate_window(
    market: ReferenceMarket,
    indicators: Mapping[str, np.ndarray],
    *,
    policy: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    start = _timestamp(window["start"])
    end = _timestamp(window["end"])
    indices = [index for index, value in enumerate(market.timestamps) if start <= value < end]
    if not indices:
        raise C3AReferenceError("empty reference economic window")
    if sum(value < start for value in market.timestamps) < 450:
        raise C3AReferenceError("insufficient reference startup")

    fee_rate = float(config["cost_rates"][cost_label])
    starting = float(config["starting_equity"])
    cash = starting
    position: ReferencePosition | None = None
    pending: dict[str, Any] | None = None
    last_exit_index: int | None = None
    events: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    daily: list[dict[str, Any]] = []
    turnover: list[float] = []
    equity = [starting]
    exposed_bars = 0

    for local_index, index in enumerate(indices):
        timestamp = market.timestamps[index]
        stamp = timestamp.isoformat()
        final = local_index == len(indices) - 1

        if pending is not None:
            action = pending
            pending = None
            asset = str(action["asset"])
            if action["kind"] == "EXIT":
                if position is None or position.asset != asset:
                    raise C3AReferenceError("reference pending exit mismatch")
                price = float(market.opens[asset][index])
                pre_equity = cash + position.quantity * price
                notional = position.quantity * price
                fee = fee_rate * notional
                cash += notional - fee
                turnover.append(notional / pre_equity)
                trades.append(_trade(position, price, fee, stamp, str(action["reason"])))
                events.append({
                    "kind": "EXIT", "time": stamp, "asset": asset,
                    "reason": action["reason"], "notional": notional,
                    "fee": fee, "pre_trade_equity": pre_equity,
                })
                position = None
                last_exit_index = index
            elif action["kind"] == "ENTRY":
                if position is not None:
                    raise C3AReferenceError("reference overlapping position")
                price = float(market.opens[asset][index])
                pre_equity = cash
                target = float(config["position_target"])
                notional = target * pre_equity / (1.0 + target * fee_rate)
                fee = fee_rate * notional
                quantity = notional / price
                cash -= notional + fee
                post_equity = cash + quantity * price
                asset_share = quantity * price / post_equity
                turnover.append(notional / pre_equity)
                position = ReferencePosition(asset, quantity, price, notional, fee, stamp)
                events.append({
                    "kind": "ENTRY", "time": stamp, "asset": asset,
                    "notional": notional, "fee": fee,
                    "pre_trade_equity": pre_equity,
                    "post_cost_asset_share": asset_share,
                })
            else:
                raise C3AReferenceError("unknown reference pending action")

        close_equity = cash
        exposed = position is not None
        if position is not None:
            position.held_bars += 1
            close_equity += position.quantity * float(market.closes[position.asset][index])
            exposed_bars += 1

        terminal = False
        if final and position is not None:
            terminal = True
            pre_equity = close_equity
            price = float(market.closes[position.asset][index])
            notional = position.quantity * price
            fee = fee_rate * notional
            cash += notional - fee
            turnover.append(notional / pre_equity)
            trades.append(_trade(position, price, fee, stamp, "WINDOW_END"))
            events.append({
                "kind": "TERMINAL_LIQUIDATION", "time": stamp,
                "asset": position.asset, "notional": notional,
                "fee": fee, "pre_trade_equity": pre_equity,
            })
            position = None
            close_equity = cash

        equity.append(close_equity)
        daily.append({
            "time": stamp, "equity": close_equity, "cash": cash,
            "asset": position.asset if position else None,
            "quantity": position.quantity if position else 0.0,
            "exposed": exposed, "terminal": terminal,
        })
        if final:
            break

        if position is not None:
            z_value = float(indicators[f"z_{position.asset}"][index])
            gross_return = float(market.closes[position.asset][index]) / position.entry_open - 1.0
            reason: str | None = None
            if math.isfinite(z_value) and z_value >= float(config["signal"]["exit_zscore"]):
                reason = "RESIDUAL_NORMALIZATION"
            elif not bool(indicators["btc_regime_on"][index]):
                reason = "REGIME_EXIT"
            elif position.held_bars >= int(config["lifecycle"]["time_exit_bars"]):
                reason = "TIME_EXIT"
            elif gross_return <= float(config["lifecycle"]["price_stop_ratio"]):
                reason = "PRICE_STOP"
            if reason is not None:
                pending = {"kind": "EXIT", "asset": position.asset, "reason": reason}
        else:
            cooldown = int(config["lifecycle"]["cooldown_bars"])
            if last_exit_index is None or index >= last_exit_index + cooldown - 1:
                asset = _entry_asset(policy, indicators, index, config)
                if asset is not None:
                    pending = {"kind": "ENTRY", "asset": asset, "reason": "EXTREME_NEGATIVE_RESIDUAL"}

    if position is not None or pending is not None:
        raise C3AReferenceError("reference window did not terminate cleanly")
    final_equity = equity[-1]
    return {
        "schema_version": 1,
        "stage": "C3A",
        "policy_id": policy,
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "fee_rate": fee_rate,
        "starting_equity": starting,
        "final_equity": final_equity,
        "net_return": final_equity / starting - 1.0,
        "maximum_drawdown": _drawdown(equity),
        "closed_trades": len(trades),
        "profit_factor": _profit_factor(trades),
        "economic_bars": len(indices),
        "exposed_bars": exposed_bars,
        "exposure_ratio": exposed_bars / len(indices),
        "turnover_contributions": turnover,
        "annualized_one_way_turnover": sum(turnover) * ANNUAL_BARS / len(indices),
        "equity_returns": _returns(equity),
        "equity_curve": equity,
        "events": events,
        "trades": trades,
        "daily": daily,
        "status": "PASS",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def reference_comparator(
    market: ReferenceMarket,
    *,
    comparator_id: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    start = _timestamp(window["start"])
    end = _timestamp(window["end"])
    indices = [index for index, value in enumerate(market.timestamps) if start <= value < end]
    starting = float(config["starting_equity"])
    fee_rate = float(config["cost_rates"][cost_label])
    equity = [starting]
    turnover: list[float] = []
    trade: dict[str, Any] | None = None
    if comparator_id == "cash":
        equity.extend([starting] * len(indices))
    else:
        asset = {"btc_buy_hold": "BTC", "eth_buy_hold": "ETH", "sol_buy_hold": "SOL"}[comparator_id]
        first = indices[0]
        entry_notional = starting / (1.0 + fee_rate)
        entry_fee = entry_notional * fee_rate
        cash = starting - entry_notional - entry_fee
        quantity = entry_notional / float(market.opens[asset][first])
        turnover.append(entry_notional / starting)
        for local_index, index in enumerate(indices):
            close = float(market.closes[asset][index])
            marked = cash + quantity * close
            if local_index == len(indices) - 1:
                exit_notional = quantity * close
                exit_fee = exit_notional * fee_rate
                turnover.append(exit_notional / marked)
                cash += exit_notional - exit_fee
                marked = cash
                trade = {
                    "asset": asset,
                    "pair": PAIR_BY_ASSET[asset],
                    "entry_time": market.timestamps[first].isoformat(),
                    "exit_time": market.timestamps[index].isoformat(),
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
        "maximum_drawdown": _drawdown(equity),
        "closed_trades": 0 if trade is None else 1,
        "economic_bars": len(indices),
        "turnover_contributions": turnover,
        "equity_returns": _returns(equity),
        "trades": [] if trade is None else [trade],
        "status": "PASS",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def reference_aggregate_policy(
    rows: Sequence[Mapping[str, Any]], policy: str, cost_label: str, config: Mapping[str, Any]
) -> dict[str, Any]:
    expected_ids = [str(window["id"]) for window in config["screen_windows"]]
    selected = [row for row in rows if row["policy_id"] == policy and row["cost_label"] == cost_label]
    by_id = {str(row["window_id"]): row for row in selected}
    if len(selected) != 3 or set(by_id) != set(expected_ids):
        raise C3AReferenceError("reference aggregate window mismatch")
    ordered = [by_id[value] for value in expected_ids]
    window_returns = {str(row["window_id"]): float(row["net_return"]) for row in ordered}
    all_returns = [float(value) for row in ordered for value in row["equity_returns"]]
    trades = [dict(value) for row in ordered for value in row["trades"]]
    turnover = [float(value) for row in ordered for value in row["turnover_contributions"]]
    total_bars = sum(int(row["economic_bars"]) for row in ordered)
    exposed_bars = sum(int(row["exposed_bars"]) for row in ordered)
    pnl = [float(value["net_pnl"]) for value in trades]
    asset_pnl = {
        asset: sum(float(value["net_pnl"]) for value in trades if value["asset"] == asset)
        for asset in ("ETH", "SOL")
    }
    return {
        "schema_version": 1,
        "stage": "C3A",
        "policy_id": policy,
        "cost_label": cost_label,
        "window_returns": window_returns,
        "minimum_window_net_return": min(window_returns.values()),
        "median_window_net_return": float(median(window_returns.values())),
        "positive_windows": sum(value > 0 for value in window_returns.values()),
        "aggregate_net_return": math.prod(1.0 + value for value in window_returns.values()) - 1.0,
        "aggregate_sharpe": _sharpe(all_returns),
        "profit_factor": _profit_factor(trades),
        "maximum_window_drawdown": max(float(row["maximum_drawdown"]) for row in ordered),
        "closed_trades": len(trades),
        "minimum_window_closed_trades": min(int(row["closed_trades"]) for row in ordered),
        "economic_bars": total_bars,
        "exposed_bars": exposed_bars,
        "exposure_ratio": exposed_bars / total_bars,
        "annualized_one_way_turnover": sum(turnover) * ANNUAL_BARS / total_bars,
        "maximum_window_positive_pnl_share": _positive_share(
            [float(row["final_equity"]) - float(config["starting_equity"]) for row in ordered], 1
        ),
        "maximum_single_trade_positive_pnl_share": _positive_share(pnl, 1),
        "maximum_top_three_trade_positive_pnl_share": _positive_share(pnl, 3),
        "asset_pnl": asset_pnl,
        "maximum_asset_positive_pnl_share": _positive_share(list(asset_pnl.values()), 1),
        "trades": trades,
        "status": "PASS",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def reference_aggregate_comparator(
    rows: Sequence[Mapping[str, Any]], comparator_id: str, cost_label: str, config: Mapping[str, Any]
) -> dict[str, Any]:
    expected_ids = [str(window["id"]) for window in config["screen_windows"]]
    selected = [row for row in rows if row["comparator_id"] == comparator_id and row["cost_label"] == cost_label]
    by_id = {str(row["window_id"]): row for row in selected}
    if len(selected) != 3 or set(by_id) != set(expected_ids):
        raise C3AReferenceError("reference comparator aggregate window mismatch")
    ordered = [by_id[value] for value in expected_ids]
    window_returns = {str(row["window_id"]): float(row["net_return"]) for row in ordered}
    return {
        "comparator_id": comparator_id,
        "cost_label": cost_label,
        "window_returns": window_returns,
        "aggregate_net_return": math.prod(1.0 + value for value in window_returns.values()) - 1.0,
        "maximum_window_drawdown": max(float(row["maximum_drawdown"]) for row in ordered),
        "status": "PASS",
    }


def _pf_gate(value: Any, threshold: float) -> bool:
    if value == "Infinity":
        return True
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= threshold


def reference_decide(aggregates: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    gate = config["gate"]
    indexed: dict[str, dict[str, Mapping[str, Any]]] = {policy: {} for policy in POLICIES}
    for row in aggregates:
        indexed[str(row["policy_id"])][str(row["cost_label"])] = row
    eligible: list[dict[str, Any]] = []
    decisions: dict[str, Any] = {}
    for policy in POLICIES:
        expected = indexed[policy]["1.0x"]
        stress = indexed[policy]["1.5x"]
        reasons: list[str] = []
        if int(expected["positive_windows"]) < int(gate["minimum_positive_windows"]): reasons.append("positive_windows")
        if float(expected["median_window_net_return"]) <= 0: reasons.append("median_window_return")
        if float(expected["aggregate_net_return"]) <= 0: reasons.append("aggregate_expected_return")
        if float(stress["aggregate_net_return"]) < 0: reasons.append("aggregate_1_5x_return")
        if expected["aggregate_sharpe"] is None or float(expected["aggregate_sharpe"]) < float(gate["minimum_aggregate_sharpe"]): reasons.append("aggregate_sharpe")
        if not _pf_gate(expected["profit_factor"], float(gate["minimum_profit_factor"])): reasons.append("profit_factor")
        if float(expected["maximum_window_drawdown"]) > float(gate["maximum_window_drawdown_ratio"]): reasons.append("maximum_window_drawdown")
        if int(expected["closed_trades"]) < int(gate["minimum_closed_trades"]): reasons.append("closed_trades")
        if int(expected["minimum_window_closed_trades"]) < int(gate["minimum_closed_trades_per_window"]): reasons.append("minimum_window_closed_trades")
        if float(expected["exposure_ratio"]) > float(gate["maximum_exposure_ratio"]): reasons.append("exposure")
        if float(expected["annualized_one_way_turnover"]) > float(gate["maximum_annualized_one_way_turnover"]): reasons.append("turnover")
        if float(expected["maximum_window_positive_pnl_share"]) > float(gate["maximum_window_positive_pnl_share"]): reasons.append("window_concentration")
        if float(expected["maximum_single_trade_positive_pnl_share"]) > float(gate["maximum_single_trade_positive_pnl_share"]): reasons.append("single_trade_concentration")
        if float(expected["maximum_top_three_trade_positive_pnl_share"]) > float(gate["maximum_top_three_trade_positive_pnl_share"]): reasons.append("top_three_trade_concentration")
        if policy == POLICIES[2]:
            if float(expected["asset_pnl"]["ETH"]) <= 0: reasons.append("eth_contribution")
            if float(expected["asset_pnl"]["SOL"]) <= 0: reasons.append("sol_contribution")
            if float(expected["maximum_asset_positive_pnl_share"]) > float(gate["strongest_laggard_maximum_asset_positive_pnl_share"]): reasons.append("asset_concentration")
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
    eligible.sort(key=lambda item: (
        -float(item["expected"]["minimum_window_net_return"]),
        -float(item["expected"]["median_window_net_return"]),
        -float(item["stress_1_5x"]["aggregate_net_return"]),
        float(item["expected"]["maximum_window_drawdown"]),
        float(item["expected"]["annualized_one_way_turnover"]),
        item["policy_id"],
    ))
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


def reference_run_screen(market: ReferenceMarket, config: Mapping[str, Any]) -> dict[str, Any]:
    verify_config(config)
    indicators = reference_indicators(market, config)
    policy_rows = [
        reference_simulate_window(
            market, indicators, policy=policy, window=window, cost_label=cost_label, config=config
        )
        for policy in POLICIES
        for window in config["screen_windows"]
        for cost_label in COST_LABELS
    ]
    comparator_rows = [
        reference_comparator(
            market, comparator_id=comparator, window=window, cost_label=cost_label, config=config
        )
        for comparator in COMPARATORS
        for window in config["screen_windows"]
        for cost_label in COST_LABELS
    ]
    aggregates = [
        reference_aggregate_policy(policy_rows, policy, cost_label, config)
        for policy in POLICIES for cost_label in COST_LABELS
    ]
    comparator_aggregates = [
        reference_aggregate_comparator(comparator_rows, comparator, cost_label, config)
        for comparator in COMPARATORS for cost_label in COST_LABELS
    ]
    return {
        "schema_version": 1,
        "stage": "C3A",
        "policy_rows": policy_rows,
        "comparator_rows": comparator_rows,
        "policy_aggregates": aggregates,
        "comparator_aggregates": comparator_aggregates,
        "decision": reference_decide(aggregates, config),
        "counts": {
            "policy_rows": len(policy_rows),
            "comparator_rows": len(comparator_rows),
            "result_pointers": len(policy_rows) + len(comparator_rows),
            "result_exports": len(policy_rows) + len(comparator_rows),
        },
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
