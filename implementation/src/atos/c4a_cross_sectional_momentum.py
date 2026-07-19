"""Deterministic C4A large-liquid cross-sectional momentum research engine.

This module implements only the frozen public-data development screen. It has no
exchange-account, private API, paper, shadow, leverage, derivative, or live path.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.stats import kurtosis, norm, skew

CANDIDATE_PAIRS = (
    "ADA/USDT", "AVAX/USDT", "BCH/USDT", "BTC/USDT", "DOGE/USDT", "DOT/USDT",
    "ETH/USDT", "LINK/USDT", "LTC/USDT", "SOL/USDT", "TRX/USDT", "XRP/USDT",
)
POLICIES = (
    "C4AWeeklyReturnTopTwo",
    "C4AHighProximityTopTwo",
    "C4ACompositeMomentumTopTwo",
)
COMPARATORS = (
    "cash",
    "btc_buy_hold",
    "top8_equal_weight_buy_hold",
    "btc_eth_sol_equal_weight_buy_hold",
)
COST_LABELS = ("1.0x", "1.5x", "2.0x")
ALIAS = {pair: pair.split("/")[0] for pair in CANDIDATE_PAIRS}
ANNUAL_FOUR_HOUR_BARS = 6 * 365
SECONDS_PER_YEAR = 365 * 24 * 60 * 60
GAMMA = 0.5772156649015329


class C4AError(RuntimeError):
    """Raised when a frozen C4A invariant or accounting rule fails."""


def _finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise C4AError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C4AError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise C4AError(f"{label} must be finite")
    return result


def _ts(value: Any) -> pd.Timestamp:
    parsed = pd.Timestamp(value)
    return parsed.tz_localize("UTC") if parsed.tzinfo is None else parsed.tz_convert("UTC")


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("schema_version") != 1 or config.get("stage") != "C4A":
        raise C4AError("C4A config identity drift")
    if config.get("live") != "FORBIDDEN" or config.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C4AError("C4A safety state drift")
    if config.get("confirmation_opened") is not False:
        raise C4AError("C4A confirmation must remain closed")
    if config.get("required_design_main_sha") != "96015f9f15c04a4a834878bb32215194ce05c7eb":
        raise C4AError("C4A design-main identity drift")
    if config.get("candidate_pairs") != list(CANDIDATE_PAIRS):
        raise C4AError("C4A candidate universe drift")
    if config.get("policies") != list(POLICIES) or config.get("comparators") != list(COMPARATORS):
        raise C4AError("C4A policy/comparator drift")
    if config.get("timeframe") != "4h" or config.get("download_timerange") != "20230901-20241001":
        raise C4AError("C4A timeframe/timerange drift")
    if config.get("economic_boundary_exclusive") != "2024-10-01T00:00:00Z":
        raise C4AError("C4A boundary drift")
    if config.get("formation_start") != "2023-09-01T00:00:00Z" or config.get("formation_end") != "2024-01-01T00:00:00Z":
        raise C4AError("C4A formation boundary drift")
    expected_windows = [
        {"id": "S1", "start": "2024-01-01T00:00:00Z", "end": "2024-04-01T00:00:00Z"},
        {"id": "S2", "start": "2024-04-01T00:00:00Z", "end": "2024-07-01T00:00:00Z"},
        {"id": "S3", "start": "2024-07-01T00:00:00Z", "end": "2024-10-01T00:00:00Z"},
    ]
    if config.get("screen_windows") != expected_windows:
        raise C4AError("C4A screen windows drift")
    expected_scalar = {
        "starting_equity": 1000.0,
        "selected_universe_size": 8,
        "position_count": 2,
        "invested_weight": 0.9,
        "target_weight_per_asset": 0.45,
        "weekly_lookback_intervals": 42,
        "weekly_high_bars": 42,
        "minimum_breadth": 0.5,
        "dsr_trial_count": 3,
        "dsr_sample_count": 39,
    }
    for key, expected in expected_scalar.items():
        actual = config.get(key)
        if isinstance(expected, int):
            if int(actual) != expected:
                raise C4AError(f"C4A config drift: {key}")
        elif _finite(actual, key) != expected:
            raise C4AError(f"C4A config drift: {key}")
    rates = config.get("cost_rates")
    if not isinstance(rates, Mapping) or list(rates) != list(COST_LABELS):
        raise C4AError("C4A cost labels drift")
    if [_finite(rates[k], k) for k in COST_LABELS] != [0.0015, 0.00225, 0.003]:
        raise C4AError("C4A cost rates drift")


def prepare_market(candles_by_pair: Mapping[str, Sequence[Mapping[str, Any]]]) -> pd.DataFrame:
    if set(candles_by_pair) != set(CANDIDATE_PAIRS):
        raise C4AError("market pair set mismatch")
    frames: list[pd.DataFrame] = []
    reference: pd.DatetimeIndex | None = None
    for pair in CANDIDATE_PAIRS:
        rows = candles_by_pair[pair]
        if not rows:
            raise C4AError(f"no candles for {pair}")
        frame = pd.DataFrame([dict(row) for row in rows])
        required = {"date", "open", "high", "low", "close", "volume"}
        if not required.issubset(frame.columns):
            raise C4AError(f"{pair} missing candle fields")
        frame = frame.loc[:, ["date", "open", "high", "low", "close", "volume"]].copy()
        frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="raise")
        if frame["date"].duplicated().any() or not frame["date"].is_monotonic_increasing:
            raise C4AError(f"unordered or duplicate candles for {pair}")
        frame = frame.set_index("date")
        for field_name in ("open", "high", "low", "close", "volume"):
            frame[field_name] = pd.to_numeric(frame[field_name], errors="raise").astype(float)
            if not np.isfinite(frame[field_name]).all() or (frame[field_name] <= 0).any():
                raise C4AError(f"invalid {field_name} for {pair}")
        invalid_ohlc = (
            (frame["low"] > frame["high"])
            | (frame["open"] < frame["low"])
            | (frame["open"] > frame["high"])
            | (frame["close"] < frame["low"])
            | (frame["close"] > frame["high"])
        )
        if invalid_ohlc.any():
            raise C4AError(f"invalid OHLC geometry for {pair}")
        if reference is None:
            reference = frame.index
        elif not frame.index.equals(reference):
            raise C4AError(f"timestamp alignment mismatch for {pair}")
        prefix = ALIAS[pair]
        frame.columns = [f"{prefix}_{column}" for column in frame.columns]
        frames.append(frame)
    market = pd.concat(frames, axis=1)
    if market.empty or market.isna().any().any():
        raise C4AError("empty or incomplete aligned market")
    return market


def expected_grid() -> pd.DatetimeIndex:
    return pd.date_range("2023-09-01T00:00:00Z", "2024-09-30T20:00:00Z", freq="4h")


def select_universe(market: pd.DataFrame, config: Mapping[str, Any]) -> dict[str, Any]:
    validate_config(config)
    if not market.index.equals(expected_grid()):
        raise C4AError("retained market does not match exact C4A grid")
    start, end = _ts(config["formation_start"]), _ts(config["formation_end"])
    formation = market.loc[(market.index >= start) & (market.index < end)]
    if len(formation) != 732:
        raise C4AError("formation count mismatch")
    scores: list[dict[str, Any]] = []
    for pair in CANDIDATE_PAIRS:
        prefix = ALIAS[pair]
        proxy = formation[f"{prefix}_close"].to_numpy(float) * formation[f"{prefix}_volume"].to_numpy(float)
        if len(proxy) != 732 or not np.isfinite(proxy).all():
            raise C4AError(f"invalid liquidity proxy for {pair}")
        scores.append({"pair": pair, "liquidity_score": float(np.median(proxy))})
    scores.sort(key=lambda item: (-item["liquidity_score"], item["pair"]))
    selected_size = int(config["selected_universe_size"])
    for index, item in enumerate(scores, start=1):
        item["rank"] = index
        item["selected"] = index <= selected_size
    selected = [item["pair"] for item in scores if item["selected"]]
    if len(selected) != 8:
        raise C4AError("selected universe size mismatch")
    return {
        "schema_version": 1,
        "stage": "C4A",
        "status": "PASS",
        "formation_rows": len(formation),
        "candidates": scores,
        "selected_pairs": selected,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def scheduled_decisions(window: Mapping[str, Any]) -> list[pd.Timestamp]:
    start, end = _ts(window["start"]), _ts(window["end"])
    index = pd.date_range(start, end - pd.Timedelta(hours=4), freq="4h")
    return [timestamp for timestamp in index if timestamp.weekday() == 0 and timestamp.hour == 0]


def _ordinal_rank(values: Mapping[str, float]) -> dict[str, int]:
    ordered = sorted(values, key=lambda pair: (-values[pair], pair))
    size = len(ordered)
    return {pair: size - index for index, pair in enumerate(ordered)}


def signal_snapshot(
    market: pd.DataFrame,
    *,
    execution_time: pd.Timestamp,
    selected_pairs: Sequence[str],
    policy: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    if policy not in POLICIES or len(selected_pairs) != 8:
        raise C4AError("invalid signal policy or universe")
    try:
        execution_position = market.index.get_loc(execution_time)
    except KeyError as exc:
        raise C4AError("execution timestamp absent") from exc
    signal_position = int(execution_position) - 1
    lookback = int(config["weekly_lookback_intervals"])
    if signal_position - lookback < 0:
        raise C4AError("insufficient weekly startup")
    signal_time = market.index[signal_position]
    if signal_time.weekday() != 6 or signal_time.hour != 20:
        raise C4AError("signal timestamp is not Sunday 20 UTC")
    weekly_return: dict[str, float] = {}
    proximity: dict[str, float] = {}
    for pair in selected_pairs:
        prefix = ALIAS[pair]
        close_now = _finite(market.iloc[signal_position][f"{prefix}_close"], "signal close")
        close_then = _finite(market.iloc[signal_position - lookback][f"{prefix}_close"], "lookback close")
        weekly_return[pair] = close_now / close_then - 1.0
        highs = market.iloc[signal_position - 41 : signal_position + 1][f"{prefix}_high"].to_numpy(float)
        if len(highs) != 42 or not np.isfinite(highs).all():
            raise C4AError("high-proximity window mismatch")
        proximity[pair] = close_now / float(np.max(highs))
    positive = [pair for pair in selected_pairs if weekly_return[pair] > 0.0]
    breadth = len(positive) / 8.0
    risk_on = breadth >= float(config["minimum_breadth"]) and len(positive) >= 2
    return_rank = _ordinal_rank(weekly_return)
    proximity_rank = _ordinal_rank(proximity)
    composite = {pair: (return_rank[pair] + proximity_rank[pair]) / 2.0 for pair in selected_pairs}
    chosen: list[str] = []
    if risk_on:
        if policy == "C4AWeeklyReturnTopTwo":
            chosen = sorted(positive, key=lambda pair: (-weekly_return[pair], pair))[:2]
        elif policy == "C4AHighProximityTopTwo":
            chosen = sorted(positive, key=lambda pair: (-proximity[pair], pair))[:2]
        else:
            chosen = sorted(
                positive,
                key=lambda pair: (-composite[pair], -weekly_return[pair], -proximity[pair], pair),
            )[:2]
    targets = {pair: float(config["target_weight_per_asset"]) for pair in chosen}
    rows = [
        {
            "pair": pair,
            "weekly_return": weekly_return[pair],
            "high_proximity": proximity[pair],
            "weekly_return_rank": return_rank[pair],
            "high_proximity_rank": proximity_rank[pair],
            "composite_score": composite[pair],
            "positive": weekly_return[pair] > 0,
            "selected_target": pair in targets,
        }
        for pair in selected_pairs
    ]
    return {
        "execution_time": execution_time.isoformat(),
        "signal_time": signal_time.isoformat(),
        "policy_id": policy,
        "breadth": breadth,
        "risk_on": risk_on,
        "chosen_pairs": chosen,
        "target_weights": targets,
        "rows": rows,
    }


def solve_post_cost_equity(
    *,
    equity_before: float,
    current_values: Mapping[str, float],
    target_weights: Mapping[str, float],
    fee_rate: float,
) -> dict[str, Any]:
    equity_before = _finite(equity_before, "equity before")
    fee_rate = _finite(fee_rate, "fee rate")
    if equity_before <= 0 or fee_rate < 0:
        raise C4AError("invalid solver inputs")
    keys = sorted(set(current_values) | set(target_weights))
    current = {key: _finite(current_values.get(key, 0.0), f"current value {key}") for key in keys}
    weights = {key: _finite(target_weights.get(key, 0.0), f"target weight {key}") for key in keys}
    if any(value < 0 for value in current.values()) or any(value < 0 for value in weights.values()):
        raise C4AError("negative value or weight")
    if sum(weights.values()) > 1.0 + 1e-12:
        raise C4AError("target weights exceed one")

    def equation(equity: float) -> float:
        return equity + fee_rate * sum(abs(weights[key] * equity - current[key]) for key in keys) - equity_before

    lower, upper = 0.0, equity_before
    if equation(lower) > 1e-12 or equation(upper) < -1e-12:
        raise C4AError("root is not bracketed")
    midpoint = upper
    iterations = 0
    for iterations in range(1, 201):
        midpoint = (lower + upper) / 2.0
        value = equation(midpoint)
        if abs(value) <= 1e-12 or upper - lower <= 1e-12:
            break
        if value > 0:
            upper = midpoint
        else:
            lower = midpoint
    else:
        raise C4AError("post-cost root did not converge")
    target_values = {key: weights[key] * midpoint for key in keys}
    deltas = {key: target_values[key] - current[key] for key in keys}
    fees = {key: fee_rate * abs(deltas[key]) for key in keys}
    total_fee = sum(fees.values())
    cash = midpoint - sum(target_values.values())
    residual = equity_before - total_fee - midpoint
    if cash < -1e-12 or abs(residual) > 1e-9:
        raise C4AError("post-cost accounting identity failure")
    return {
        "equity_before": equity_before,
        "equity_after": midpoint,
        "target_values": target_values,
        "trade_deltas": deltas,
        "fees": fees,
        "total_fee": total_fee,
        "cash": max(0.0, cash),
        "residual": residual,
        "iterations": iterations,
    }


@dataclass
class LotState:
    pair: str
    window_id: str
    entry_time: str
    opening_quantity: float
    net_pnl: float = 0.0
    adjustments: list[dict[str, Any]] = field(default_factory=list)


def _max_drawdown(equity: Sequence[float]) -> float:
    peak = -math.inf
    maximum = 0.0
    for raw in equity:
        value = _finite(raw, "equity")
        if value <= 0:
            raise C4AError("equity must remain positive")
        peak = max(peak, value)
        maximum = max(maximum, 1.0 - value / peak)
    return maximum


def _returns(equity: Sequence[float]) -> list[float]:
    values = [_finite(value, "equity") for value in equity]
    return [values[index] / values[index - 1] - 1.0 for index in range(1, len(values))]


def _four_hour_sharpe(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    array = np.asarray(values, float)
    deviation = float(np.std(array, ddof=1))
    mean_value = float(np.mean(array))
    if not np.isfinite(array).all() or not math.isfinite(deviation):
        return None
    if deviation == 0:
        if mean_value == 0:
            return 0.0
        raise C4AError("nonzero mean with zero return variance")
    return mean_value / deviation * math.sqrt(ANNUAL_FOUR_HOUR_BARS)


def _positive_share(values: Sequence[float], *, top: int = 1) -> float | None:
    positive = sorted((value for value in (_finite(item, "pnl") for item in values) if value > 0), reverse=True)
    total = sum(positive)
    return None if total <= 0 else sum(positive[:top]) / total


def _close_lot(
    active: dict[str, LotState],
    pair: str,
    timestamp: pd.Timestamp,
    closed: list[dict[str, Any]],
) -> None:
    lot = active.pop(pair, None)
    if lot is None:
        raise C4AError(f"missing active lot for {pair}")
    closed.append(
        {
            "pair": pair,
            "window_id": lot.window_id,
            "entry_time": lot.entry_time,
            "exit_time": timestamp.isoformat(),
            "opening_quantity": lot.opening_quantity,
            "adjustments": lot.adjustments,
            "net_pnl": lot.net_pnl,
        }
    )


def simulate_window(
    market: pd.DataFrame,
    *,
    selected_pairs: Sequence[str],
    policy: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    if policy not in POLICIES or cost_label not in COST_LABELS or len(selected_pairs) != 8:
        raise C4AError("unknown policy/cost or invalid selected universe")
    start, end = _ts(window["start"]), _ts(window["end"])
    economic = market.loc[(market.index >= start) & (market.index < end)]
    expected = pd.date_range(start, end - pd.Timedelta(hours=4), freq="4h")
    if not economic.index.equals(expected):
        raise C4AError("economic timestamp sequence mismatch")
    schedules = set(scheduled_decisions(window))
    expected_schedule_count = {"S1": 13, "S2": 13, "S3": 14}[str(window["id"])]
    if len(schedules) != expected_schedule_count:
        raise C4AError("scheduled decision count mismatch")
    fee_rate = float(config["cost_rates"][cost_label])
    cash = float(config["starting_equity"])
    quantities = {pair: 0.0 for pair in selected_pairs}
    asset_contributions = {pair: 0.0 for pair in selected_pairs}
    active_lots: dict[str, LotState] = {}
    closed_lots: list[dict[str, Any]] = []
    marks: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    turnover: list[float] = []
    equity_curve = [cash]
    exposed_bars = 0
    active_decisions = 0
    traded_decisions = 0
    full_weeks: list[dict[str, Any]] = []
    week_start: dict[str, Any] | None = None
    previous_close_prices: dict[str, float] | None = None
    previous_post_close_equity = cash
    stub_start_equity: float | None = None

    for local_index, (timestamp, row) in enumerate(economic.iterrows()):
        is_final = local_index == len(economic) - 1
        open_prices = {pair: _finite(row[f"{ALIAS[pair]}_open"], f"{pair} open") for pair in selected_pairs}
        close_prices = {pair: _finite(row[f"{ALIAS[pair]}_close"], f"{pair} close") for pair in selected_pairs}
        boundary_gap_pnl = 0.0
        if previous_close_prices is not None:
            for pair in selected_pairs:
                pnl = quantities[pair] * (open_prices[pair] - previous_close_prices[pair])
                asset_contributions[pair] += pnl
                if pair in active_lots:
                    active_lots[pair].net_pnl += pnl
                boundary_gap_pnl += pnl
        equity_at_open = cash + sum(quantities[pair] * open_prices[pair] for pair in selected_pairs)
        if equity_at_open <= 0 or not math.isfinite(equity_at_open):
            raise C4AError("invalid open equity")
        event_fee = 0.0
        forced_stub = str(window["id"]) == "S3" and timestamp == pd.Timestamp("2024-09-30T00:00:00Z")
        if timestamp in schedules:
            if forced_stub:
                stub_start_equity = previous_post_close_equity
                target_weights: dict[str, float] = {}
                snapshot = {
                    "execution_time": timestamp.isoformat(),
                    "signal_time": (timestamp - pd.Timedelta(hours=4)).isoformat(),
                    "policy_id": policy,
                    "breadth": None,
                    "risk_on": False,
                    "chosen_pairs": [],
                    "target_weights": {},
                    "rows": [],
                    "forced_cash": True,
                }
            else:
                if week_start is not None:
                    raise C4AError("previous full week did not close")
                week_start = {
                    "start_reference_time": None if local_index == 0 else (timestamp - pd.Timedelta(hours=4)).isoformat(),
                    "start_reference_equity": previous_post_close_equity,
                    "execution_time": timestamp.isoformat(),
                    "boundary_gap_pnl": boundary_gap_pnl,
                }
                snapshot = signal_snapshot(
                    market,
                    execution_time=timestamp,
                    selected_pairs=selected_pairs,
                    policy=policy,
                    config=config,
                )
                target_weights = dict(snapshot["target_weights"])
            signals.append(snapshot)
            if target_weights:
                active_decisions += 1
            current_values = {pair: quantities[pair] * open_prices[pair] for pair in selected_pairs}
            solved = solve_post_cost_equity(
                equity_before=equity_at_open,
                current_values=current_values,
                target_weights=target_weights,
                fee_rate=fee_rate,
            )
            before = dict(quantities)
            for pair in selected_pairs:
                fee = solved["fees"][pair]
                event_fee += fee
                asset_contributions[pair] -= fee
                if pair in active_lots:
                    active_lots[pair].net_pnl -= fee
                target_value = solved["target_values"][pair]
                after_quantity = target_value / open_prices[pair] if target_value > 0 else 0.0
                if before[pair] == 0.0 and after_quantity > 0.0:
                    lot = LotState(
                        pair=pair,
                        window_id=str(window["id"]),
                        entry_time=timestamp.isoformat(),
                        opening_quantity=after_quantity,
                    )
                    lot.net_pnl -= fee
                    active_lots[pair] = lot
                elif before[pair] > 0.0 and after_quantity == 0.0:
                    if pair not in active_lots:
                        raise C4AError("lot state missing on close")
                    active_lots[pair].adjustments.append(
                        {
                            "time": timestamp.isoformat(),
                            "quantity_before": before[pair],
                            "quantity_after": 0.0,
                            "fee": fee,
                        }
                    )
                    _close_lot(active_lots, pair, timestamp, closed_lots)
                elif before[pair] > 0.0 and after_quantity > 0.0:
                    active_lots[pair].adjustments.append(
                        {
                            "time": timestamp.isoformat(),
                            "quantity_before": before[pair],
                            "quantity_after": after_quantity,
                            "fee": fee,
                        }
                    )
                quantities[pair] = after_quantity
            cash = solved["cash"]
            traded_notional = sum(abs(value) for value in solved["trade_deltas"].values())
            if traded_notional > 0:
                traded_decisions += 1
            turnover.append(traded_notional / equity_at_open)
            events.append(
                {
                    "kind": "FORCED_CASH" if forced_stub else "SCHEDULED_REBALANCE",
                    "time": timestamp.isoformat(),
                    "policy_id": policy,
                    "target_weights": target_weights,
                    "equity_before": equity_at_open,
                    "equity_after": solved["equity_after"],
                    "trade_deltas": solved["trade_deltas"],
                    "fees": solved["fees"],
                    "total_fee": event_fee,
                    "cash": cash,
                    "iterations": solved["iterations"],
                    "boundary_gap_pnl": boundary_gap_pnl,
                }
            )
        bar_exposed = any(quantity > 0 for quantity in quantities.values())
        if bar_exposed:
            exposed_bars += 1
        for pair in selected_pairs:
            pnl = quantities[pair] * (close_prices[pair] - open_prices[pair])
            asset_contributions[pair] += pnl
            if pair in active_lots:
                active_lots[pair].net_pnl += pnl
        close_equity = cash + sum(quantities[pair] * close_prices[pair] for pair in selected_pairs)
        terminal_fee = 0.0
        terminal = False
        if is_final and any(quantity > 0 for quantity in quantities.values()):
            terminal = True
            current_values = {pair: quantities[pair] * close_prices[pair] for pair in selected_pairs}
            solved = solve_post_cost_equity(
                equity_before=close_equity,
                current_values=current_values,
                target_weights={},
                fee_rate=fee_rate,
            )
            before = dict(quantities)
            for pair in selected_pairs:
                fee = solved["fees"][pair]
                terminal_fee += fee
                asset_contributions[pair] -= fee
                if pair in active_lots:
                    active_lots[pair].net_pnl -= fee
                if before[pair] > 0:
                    active_lots[pair].adjustments.append(
                        {
                            "time": timestamp.isoformat(),
                            "quantity_before": before[pair],
                            "quantity_after": 0.0,
                            "fee": fee,
                            "terminal": True,
                        }
                    )
                    quantities[pair] = 0.0
                    _close_lot(active_lots, pair, timestamp, closed_lots)
            cash = solved["cash"]
            turnover.append(sum(abs(value) for value in solved["trade_deltas"].values()) / close_equity)
            close_equity = cash
            events.append(
                {
                    "kind": "TERMINAL_LIQUIDATION",
                    "time": timestamp.isoformat(),
                    "fees": solved["fees"],
                    "total_fee": terminal_fee,
                    "equity_before": solved["equity_before"],
                    "equity_after": solved["equity_after"],
                }
            )
        if close_equity <= 0 or not math.isfinite(close_equity):
            raise C4AError("invalid close equity")
        if timestamp.weekday() == 6 and timestamp.hour == 20 and week_start is not None:
            week_pnl = close_equity - float(week_start["start_reference_equity"])
            full_weeks.append(
                {
                    **week_start,
                    "end_time": timestamp.isoformat(),
                    "ending_equity": close_equity,
                    "net_pnl": week_pnl,
                    "net_return": close_equity / float(week_start["start_reference_equity"]) - 1.0,
                    "ending_terminal_fee": terminal_fee,
                }
            )
            week_start = None
        equity_curve.append(close_equity)
        marks.append(
            {
                "time": timestamp.isoformat(),
                "equity": close_equity,
                "cash": cash,
                "bar_exposed": bar_exposed,
                "post_close_quantities": dict(quantities),
                "terminal": terminal,
                "terminal_fee": terminal_fee,
            }
        )
        previous_close_prices = close_prices
        previous_post_close_equity = close_equity
    if active_lots or any(quantity != 0.0 for quantity in quantities.values()) or week_start is not None:
        raise C4AError("window did not terminate cleanly")
    if len(full_weeks) != 13:
        raise C4AError(f"full-week count mismatch: {len(full_weeks)}")
    final_equity = equity_curve[-1]
    contribution_total = sum(asset_contributions.values())
    if abs(contribution_total - (final_equity - float(config["starting_equity"]))) > 1e-9:
        raise C4AError("asset contribution reconciliation failure")
    stub_pnl = 0.0
    if str(window["id"]) == "S3":
        if stub_start_equity is None:
            raise C4AError("missing S3 stub start")
        stub_pnl = final_equity - stub_start_equity
    duration_years = (end - start).total_seconds() / SECONDS_PER_YEAR
    return {
        "schema_version": 1,
        "stage": "C4A",
        "status": "PASS",
        "policy_id": policy,
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "fee_rate": fee_rate,
        "selected_pairs": list(selected_pairs),
        "starting_equity": float(config["starting_equity"]),
        "final_equity": final_equity,
        "net_return": final_equity / float(config["starting_equity"]) - 1.0,
        "maximum_drawdown": _max_drawdown(equity_curve),
        "economic_bars": len(economic),
        "exposed_bars": exposed_bars,
        "exposure_ratio": exposed_bars / len(economic),
        "scheduled_decision_count": len(schedules),
        "scheduled_active_rebalance_count": active_decisions,
        "traded_rebalance_count": traded_decisions,
        "closed_asset_lot_count": len(closed_lots),
        "turnover_contributions": turnover,
        "annualized_one_way_turnover": sum(turnover) / duration_years,
        "equity_curve": equity_curve,
        "equity_returns": _returns(equity_curve),
        "marks": marks,
        "events": events,
        "signals": signals,
        "closed_lots": closed_lots,
        "asset_contributions": asset_contributions,
        "full_weeks": full_weeks,
        "full_week_returns": [item["net_return"] for item in full_weeks],
        "full_week_pnl": [item["net_pnl"] for item in full_weeks],
        "terminal_stub_net_pnl": stub_pnl,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def _target_buy_hold(
    market: pd.DataFrame,
    pairs: Sequence[str],
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    start, end = _ts(window["start"]), _ts(window["end"])
    economic = market.loc[(market.index >= start) & (market.index < end)]
    fee_rate = float(config["cost_rates"][cost_label])
    starting = float(config["starting_equity"])
    weights = {pair: 1.0 / len(pairs) for pair in pairs}
    first = economic.iloc[0]
    solved = solve_post_cost_equity(
        equity_before=starting,
        current_values={pair: 0.0 for pair in pairs},
        target_weights=weights,
        fee_rate=fee_rate,
    )
    quantities = {
        pair: solved["target_values"][pair] / _finite(first[f"{ALIAS[pair]}_open"], "entry open")
        for pair in pairs
    }
    cash = solved["cash"]
    equity = [starting]
    for local_index, (_, row) in enumerate(economic.iterrows()):
        marked = cash + sum(
            quantities[pair] * _finite(row[f"{ALIAS[pair]}_close"], "comparator close")
            for pair in pairs
        )
        if local_index == len(economic) - 1:
            current_values = {
                pair: quantities[pair] * _finite(row[f"{ALIAS[pair]}_close"], "terminal close")
                for pair in pairs
            }
            out = solve_post_cost_equity(
                equity_before=marked,
                current_values=current_values,
                target_weights={},
                fee_rate=fee_rate,
            )
            marked = out["equity_after"]
        equity.append(marked)
    return {
        "schema_version": 1,
        "stage": "C4A",
        "status": "PASS",
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "starting_equity": starting,
        "final_equity": equity[-1],
        "net_return": equity[-1] / starting - 1.0,
        "maximum_drawdown": _max_drawdown(equity),
        "equity_curve": equity,
        "equity_returns": _returns(equity),
        "pairs": list(pairs),
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def simulate_comparator(
    market: pd.DataFrame,
    *,
    selected_pairs: Sequence[str],
    comparator_id: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    if comparator_id not in COMPARATORS:
        raise C4AError("unknown comparator")
    if comparator_id == "cash":
        start, end = _ts(window["start"]), _ts(window["end"])
        bars = len(market.loc[(market.index >= start) & (market.index < end)])
        equity = [float(config["starting_equity"])] * (bars + 1)
        return {
            "schema_version": 1,
            "stage": "C4A",
            "status": "PASS",
            "comparator_id": comparator_id,
            "window_id": str(window["id"]),
            "cost_label": cost_label,
            "starting_equity": equity[0],
            "final_equity": equity[-1],
            "net_return": 0.0,
            "maximum_drawdown": 0.0,
            "equity_curve": equity,
            "equity_returns": [0.0] * bars,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        }
    pairs = {
        "btc_buy_hold": ["BTC/USDT"],
        "top8_equal_weight_buy_hold": list(selected_pairs),
        "btc_eth_sol_equal_weight_buy_hold": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    }[comparator_id]
    result = _target_buy_hold(market, pairs, window, cost_label, config)
    result["comparator_id"] = comparator_id
    return result


def _weekly_stats(weekly_returns: Sequence[float]) -> dict[str, Any]:
    array = np.asarray(weekly_returns, dtype=float)
    if len(array) != 39 or not np.isfinite(array).all():
        raise C4AError("weekly DSR sample mismatch")
    mean_value = float(np.mean(array))
    deviation = float(np.std(array, ddof=1))
    if deviation == 0:
        if mean_value != 0:
            raise C4AError("nonzero weekly mean with zero variance")
        raw_sharpe = 0.0
        skewness = 0.0
        ordinary_kurtosis = 3.0
    else:
        raw_sharpe = mean_value / deviation
        skewness = float(skew(array, bias=False))
        ordinary_kurtosis = float(kurtosis(array, fisher=False, bias=False))
    return {
        "weekly_mean": mean_value,
        "weekly_std": deviation,
        "sr_weekly_raw": raw_sharpe,
        "sr_weekly_annualized": raw_sharpe * math.sqrt(52),
        "skewness": skewness,
        "ordinary_kurtosis": ordinary_kurtosis,
    }


def attach_within_stage_dsr(expected_aggregates: Sequence[dict[str, Any]]) -> None:
    if len(expected_aggregates) != 3 or {row["policy_id"] for row in expected_aggregates} != set(POLICIES):
        raise C4AError("DSR requires exactly three expected-cost policies")
    statistics = {
        row["policy_id"]: _weekly_stats(row["full_week_returns"])
        for row in expected_aggregates
    }
    trial_vector = [statistics[policy]["sr_weekly_raw"] for policy in POLICIES]
    sigma = float(np.std(np.asarray(trial_vector, float), ddof=1))
    if len(set(trial_vector)) == 1:
        sr_star = 0.0
    else:
        count = 3
        sr_star = sigma * (
            (1 - GAMMA) * float(norm.ppf(1 - 1 / count))
            + GAMMA * float(norm.ppf(1 - 1 / (count * math.e)))
        )
    for row in expected_aggregates:
        item = statistics[row["policy_id"]]
        raw_sharpe = item["sr_weekly_raw"]
        radicand = (
            1
            - item["skewness"] * raw_sharpe
            + ((item["ordinary_kurtosis"] - 1) / 4) * raw_sharpe * raw_sharpe
        )
        if not math.isfinite(radicand) or radicand <= 0:
            raise C4AError("invalid DSR denominator")
        if item["weekly_std"] == 0 and item["weekly_mean"] == 0:
            z_score, probability = 0.0, 0.0
        else:
            z_score = (raw_sharpe - sr_star) * math.sqrt(38) / math.sqrt(radicand)
            probability = float(norm.cdf(z_score))
        row.update(
            {
                **item,
                "dsr_trial_policy_order": list(POLICIES),
                "dsr_trial_raw_sharpes": trial_vector,
                "sigma_sr_raw": sigma,
                "sr_star_raw": sr_star,
                "dsr_radicand": radicand,
                "dsr_z_score": z_score,
                "within_stage_dsr_probability": probability,
            }
        )


def aggregate_policy(
    rows: Sequence[Mapping[str, Any]],
    *,
    policy: str,
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    selected = [row for row in rows if row.get("policy_id") == policy and row.get("cost_label") == cost_label]
    by_id = {str(row["window_id"]): row for row in selected}
    ordered = [by_id[window["id"]] for window in config["screen_windows"]]
    window_returns = {row["window_id"]: _finite(row["net_return"], "window return") for row in ordered}
    asset_contributions = {
        pair: sum(float(row["asset_contributions"].get(pair, 0.0)) for row in ordered)
        for pair in ordered[0]["selected_pairs"]
    }
    full_week_pnl = [float(value) for row in ordered for value in row["full_week_pnl"]]
    all_returns = [float(value) for row in ordered for value in row["equity_returns"]]
    total_bars = sum(int(row["economic_bars"]) for row in ordered)
    exposed = sum(int(row["exposed_bars"]) for row in ordered)
    total_turnover = sum(
        sum(float(value) for value in row["turnover_contributions"])
        for row in ordered
    )
    total_duration = sum(
        (_ts(window["end"]) - _ts(window["start"])).total_seconds()
        for window in config["screen_windows"]
    ) / SECONDS_PER_YEAR
    result = {
        "schema_version": 1,
        "stage": "C4A",
        "status": "PASS",
        "policy_id": policy,
        "cost_label": cost_label,
        "window_returns": window_returns,
        "minimum_window_net_return": min(window_returns.values()),
        "median_window_net_return": float(median(window_returns.values())),
        "positive_windows": sum(value > 0 for value in window_returns.values()),
        "aggregate_net_return": math.prod(1 + value for value in window_returns.values()) - 1,
        "aggregate_sharpe": _four_hour_sharpe(all_returns),
        "maximum_window_drawdown": max(float(row["maximum_drawdown"]) for row in ordered),
        "scheduled_active_rebalance_count": sum(
            int(row["scheduled_active_rebalance_count"]) for row in ordered
        ),
        "minimum_window_active_rebalances": min(
            int(row["scheduled_active_rebalance_count"]) for row in ordered
        ),
        "closed_asset_lot_count": sum(int(row["closed_asset_lot_count"]) for row in ordered),
        "exposure_ratio": exposed / total_bars,
        "annualized_one_way_turnover": total_turnover / total_duration,
        "asset_contributions": asset_contributions,
        "positive_asset_count": sum(value > 0 for value in asset_contributions.values()),
        "maximum_asset_positive_pnl_share": _positive_share(asset_contributions.values()),
        "maximum_window_positive_pnl_share": _positive_share(
            [float(row["final_equity"]) - float(config["starting_equity"]) for row in ordered]
        ),
        "maximum_week_positive_pnl_share": _positive_share(full_week_pnl),
        "maximum_top_three_week_positive_pnl_share": _positive_share(full_week_pnl, top=3),
        "full_week_returns": [float(value) for row in ordered for value in row["full_week_returns"]],
        "full_week_pnl": full_week_pnl,
        "window_rows": [dict(row) for row in ordered],
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    if len(result["full_week_returns"]) != 39:
        raise C4AError("aggregate full-week count mismatch")
    return result


def aggregate_comparator(
    rows: Sequence[Mapping[str, Any]],
    comparator_id: str,
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    selected = [
        row
        for row in rows
        if row.get("comparator_id") == comparator_id and row.get("cost_label") == cost_label
    ]
    by_id = {str(row["window_id"]): row for row in selected}
    ordered = [by_id[window["id"]] for window in config["screen_windows"]]
    returns = {row["window_id"]: float(row["net_return"]) for row in ordered}
    return {
        "comparator_id": comparator_id,
        "cost_label": cost_label,
        "window_returns": returns,
        "aggregate_net_return": math.prod(1 + value for value in returns.values()) - 1,
        "maximum_window_drawdown": max(float(row["maximum_drawdown"]) for row in ordered),
        "status": "PASS",
    }


def decide(aggregates: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    validate_config(config)
    gate = config["gate"]
    by_policy = {
        policy: {
            row["cost_label"]: row
            for row in aggregates
            if row.get("policy_id") == policy
        }
        for policy in POLICIES
    }
    eligible: list[Mapping[str, Any]] = []
    decisions: dict[str, Any] = {}
    for policy in POLICIES:
        expected = by_policy[policy].get("1.0x")
        stress = by_policy[policy].get("1.5x")
        if expected is None or stress is None:
            raise C4AError("missing expected/stress aggregate")
        reasons: list[str] = []
        checks = [
            (int(expected["positive_windows"]) < int(gate["minimum_positive_windows"]), "positive_windows"),
            (float(expected["median_window_net_return"]) <= 0, "median_window_return"),
            (float(expected["aggregate_net_return"]) <= 0, "aggregate_expected_return"),
            (float(stress["aggregate_net_return"]) < 0, "aggregate_1_5x_return"),
            (
                expected["aggregate_sharpe"] is None
                or float(expected["aggregate_sharpe"]) < float(gate["minimum_aggregate_sharpe"]),
                "aggregate_sharpe",
            ),
            (
                float(expected["within_stage_dsr_probability"])
                < float(gate["minimum_within_stage_dsr_probability"]),
                "within_stage_dsr",
            ),
            (
                float(expected["maximum_window_drawdown"])
                > float(gate["maximum_window_drawdown_ratio"]),
                "maximum_window_drawdown",
            ),
            (
                int(expected["scheduled_active_rebalance_count"])
                < int(gate["minimum_active_rebalances"]),
                "active_rebalances",
            ),
            (
                int(expected["minimum_window_active_rebalances"])
                < int(gate["minimum_active_rebalances_per_window"]),
                "minimum_window_active_rebalances",
            ),
            (
                int(expected["closed_asset_lot_count"])
                < int(gate["minimum_closed_asset_lots"]),
                "closed_asset_lots",
            ),
            (
                float(expected["annualized_one_way_turnover"])
                > float(gate["maximum_annualized_one_way_turnover"]),
                "turnover",
            ),
            (
                float(expected["exposure_ratio"]) > float(gate["maximum_exposure_ratio"]),
                "exposure",
            ),
            (
                int(expected["positive_asset_count"]) < int(gate["minimum_positive_assets"]),
                "positive_assets",
            ),
        ]
        for failed, reason in checks:
            if failed:
                reasons.append(reason)
        for key, reason in (
            ("maximum_window_positive_pnl_share", "window_concentration"),
            ("maximum_asset_positive_pnl_share", "asset_concentration"),
            ("maximum_week_positive_pnl_share", "week_concentration"),
            ("maximum_top_three_week_positive_pnl_share", "top_three_week_concentration"),
        ):
            value = expected[key]
            threshold = gate[key]
            if value is None or float(value) > float(threshold):
                reasons.append(reason)
        decisions[policy] = {
            "policy_id": policy,
            "eligible": not reasons,
            "rejection_reasons": reasons,
            "expected": dict(expected),
            "stress_1_5x": dict(stress),
        }
        if not reasons:
            eligible.append(expected)
    eligible.sort(
        key=lambda row: (
            -float(row["minimum_window_net_return"]),
            -float(row["within_stage_dsr_probability"]),
            -float(row["median_window_net_return"]),
            -float(by_policy[row["policy_id"]]["1.5x"]["aggregate_net_return"]),
            float(row["maximum_window_drawdown"]),
            float(row["annualized_one_way_turnover"]),
            str(row["policy_id"]),
        )
    )
    selected = eligible[0]["policy_id"] if eligible else None
    return {
        "schema_version": 1,
        "stage": "C4A",
        "economic_result": "SELECTED" if selected else "REJECTED",
        "selected_policy": selected,
        "eligible_ranking": [row["policy_id"] for row in eligible],
        "policy_decisions": decisions,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def run_screen(
    candles_by_pair: Mapping[str, Sequence[Mapping[str, Any]]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    market = prepare_market(candles_by_pair)
    universe = select_universe(market, config)
    selected_pairs = universe["selected_pairs"]
    policy_rows = [
        simulate_window(
            market,
            selected_pairs=selected_pairs,
            policy=policy,
            window=window,
            cost_label=cost,
            config=config,
        )
        for policy in POLICIES
        for window in config["screen_windows"]
        for cost in COST_LABELS
    ]
    comparator_rows = [
        simulate_comparator(
            market,
            selected_pairs=selected_pairs,
            comparator_id=comparator,
            window=window,
            cost_label=cost,
            config=config,
        )
        for comparator in COMPARATORS
        for window in config["screen_windows"]
        for cost in COST_LABELS
    ]
    if len(policy_rows) != 27 or len(comparator_rows) != 36:
        raise C4AError("frozen row count mismatch")
    policy_aggregates = [
        aggregate_policy(policy_rows, policy=policy, cost_label=cost, config=config)
        for policy in POLICIES
        for cost in COST_LABELS
    ]
    expected = [row for row in policy_aggregates if row["cost_label"] == "1.0x"]
    attach_within_stage_dsr(expected)
    comparator_aggregates = [
        aggregate_comparator(comparator_rows, comparator, cost, config)
        for comparator in COMPARATORS
        for cost in COST_LABELS
    ]
    decision = decide(policy_aggregates, config)
    return {
        "schema_version": 1,
        "stage": "C4A",
        "status": "PASS",
        "universe": universe,
        "policy_rows": policy_rows,
        "comparator_rows": comparator_rows,
        "policy_aggregates": policy_aggregates,
        "comparator_aggregates": comparator_aggregates,
        "decision": decision,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
