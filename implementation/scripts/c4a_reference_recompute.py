#!/usr/bin/env python3
"""Independent plain-array recomputation for the frozen C4A screen.

The production C4A engine is intentionally not imported here.  This module
reconstructs universe selection, weekly signals, post-cost portfolio accounting,
comparators, aggregate metrics, within-stage DSR, gates, and ranking from retained
primitive candles.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np
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
EXPECTED_CONFIG_CANONICAL_SHA256 = "14e7b96d1167afad6b23c1bc6302e7f9b86ad291f956944ba8f546908402fa92"
STEP = timedelta(hours=4)
START = datetime(2023, 9, 1, tzinfo=UTC)
BOUNDARY = datetime(2024, 10, 1, tzinfo=UTC)
ANNUAL_FOUR_HOUR_BARS = 6 * 365
SECONDS_PER_YEAR = 365 * 24 * 60 * 60
GAMMA = 0.5772156649015329


class C4AReferenceError(RuntimeError):
    pass


def _finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise C4AReferenceError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C4AReferenceError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise C4AReferenceError(f"{label} must be finite")
    return result


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        raw = float(value)
        parsed = datetime.fromtimestamp(raw / (1000 if raw > 10_000_000_000 else 1), tz=UTC)
    else:
        raise C4AReferenceError(f"invalid timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def verify_config(config: Mapping[str, Any]) -> None:
    digest = hashlib.sha256(
        json.dumps(config, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if digest != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C4AReferenceError(
            f"retained C4A semantic configuration drift: {digest}"
        )
    if config.get("stage") != "C4A" or config.get("confirmation_opened") is not False:
        raise C4AReferenceError("C4A identity or confirmation state drift")
    if config.get("holdout_state") != "HOLDOUT_CLOSED" or config.get("live") != "FORBIDDEN":
        raise C4AReferenceError("C4A safety state drift")


@dataclass(frozen=True)
class ReferenceMarket:
    timestamps: tuple[datetime, ...]
    opens: Mapping[str, np.ndarray]
    highs: Mapping[str, np.ndarray]
    lows: Mapping[str, np.ndarray]
    closes: Mapping[str, np.ndarray]
    volumes: Mapping[str, np.ndarray]


def reference_prepare_market(
    candles: Mapping[str, Sequence[Mapping[str, Any]]],
) -> ReferenceMarket:
    if set(candles) != set(CANDIDATE_PAIRS):
        raise C4AReferenceError("reference candidate pair set mismatch")
    expected_count = int((BOUNDARY - START) / STEP)
    expected_timestamps = tuple(START + index * STEP for index in range(expected_count))
    opens: dict[str, np.ndarray] = {}
    highs: dict[str, np.ndarray] = {}
    lows: dict[str, np.ndarray] = {}
    closes: dict[str, np.ndarray] = {}
    volumes: dict[str, np.ndarray] = {}
    for pair in CANDIDATE_PAIRS:
        rows = candles[pair]
        timestamps = tuple(_timestamp(row.get("date")) for row in rows)
        if timestamps != expected_timestamps:
            raise C4AReferenceError(f"reference timestamp mismatch for {pair}")
        arrays = {
            "open": np.asarray([_finite(row.get("open"), f"{pair} open") for row in rows]),
            "high": np.asarray([_finite(row.get("high"), f"{pair} high") for row in rows]),
            "low": np.asarray([_finite(row.get("low"), f"{pair} low") for row in rows]),
            "close": np.asarray([_finite(row.get("close"), f"{pair} close") for row in rows]),
            "volume": np.asarray([_finite(row.get("volume"), f"{pair} volume") for row in rows]),
        }
        if any(len(value) != expected_count or not np.isfinite(value).all() for value in arrays.values()):
            raise C4AReferenceError(f"reference non-finite or count mismatch for {pair}")
        if any(np.any(value <= 0) for value in arrays.values()):
            raise C4AReferenceError(f"reference non-positive OHLCV for {pair}")
        invalid = (
            (arrays["low"] > arrays["high"])
            | (arrays["open"] < arrays["low"])
            | (arrays["open"] > arrays["high"])
            | (arrays["close"] < arrays["low"])
            | (arrays["close"] > arrays["high"])
        )
        if np.any(invalid):
            raise C4AReferenceError(f"reference invalid OHLC geometry for {pair}")
        opens[pair], highs[pair], lows[pair] = arrays["open"], arrays["high"], arrays["low"]
        closes[pair], volumes[pair] = arrays["close"], arrays["volume"]
    return ReferenceMarket(expected_timestamps, opens, highs, lows, closes, volumes)


def reference_select_universe(
    market: ReferenceMarket,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    verify_config(config)
    formation_end = _timestamp(config["formation_end"])
    formation_indices = [index for index, stamp in enumerate(market.timestamps) if START <= stamp < formation_end]
    if len(formation_indices) != 732:
        raise C4AReferenceError("reference formation row count mismatch")
    candidates: list[dict[str, Any]] = []
    for pair in CANDIDATE_PAIRS:
        values = market.closes[pair][formation_indices] * market.volumes[pair][formation_indices]
        score = float(np.median(values))
        if not math.isfinite(score):
            raise C4AReferenceError(f"reference liquidity score invalid for {pair}")
        candidates.append({"pair": pair, "liquidity_score": score})
    candidates.sort(key=lambda item: (-item["liquidity_score"], item["pair"]))
    for rank, item in enumerate(candidates, start=1):
        item["rank"] = rank
        item["selected"] = rank <= 8
    selected = [item["pair"] for item in candidates if item["selected"]]
    return {
        "schema_version": 1,
        "stage": "C4A",
        "status": "PASS",
        "formation_rows": 732,
        "candidates": candidates,
        "selected_pairs": selected,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def _ordinal_rank(values: Mapping[str, float]) -> dict[str, int]:
    ordered = sorted(values, key=lambda pair: (-values[pair], pair))
    return {pair: len(ordered) - index for index, pair in enumerate(ordered)}


def reference_signal(
    market: ReferenceMarket,
    *,
    execution_index: int,
    selected_pairs: Sequence[str],
    policy: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    signal_index = execution_index - 1
    lookback = int(config["weekly_lookback_intervals"])
    if signal_index - lookback < 0:
        raise C4AReferenceError("reference insufficient weekly startup")
    signal_time = market.timestamps[signal_index]
    if signal_time.weekday() != 6 or signal_time.hour != 20:
        raise C4AReferenceError("reference signal is not Sunday 20 UTC")
    weekly: dict[str, float] = {}
    proximity: dict[str, float] = {}
    for pair in selected_pairs:
        close_now = float(market.closes[pair][signal_index])
        weekly[pair] = close_now / float(market.closes[pair][signal_index - lookback]) - 1.0
        sample = market.highs[pair][signal_index - 41 : signal_index + 1]
        if len(sample) != 42:
            raise C4AReferenceError("reference high-proximity count mismatch")
        proximity[pair] = close_now / float(np.max(sample))
    return_rank = _ordinal_rank(weekly)
    proximity_rank = _ordinal_rank(proximity)
    composite = {pair: (return_rank[pair] + proximity_rank[pair]) / 2.0 for pair in selected_pairs}
    positive = [pair for pair in selected_pairs if weekly[pair] > 0]
    breadth = len(positive) / 8.0
    risk_on = breadth >= float(config["minimum_breadth"]) and len(positive) >= 2
    chosen: list[str] = []
    if risk_on:
        if policy == POLICIES[0]:
            chosen = sorted(positive, key=lambda pair: (-weekly[pair], pair))[:2]
        elif policy == POLICIES[1]:
            chosen = sorted(positive, key=lambda pair: (-proximity[pair], pair))[:2]
        elif policy == POLICIES[2]:
            chosen = sorted(
                positive,
                key=lambda pair: (-composite[pair], -weekly[pair], -proximity[pair], pair),
            )[:2]
        else:
            raise C4AReferenceError(f"unknown reference policy: {policy}")
    rows = [
        {
            "pair": pair,
            "weekly_return": weekly[pair],
            "high_proximity": proximity[pair],
            "weekly_return_rank": return_rank[pair],
            "high_proximity_rank": proximity_rank[pair],
            "composite_score": composite[pair],
            "positive": weekly[pair] > 0,
            "selected_target": pair in chosen,
        }
        for pair in selected_pairs
    ]
    return {
        "execution_time": market.timestamps[execution_index].isoformat(),
        "signal_time": signal_time.isoformat(),
        "policy_id": policy,
        "breadth": breadth,
        "risk_on": risk_on,
        "chosen_pairs": chosen,
        "target_weights": {pair: float(config["target_weight_per_asset"]) for pair in chosen},
        "rows": rows,
    }


def reference_solve_post_cost(
    equity_before: float,
    current_values: Mapping[str, float],
    target_weights: Mapping[str, float],
    fee_rate: float,
) -> dict[str, Any]:
    keys = sorted(set(current_values) | set(target_weights))
    before = {key: _finite(current_values.get(key, 0.0), f"current {key}") for key in keys}
    weights = {key: _finite(target_weights.get(key, 0.0), f"weight {key}") for key in keys}
    equity_before = _finite(equity_before, "equity before")
    fee_rate = _finite(fee_rate, "fee rate")
    if equity_before <= 0 or fee_rate < 0 or any(value < 0 for value in before.values()):
        raise C4AReferenceError("reference invalid post-cost inputs")

    def equation(value: float) -> float:
        return value + fee_rate * sum(abs(weights[key] * value - before[key]) for key in keys) - equity_before

    lo, hi = 0.0, equity_before
    if equation(lo) > 1e-12 or equation(hi) < -1e-12:
        raise C4AReferenceError("reference post-cost root not bracketed")
    midpoint = hi
    iterations = 0
    for iterations in range(1, 201):
        midpoint = (lo + hi) / 2
        residual = equation(midpoint)
        if abs(residual) <= 1e-12 or hi - lo <= 1e-12:
            break
        if residual > 0:
            hi = midpoint
        else:
            lo = midpoint
    else:
        raise C4AReferenceError("reference post-cost root did not converge")
    target = {key: weights[key] * midpoint for key in keys}
    delta = {key: target[key] - before[key] for key in keys}
    fees = {key: fee_rate * abs(delta[key]) for key in keys}
    cash = midpoint - sum(target.values())
    if cash < -1e-12 or abs(equity_before - sum(fees.values()) - midpoint) > 1e-9:
        raise C4AReferenceError("reference post-cost identity mismatch")
    return {
        "equity_after": midpoint,
        "target_values": target,
        "trade_deltas": delta,
        "fees": fees,
        "total_fee": sum(fees.values()),
        "cash": max(0.0, cash),
        "iterations": iterations,
    }


def _drawdown(values: Sequence[float]) -> float:
    peak = -math.inf
    result = 0.0
    for value in values:
        current = _finite(value, "reference equity")
        peak = max(peak, current)
        result = max(result, 1.0 - current / peak)
    return result


def _returns(values: Sequence[float]) -> list[float]:
    return [float(values[index]) / float(values[index - 1]) - 1.0 for index in range(1, len(values))]


def _positive_share(values: Sequence[float], top: int = 1) -> float | None:
    positive = sorted((float(value) for value in values if float(value) > 0), reverse=True)
    total = sum(positive)
    return None if total <= 0 else sum(positive[:top]) / total


def reference_simulate_window(
    market: ReferenceMarket,
    *,
    selected_pairs: Sequence[str],
    policy: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    start, end = _timestamp(window["start"]), _timestamp(window["end"])
    indices = [index for index, stamp in enumerate(market.timestamps) if start <= stamp < end]
    expected_count = int((end - start) / STEP)
    if len(indices) != expected_count:
        raise C4AReferenceError("reference economic window count mismatch")
    scheduled = [index for index in indices if market.timestamps[index].weekday() == 0 and market.timestamps[index].hour == 0]
    if len(scheduled) != {"S1": 13, "S2": 13, "S3": 14}[str(window["id"])]:
        raise C4AReferenceError("reference schedule count mismatch")
    scheduled_set = set(scheduled)
    fee_rate = float(config["cost_rates"][cost_label])
    starting = float(config["starting_equity"])
    cash = starting
    quantities = {pair: 0.0 for pair in selected_pairs}
    active_lots = {pair: False for pair in selected_pairs}
    closed_lots = 0
    contribution = {pair: 0.0 for pair in selected_pairs}
    equity = [starting]
    four_hour_returns: list[float] = []
    full_week_returns: list[float] = []
    full_week_pnl: list[float] = []
    decisions: list[dict[str, Any]] = []
    turnover: list[float] = []
    exposed_bars = 0
    active_decisions = 0
    traded_decisions = 0
    previous_close: dict[str, float] | None = None
    previous_equity = starting
    week_start: float | None = None
    stub_start: float | None = None

    for local_index, index in enumerate(indices):
        timestamp = market.timestamps[index]
        final = local_index == len(indices) - 1
        open_prices = {pair: float(market.opens[pair][index]) for pair in selected_pairs}
        close_prices = {pair: float(market.closes[pair][index]) for pair in selected_pairs}
        boundary_gap = 0.0
        if previous_close is not None:
            for pair in selected_pairs:
                pnl = quantities[pair] * (open_prices[pair] - previous_close[pair])
                contribution[pair] += pnl
                boundary_gap += pnl
        open_equity = cash + sum(quantities[pair] * open_prices[pair] for pair in selected_pairs)
        forced_stub = str(window["id"]) == "S3" and timestamp == datetime(2024, 9, 30, tzinfo=UTC)
        if index in scheduled_set:
            if forced_stub:
                stub_start = previous_equity
                target_weights: dict[str, float] = {}
                snapshot = {
                    "execution_time": timestamp.isoformat(),
                    "signal_time": (timestamp - STEP).isoformat(),
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
                    raise C4AReferenceError("reference prior week not closed")
                week_start = previous_equity
                snapshot = reference_signal(
                    market,
                    execution_index=index,
                    selected_pairs=selected_pairs,
                    policy=policy,
                    config=config,
                )
                target_weights = dict(snapshot["target_weights"])
            decisions.append(snapshot)
            if target_weights:
                active_decisions += 1
            current_values = {pair: quantities[pair] * open_prices[pair] for pair in selected_pairs}
            solved = reference_solve_post_cost(open_equity, current_values, target_weights, fee_rate)
            before_quantities = dict(quantities)
            for pair in selected_pairs:
                contribution[pair] -= solved["fees"][pair]
                target_value = solved["target_values"][pair]
                after = target_value / open_prices[pair] if target_value > 0 else 0.0
                if before_quantities[pair] == 0 and after > 0:
                    active_lots[pair] = True
                elif before_quantities[pair] > 0 and after == 0:
                    if not active_lots[pair]:
                        raise C4AReferenceError("reference lot close without active lot")
                    active_lots[pair] = False
                    closed_lots += 1
                quantities[pair] = after
            cash = solved["cash"]
            traded_notional = sum(abs(value) for value in solved["trade_deltas"].values())
            if traded_notional > 0:
                traded_decisions += 1
            turnover.append(traded_notional / open_equity)
        if any(quantity > 0 for quantity in quantities.values()):
            exposed_bars += 1
        for pair in selected_pairs:
            contribution[pair] += quantities[pair] * (close_prices[pair] - open_prices[pair])
        close_equity = cash + sum(quantities[pair] * close_prices[pair] for pair in selected_pairs)
        if final and any(quantity > 0 for quantity in quantities.values()):
            current_values = {pair: quantities[pair] * close_prices[pair] for pair in selected_pairs}
            solved = reference_solve_post_cost(close_equity, current_values, {}, fee_rate)
            before = dict(quantities)
            for pair in selected_pairs:
                contribution[pair] -= solved["fees"][pair]
                if before[pair] > 0:
                    quantities[pair] = 0.0
                    if not active_lots[pair]:
                        raise C4AReferenceError("reference terminal lot state mismatch")
                    active_lots[pair] = False
                    closed_lots += 1
            turnover.append(sum(abs(value) for value in solved["trade_deltas"].values()) / close_equity)
            cash = solved["cash"]
            close_equity = cash
        four_hour_returns.append(close_equity / equity[-1] - 1.0)
        equity.append(close_equity)
        if timestamp.weekday() == 6 and timestamp.hour == 20 and week_start is not None:
            full_week_returns.append(close_equity / week_start - 1.0)
            full_week_pnl.append(close_equity - week_start)
            week_start = None
        previous_close = close_prices
        previous_equity = close_equity
    if any(active_lots.values()) or any(value != 0 for value in quantities.values()) or week_start is not None:
        raise C4AReferenceError("reference window did not terminate cleanly")
    if len(full_week_returns) != 13:
        raise C4AReferenceError("reference full-week count mismatch")
    final_equity = equity[-1]
    if abs(sum(contribution.values()) - (final_equity - starting)) > 1e-8:
        raise C4AReferenceError("reference asset contribution mismatch")
    stub_pnl = 0.0 if stub_start is None else final_equity - stub_start
    if abs(sum(full_week_pnl) + stub_pnl - (final_equity - starting)) > 1e-8:
        raise C4AReferenceError("reference week/stub reconciliation mismatch")
    duration_years = (end - start).total_seconds() / SECONDS_PER_YEAR
    return {
        "policy_id": policy,
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "starting_equity": starting,
        "final_equity": final_equity,
        "net_return": final_equity / starting - 1.0,
        "maximum_drawdown": _drawdown(equity),
        "economic_bars": len(indices),
        "exposed_bars": exposed_bars,
        "exposure_ratio": exposed_bars / len(indices),
        "scheduled_decision_count": len(scheduled),
        "scheduled_active_rebalance_count": active_decisions,
        "traded_rebalance_count": traded_decisions,
        "closed_asset_lot_count": closed_lots,
        "turnover_contributions": turnover,
        "annualized_one_way_turnover": sum(turnover) / duration_years,
        "equity_returns": four_hour_returns,
        "asset_contributions": contribution,
        "full_week_returns": full_week_returns,
        "full_week_pnl": full_week_pnl,
        "terminal_stub_net_pnl": stub_pnl,
        "decisions": decisions,
    }


def reference_simulate_comparator(
    market: ReferenceMarket,
    *,
    selected_pairs: Sequence[str],
    comparator_id: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    start, end = _timestamp(window["start"]), _timestamp(window["end"])
    indices = [index for index, stamp in enumerate(market.timestamps) if start <= stamp < end]
    starting = float(config["starting_equity"])
    if comparator_id == "cash":
        return {
            "comparator_id": comparator_id,
            "window_id": str(window["id"]),
            "cost_label": cost_label,
            "final_equity": starting,
            "net_return": 0.0,
            "maximum_drawdown": 0.0,
            "equity_returns": [0.0] * len(indices),
        }
    pairs = {
        "btc_buy_hold": ["BTC/USDT"],
        "top8_equal_weight_buy_hold": list(selected_pairs),
        "btc_eth_sol_equal_weight_buy_hold": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    }.get(comparator_id)
    if pairs is None:
        raise C4AReferenceError("unknown reference comparator")
    fee_rate = float(config["cost_rates"][cost_label])
    weights = {pair: 1 / len(pairs) for pair in pairs}
    first = indices[0]
    solved = reference_solve_post_cost(
        starting,
        {pair: 0.0 for pair in pairs},
        weights,
        fee_rate,
    )
    quantities = {
        pair: solved["target_values"][pair] / float(market.opens[pair][first])
        for pair in pairs
    }
    cash = solved["cash"]
    equity = [starting]
    for local_index, index in enumerate(indices):
        marked = cash + sum(quantities[pair] * float(market.closes[pair][index]) for pair in pairs)
        if local_index == len(indices) - 1:
            solved_out = reference_solve_post_cost(
                marked,
                {pair: quantities[pair] * float(market.closes[pair][index]) for pair in pairs},
                {},
                fee_rate,
            )
            marked = solved_out["equity_after"]
        equity.append(marked)
    return {
        "comparator_id": comparator_id,
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "final_equity": equity[-1],
        "net_return": equity[-1] / starting - 1.0,
        "maximum_drawdown": _drawdown(equity),
        "equity_returns": _returns(equity),
    }


def _sharpe(values: Sequence[float]) -> float | None:
    array = np.asarray(values, dtype=float)
    if len(array) < 2 or not np.isfinite(array).all():
        return None
    deviation = float(np.std(array, ddof=1))
    mean_value = float(np.mean(array))
    if deviation == 0:
        if mean_value == 0:
            return 0.0
        raise C4AReferenceError("reference nonzero mean with zero variance")
    return mean_value / deviation * math.sqrt(ANNUAL_FOUR_HOUR_BARS)


def reference_aggregate_policy(
    rows: Sequence[Mapping[str, Any]],
    *,
    policy: str,
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    selected = [row for row in rows if row["policy_id"] == policy and row["cost_label"] == cost_label]
    by_window = {row["window_id"]: row for row in selected}
    ordered = [by_window[window["id"]] for window in config["screen_windows"]]
    window_returns = {row["window_id"]: float(row["net_return"]) for row in ordered}
    window_pnl = [float(row["final_equity"]) - float(config["starting_equity"]) for row in ordered]
    assets = ordered[0]["asset_contributions"].keys()
    asset_pnl = {pair: sum(float(row["asset_contributions"][pair]) for row in ordered) for pair in assets}
    week_pnl = [float(value) for row in ordered for value in row["full_week_pnl"]]
    week_returns = [float(value) for row in ordered for value in row["full_week_returns"]]
    returns = [float(value) for row in ordered for value in row["equity_returns"]]
    total_bars = sum(int(row["economic_bars"]) for row in ordered)
    duration = sum(
        (_timestamp(window["end"]) - _timestamp(window["start"])).total_seconds()
        for window in config["screen_windows"]
    ) / SECONDS_PER_YEAR
    return {
        "policy_id": policy,
        "cost_label": cost_label,
        "window_returns": window_returns,
        "minimum_window_net_return": min(window_returns.values()),
        "median_window_net_return": float(median(window_returns.values())),
        "positive_windows": sum(value > 0 for value in window_returns.values()),
        "aggregate_net_return": math.prod(1 + value for value in window_returns.values()) - 1.0,
        "aggregate_sharpe": _sharpe(returns),
        "maximum_window_drawdown": max(float(row["maximum_drawdown"]) for row in ordered),
        "scheduled_active_rebalance_count": sum(int(row["scheduled_active_rebalance_count"]) for row in ordered),
        "minimum_window_active_rebalances": min(int(row["scheduled_active_rebalance_count"]) for row in ordered),
        "closed_asset_lot_count": sum(int(row["closed_asset_lot_count"]) for row in ordered),
        "exposure_ratio": sum(int(row["exposed_bars"]) for row in ordered) / total_bars,
        "annualized_one_way_turnover": sum(
            sum(float(value) for value in row["turnover_contributions"]) for row in ordered
        ) / duration,
        "asset_contributions": asset_pnl,
        "positive_asset_count": sum(value > 0 for value in asset_pnl.values()),
        "maximum_asset_positive_pnl_share": _positive_share(list(asset_pnl.values())),
        "maximum_window_positive_pnl_share": _positive_share(window_pnl),
        "maximum_week_positive_pnl_share": _positive_share(week_pnl),
        "maximum_top_three_week_positive_pnl_share": _positive_share(week_pnl, top=3),
        "full_week_returns": week_returns,
        "full_week_pnl": week_pnl,
        "window_net_pnl": sum(window_pnl),
        "week_and_stub_net_pnl": sum(week_pnl) + sum(float(row["terminal_stub_net_pnl"]) for row in ordered),
    }


def reference_attach_dsr(expected: Sequence[dict[str, Any]]) -> None:
    if len(expected) != 3:
        raise C4AReferenceError("reference DSR requires three policies")
    stats: dict[str, dict[str, float]] = {}
    for row in expected:
        values = np.asarray(row["full_week_returns"], dtype=float)
        if len(values) != 39 or not np.isfinite(values).all():
            raise C4AReferenceError("reference DSR observation mismatch")
        mean_value = float(np.mean(values))
        deviation = float(np.std(values, ddof=1))
        if deviation == 0:
            if mean_value != 0:
                raise C4AReferenceError("reference DSR zero variance mismatch")
            raw, skewness, ordinary = 0.0, 0.0, 3.0
        else:
            raw = mean_value / deviation
            skewness = float(skew(values, bias=False))
            ordinary = float(kurtosis(values, fisher=False, bias=False))
        stats[row["policy_id"]] = {
            "weekly_mean": mean_value,
            "weekly_std": deviation,
            "sr_weekly_raw": raw,
            "sr_weekly_annualized": raw * math.sqrt(52),
            "skewness": skewness,
            "ordinary_kurtosis": ordinary,
        }
    vector = [stats[policy]["sr_weekly_raw"] for policy in POLICIES]
    sigma = float(np.std(np.asarray(vector), ddof=1))
    sr_star = 0.0 if len(set(vector)) == 1 else sigma * (
        (1 - GAMMA) * float(norm.ppf(1 - 1 / 3))
        + GAMMA * float(norm.ppf(1 - 1 / (3 * math.e)))
    )
    for row in expected:
        item = stats[row["policy_id"]]
        raw = item["sr_weekly_raw"]
        radicand = 1 - item["skewness"] * raw + ((item["ordinary_kurtosis"] - 1) / 4) * raw * raw
        if not math.isfinite(radicand) or radicand <= 0:
            raise C4AReferenceError("reference DSR radicand invalid")
        if item["weekly_std"] == 0 and item["weekly_mean"] == 0:
            z_score, probability = 0.0, 0.0
        else:
            z_score = (raw - sr_star) * math.sqrt(38) / math.sqrt(radicand)
            probability = float(norm.cdf(z_score))
        row.update(
            {
                **item,
                "dsr_trial_policy_order": list(POLICIES),
                "dsr_trial_raw_sharpes": vector,
                "sigma_sr_raw": sigma,
                "sr_star_raw": sr_star,
                "dsr_radicand": radicand,
                "dsr_z_score": z_score,
                "within_stage_dsr_probability": probability,
            }
        )


def reference_aggregate_comparator(
    rows: Sequence[Mapping[str, Any]],
    comparator_id: str,
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    selected = [
        row for row in rows
        if row["comparator_id"] == comparator_id and row["cost_label"] == cost_label
    ]
    by_window = {row["window_id"]: row for row in selected}
    ordered = [by_window[window["id"]] for window in config["screen_windows"]]
    returns = {row["window_id"]: float(row["net_return"]) for row in ordered}
    return {
        "comparator_id": comparator_id,
        "cost_label": cost_label,
        "window_returns": returns,
        "aggregate_net_return": math.prod(1 + value for value in returns.values()) - 1.0,
        "maximum_window_drawdown": max(float(row["maximum_drawdown"]) for row in ordered),
        "status": "PASS",
    }


def reference_decide(aggregates: Sequence[Mapping[str, Any]], config: Mapping[str, Any]) -> dict[str, Any]:
    gate = config["gate"]
    by_policy = {
        policy: {row["cost_label"]: row for row in aggregates if row["policy_id"] == policy}
        for policy in POLICIES
    }
    decisions: dict[str, Any] = {}
    eligible: list[Mapping[str, Any]] = []
    for policy in POLICIES:
        expected = by_policy[policy]["1.0x"]
        stress = by_policy[policy]["1.5x"]
        reasons: list[str] = []
        checks = [
            (int(expected["positive_windows"]) < int(gate["minimum_positive_windows"]), "positive_windows"),
            (float(expected["median_window_net_return"]) <= 0, "median_window_return"),
            (float(expected["aggregate_net_return"]) <= 0, "aggregate_expected_return"),
            (float(stress["aggregate_net_return"]) < 0, "aggregate_1_5x_return"),
            (expected["aggregate_sharpe"] is None or float(expected["aggregate_sharpe"]) < float(gate["minimum_aggregate_sharpe"]), "aggregate_sharpe"),
            (float(expected["within_stage_dsr_probability"]) < float(gate["minimum_within_stage_dsr_probability"]), "within_stage_dsr"),
            (float(expected["maximum_window_drawdown"]) > float(gate["maximum_window_drawdown_ratio"]), "maximum_window_drawdown"),
            (int(expected["scheduled_active_rebalance_count"]) < int(gate["minimum_active_rebalances"]), "active_rebalances"),
            (int(expected["minimum_window_active_rebalances"]) < int(gate["minimum_active_rebalances_per_window"]), "minimum_window_active_rebalances"),
            (int(expected["closed_asset_lot_count"]) < int(gate["minimum_closed_asset_lots"]), "closed_asset_lots"),
            (float(expected["annualized_one_way_turnover"]) > float(gate["maximum_annualized_one_way_turnover"]), "turnover"),
            (float(expected["exposure_ratio"]) > float(gate["maximum_exposure_ratio"]), "exposure"),
            (int(expected["positive_asset_count"]) < int(gate["minimum_positive_assets"]), "positive_assets"),
        ]
        reasons.extend(reason for failed, reason in checks if failed)
        for key, reason in (
            ("maximum_window_positive_pnl_share", "window_concentration"),
            ("maximum_asset_positive_pnl_share", "asset_concentration"),
            ("maximum_week_positive_pnl_share", "week_concentration"),
            ("maximum_top_three_week_positive_pnl_share", "top_three_week_concentration"),
        ):
            value = expected[key]
            if value is None or float(value) > float(gate[key]):
                reasons.append(reason)
        decisions[policy] = {
            "policy_id": policy,
            "eligible": not reasons,
            "rejection_reasons": reasons,
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
        "economic_result": "SELECTED" if selected else "REJECTED",
        "selected_policy": selected,
        "eligible_ranking": [row["policy_id"] for row in eligible],
        "policy_decisions": decisions,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def reference_run_screen(
    candles: Mapping[str, Sequence[Mapping[str, Any]]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    verify_config(config)
    market = reference_prepare_market(candles)
    universe = reference_select_universe(market, config)
    selected = universe["selected_pairs"]
    policy_rows = [
        reference_simulate_window(
            market,
            selected_pairs=selected,
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
        reference_simulate_comparator(
            market,
            selected_pairs=selected,
            comparator_id=comparator,
            window=window,
            cost_label=cost,
            config=config,
        )
        for comparator in COMPARATORS
        for window in config["screen_windows"]
        for cost in COST_LABELS
    ]
    aggregates = [
        reference_aggregate_policy(policy_rows, policy=policy, cost_label=cost, config=config)
        for policy in POLICIES
        for cost in COST_LABELS
    ]
    reference_attach_dsr([row for row in aggregates if row["cost_label"] == "1.0x"])
    comparator_aggregates = [
        reference_aggregate_comparator(comparator_rows, comparator, cost, config)
        for comparator in COMPARATORS
        for cost in COST_LABELS
    ]
    return {
        "universe": universe,
        "policy_rows": policy_rows,
        "comparator_rows": comparator_rows,
        "policy_aggregates": aggregates,
        "comparator_aggregates": comparator_aggregates,
        "decision": reference_decide(aggregates, config),
    }
