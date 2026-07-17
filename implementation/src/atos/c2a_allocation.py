"""Deterministic C2A low-turnover portfolio allocation research engine."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import median
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


POLICIES = (
    "C2AEqualWeightRiskOn",
    "C2AInverseVolRiskOn",
    "C2ATopTwoPersistentMomentum",
)
PAIR_ORDER = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
COST_LABELS = ("1.0x", "1.5x", "2.0x")
EPSILON = 1e-9


class C2AAllocationError(RuntimeError):
    """Raised when C2A accounting or a frozen contract invariant fails."""


def _finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise C2AAllocationError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C2AAllocationError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise C2AAllocationError(f"{label} must be finite")
    return result


def _iso(value: Any) -> pd.Timestamp:
    try:
        parsed = pd.Timestamp(value)
    except Exception as exc:  # pragma: no cover - pandas exception type varies
        raise C2AAllocationError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize(UTC)
    else:
        parsed = parsed.tz_convert(UTC)
    return parsed


def validate_config(config: Mapping[str, Any]) -> None:
    if config.get("schema_version") != 1 or config.get("stage") != "C2A":
        raise C2AAllocationError("C2A config identity drift")
    if config.get("live") != "FORBIDDEN" or config.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C2AAllocationError("C2A safety state drift")
    if config.get("confirmation_opened") is not False:
        raise C2AAllocationError("C2A confirmation must remain closed")
    if config.get("pairs") != list(PAIR_ORDER):
        raise C2AAllocationError("C2A pair universe drift")
    if config.get("policies") != list(POLICIES):
        raise C2AAllocationError("C2A policy set drift")
    if config.get("timeframe") != "1d":
        raise C2AAllocationError("C2A timeframe drift")
    if config.get("download_timerange") != "20230501-20241001":
        raise C2AAllocationError("C2A download timerange drift")
    if config.get("economic_boundary_exclusive") != "2024-10-01T00:00:00Z":
        raise C2AAllocationError("C2A boundary drift")
    if int(config.get("startup_history_candles", 0)) != 220:
        raise C2AAllocationError("C2A startup coverage drift")
    if list(config.get("cost_rates", {}).keys()) != list(COST_LABELS):
        raise C2AAllocationError("C2A cost labels drift")
    rates = [_finite(config["cost_rates"][label], f"cost {label}") for label in COST_LABELS]
    if rates != [0.0015, 0.00225, 0.003]:
        raise C2AAllocationError("C2A cost rates drift")
    windows = config.get("screen_windows")
    expected_windows = [
        {"id": "S1", "start": "2024-01-01", "end": "2024-04-01"},
        {"id": "S2", "start": "2024-04-01", "end": "2024-07-01"},
        {"id": "S3", "start": "2024-07-01", "end": "2024-10-01"},
    ]
    if windows != expected_windows:
        raise C2AAllocationError("C2A screen window drift")


def prepare_market(candles_by_pair: Mapping[str, Sequence[Mapping[str, Any]]]) -> pd.DataFrame:
    """Create one exact aligned daily open/close frame for the frozen pair universe."""
    if set(candles_by_pair) != set(PAIR_ORDER):
        raise C2AAllocationError("market data pair set mismatch")
    frames: list[pd.DataFrame] = []
    for pair in PAIR_ORDER:
        rows = candles_by_pair[pair]
        if not rows:
            raise C2AAllocationError(f"no candles for {pair}")
        frame = pd.DataFrame([dict(row) for row in rows])
        required = {"date", "open", "close"}
        if not required.issubset(frame.columns):
            raise C2AAllocationError(f"{pair} missing candle columns")
        frame = frame.loc[:, ["date", "open", "close"]].copy()
        frame["date"] = pd.to_datetime(frame["date"], utc=True, errors="raise")
        if frame["date"].duplicated().any():
            raise C2AAllocationError(f"duplicate candle for {pair}")
        frame = frame.sort_values("date").set_index("date")
        for field in ("open", "close"):
            frame[field] = pd.to_numeric(frame[field], errors="raise").astype(float)
            if not np.isfinite(frame[field]).all() or (frame[field] <= 0).any():
                raise C2AAllocationError(f"invalid {field} prices for {pair}")
        frame.columns = pd.MultiIndex.from_product([[pair], ["open", "close"]])
        frames.append(frame)
    market = pd.concat(frames, axis=1, join="inner").sort_index()
    if market.empty or market.isna().any().any():
        raise C2AAllocationError("aligned market data is empty or incomplete")
    expected_columns = pd.MultiIndex.from_product([PAIR_ORDER, ("open", "close")])
    market = market.reindex(columns=expected_columns)
    if not market.index.is_monotonic_increasing:
        raise C2AAllocationError("market index is not sorted")
    return market


def _lookback_return(closes: pd.Series, days: int) -> float:
    if len(closes) < days + 1:
        raise C2AAllocationError(f"insufficient history for {days}-day return")
    return float(closes.iloc[-1] / closes.iloc[-(days + 1)] - 1.0)


def _targets(policy: str, history: pd.DataFrame, config: Mapping[str, Any]) -> dict[str, float]:
    if policy not in POLICIES:
        raise C2AAllocationError(f"unknown C2A policy: {policy}")
    signals = config["signals"]
    short_days = int(signals["momentum_short_days"])
    long_days = int(signals["momentum_long_days"])
    sma_days = int(signals["btc_sma_days"])
    vol_days = int(signals["volatility_days"])
    closes = {pair: history[(pair, "close")].astype(float) for pair in PAIR_ORDER}
    short_returns = {pair: _lookback_return(closes[pair], short_days) for pair in PAIR_ORDER}

    if policy in ("C2AEqualWeightRiskOn", "C2AInverseVolRiskOn"):
        btc = closes["BTC/USDT"]
        if len(btc) < sma_days:
            raise C2AAllocationError("insufficient BTC SMA history")
        risk_on = float(btc.iloc[-1]) > float(btc.iloc[-sma_days:].mean())
        eligible = [pair for pair in PAIR_ORDER if short_returns[pair] > 0]
        if not risk_on or not eligible:
            return {pair: 0.0 for pair in PAIR_ORDER}
        if policy == "C2AEqualWeightRiskOn":
            weight = 1.0 / len(eligible)
            return {pair: (weight if pair in eligible else 0.0) for pair in PAIR_ORDER}

        inverse: dict[str, float] = {}
        for pair in eligible:
            series = closes[pair]
            if len(series) < vol_days + 1:
                raise C2AAllocationError("insufficient inverse-volatility history")
            log_returns = np.diff(np.log(series.iloc[-(vol_days + 1) :].to_numpy(dtype=float)))
            volatility = float(np.std(log_returns, ddof=0))
            if not math.isfinite(volatility) or volatility <= 0:
                raise C2AAllocationError(f"invalid volatility for {pair}")
            inverse[pair] = 1.0 / volatility
        total = sum(inverse.values())
        raw = {pair: inverse[pair] / total for pair in eligible}
        cap = _finite(signals["inverse_volatility_asset_cap"], "inverse-volatility cap")
        capped = {pair: min(raw[pair], cap) for pair in eligible}
        remaining = max(0.0, 1.0 - sum(capped.values()))
        uncapped = [pair for pair in eligible if raw[pair] < cap - EPSILON]
        if remaining > EPSILON and uncapped:
            base = sum(raw[pair] for pair in uncapped)
            for pair in uncapped:
                capped[pair] += remaining * raw[pair] / base
        return {pair: float(capped.get(pair, 0.0)) for pair in PAIR_ORDER}

    long_returns = {pair: _lookback_return(closes[pair], long_days) for pair in PAIR_ORDER}
    eligible = [
        pair
        for pair in PAIR_ORDER
        if short_returns[pair] > 0 and long_returns[pair] > 0
    ]
    order = {pair: index for index, pair in enumerate(PAIR_ORDER)}
    eligible.sort(key=lambda pair: (-long_returns[pair], -short_returns[pair], order[pair]))
    chosen = eligible[:2]
    single = _finite(signals["top_two_single_asset_weight"], "top-two single weight")
    if len(chosen) == 1:
        return {pair: (single if pair == chosen[0] else 0.0) for pair in PAIR_ORDER}
    if len(chosen) == 2:
        return {pair: (0.5 if pair in chosen else 0.0) for pair in PAIR_ORDER}
    return {pair: 0.0 for pair in PAIR_ORDER}


@dataclass
class PortfolioState:
    cash: float
    units: dict[str, float]


def _execute_target(
    state: PortfolioState,
    prices: Mapping[str, float],
    targets: Mapping[str, float],
    *,
    fee_rate: float,
    no_trade_band: float,
    turnover_cap: float | None,
) -> dict[str, Any]:
    pre_equity = state.cash + sum(state.units[pair] * prices[pair] for pair in PAIR_ORDER)
    if pre_equity <= 0 or not math.isfinite(pre_equity):
        raise C2AAllocationError("non-positive pre-trade equity")
    current_values = {pair: state.units[pair] * prices[pair] for pair in PAIR_ORDER}
    current_weights = {pair: current_values[pair] / pre_equity for pair in PAIR_ORDER}
    adjusted: dict[str, float] = {}
    for pair in PAIR_ORDER:
        target = _finite(targets.get(pair, 0.0), f"target {pair}")
        if target < -EPSILON or target > 1.0 + EPSILON:
            raise C2AAllocationError(f"invalid target weight for {pair}")
        adjusted[pair] = current_weights[pair] if abs(target - current_weights[pair]) < no_trade_band else target
    if sum(max(0.0, value) for value in adjusted.values()) > 1.0 + EPSILON:
        raise C2AAllocationError("adjusted targets exceed one")
    deltas = {pair: adjusted[pair] * pre_equity - current_values[pair] for pair in PAIR_ORDER}
    requested_turnover = sum(abs(value) for value in deltas.values()) / pre_equity
    cap_scaled = False
    if turnover_cap is not None and requested_turnover > turnover_cap + EPSILON:
        scale = turnover_cap / requested_turnover
        deltas = {pair: value * scale for pair, value in deltas.items()}
        cap_scaled = True

    executed = {pair: 0.0 for pair in PAIR_ORDER}
    fees = {pair: 0.0 for pair in PAIR_ORDER}
    for pair in PAIR_ORDER:
        delta = deltas[pair]
        if delta >= -EPSILON:
            continue
        notional = min(-delta, state.units[pair] * prices[pair])
        units_sold = notional / prices[pair]
        fee = notional * fee_rate
        state.units[pair] -= units_sold
        state.cash += notional - fee
        executed[pair] -= notional
        fees[pair] += fee

    requested_buys = {pair: max(0.0, deltas[pair]) for pair in PAIR_ORDER}
    buy_total = sum(requested_buys.values())
    buy_scale = 1.0
    if buy_total > EPSILON:
        buy_scale = min(1.0, state.cash / (buy_total * (1.0 + fee_rate)))
    for pair in PAIR_ORDER:
        notional = requested_buys[pair] * buy_scale
        if notional <= EPSILON:
            continue
        fee = notional * fee_rate
        if notional + fee > state.cash + 1e-7:
            raise C2AAllocationError("buy exceeds available cash")
        state.cash -= notional + fee
        state.units[pair] += notional / prices[pair]
        executed[pair] += notional
        fees[pair] += fee

    if state.cash < -1e-7 or any(state.units[pair] < -1e-12 for pair in PAIR_ORDER):
        raise C2AAllocationError("negative portfolio state after trade")
    state.cash = max(0.0, state.cash)
    turnover = sum(abs(value) for value in executed.values()) / pre_equity
    if turnover_cap is not None and turnover > turnover_cap + 1e-7:
        raise C2AAllocationError("executed turnover exceeds cap")
    return {
        "pre_trade_equity": pre_equity,
        "requested_targets": {pair: float(targets.get(pair, 0.0)) for pair in PAIR_ORDER},
        "adjusted_targets": adjusted,
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


def _max_drawdown(equity: Sequence[float]) -> float:
    peak = -math.inf
    drawdown = 0.0
    for value in equity:
        peak = max(peak, value)
        if peak > 0:
            drawdown = max(drawdown, (peak - value) / peak)
    return drawdown


def simulate_window(
    market: pd.DataFrame,
    *,
    policy: str,
    window: Mapping[str, str],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    if cost_label not in COST_LABELS:
        raise C2AAllocationError("unknown cost label")
    start, end = _iso(window["start"]), _iso(window["end"])
    positions = [index for index, when in enumerate(market.index) if start <= when < end]
    if not positions:
        raise C2AAllocationError(f"empty window {window['id']}")
    if positions[0] == 0:
        raise C2AAllocationError("window lacks previous completed signal candle")
    expected_dates = pd.date_range(start=start, end=end - pd.Timedelta(days=1), freq="1D", tz=UTC)
    actual_dates = market.index[positions]
    if not actual_dates.equals(expected_dates):
        raise C2AAllocationError(f"window {window['id']} has missing or extra daily candles")

    fee_rate = _finite(config["cost_rates"][cost_label], "fee rate")
    state = PortfolioState(
        cash=_finite(config["starting_equity"], "starting equity"),
        units={pair: 0.0 for pair in PAIR_ORDER},
    )
    previous_equity = state.cash
    daily_rows: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    turnover_terms: list[float] = []
    asset_pnl = {pair: 0.0 for pair in PAIR_ORDER}
    scheduled_nonzero = 0

    for offset, position in enumerate(positions):
        when = market.index[position]
        open_prices = {pair: float(market.iloc[position][(pair, "open")]) for pair in PAIR_ORDER}
        close_prices = {pair: float(market.iloc[position][(pair, "close")]) for pair in PAIR_ORDER}
        previous_close = {
            pair: float(market.iloc[position - 1][(pair, "close")]) for pair in PAIR_ORDER
        }
        units_before = dict(state.units)
        contribution = {
            pair: units_before[pair] * (open_prices[pair] - previous_close[pair])
            for pair in PAIR_ORDER
        }
        trade_fees = {pair: 0.0 for pair in PAIR_ORDER}

        if when.day == 1:
            history = market.iloc[:position]
            targets = _targets(policy, history, config)
            event = _execute_target(
                state,
                open_prices,
                targets,
                fee_rate=fee_rate,
                no_trade_band=_finite(config["no_trade_band"], "no-trade band"),
                turnover_cap=_finite(config["scheduled_turnover_cap"], "turnover cap"),
            )
            event.update({"kind": "SCHEDULED_REBALANCE", "date": when.isoformat()})
            events.append(event)
            turnover_terms.append(float(event["turnover_ratio"]))
            if event["nonzero"]:
                scheduled_nonzero += 1
            for pair in PAIR_ORDER:
                trade_fees[pair] += float(event["fees"][pair])

        units_after_open = dict(state.units)
        for pair in PAIR_ORDER:
            contribution[pair] += units_after_open[pair] * (close_prices[pair] - open_prices[pair])
            contribution[pair] -= trade_fees[pair]

        terminal = offset == len(positions) - 1
        terminal_event: dict[str, Any] | None = None
        if terminal:
            terminal_event = _execute_target(
                state,
                close_prices,
                {pair: 0.0 for pair in PAIR_ORDER},
                fee_rate=fee_rate,
                no_trade_band=0.0,
                turnover_cap=None,
            )
            terminal_event.update({"kind": "TERMINAL_LIQUIDATION", "date": when.isoformat()})
            events.append(terminal_event)
            turnover_terms.append(float(terminal_event["turnover_ratio"]))
            for pair in PAIR_ORDER:
                contribution[pair] -= float(terminal_event["fees"][pair])

        equity = state.cash + sum(state.units[pair] * close_prices[pair] for pair in PAIR_ORDER)
        pnl = equity - previous_equity
        contribution_total = sum(contribution.values())
        if not math.isclose(pnl, contribution_total, abs_tol=1e-6, rel_tol=1e-9):
            raise C2AAllocationError(
                f"daily PnL reconciliation failed {when.isoformat()}: {pnl} != {contribution_total}"
            )
        daily_return = pnl / previous_equity if previous_equity > 0 else 0.0
        for pair in PAIR_ORDER:
            asset_pnl[pair] += contribution[pair]
        daily_rows.append(
            {
                "date": when.isoformat(),
                "equity": equity,
                "cash": state.cash,
                "daily_pnl": pnl,
                "daily_return": daily_return,
                "asset_pnl": contribution,
                "units": dict(state.units),
                "terminal": terminal,
            }
        )
        previous_equity = equity

    if abs(state.cash - previous_equity) > 1e-6 or any(abs(value) > 1e-12 for value in state.units.values()):
        raise C2AAllocationError("window did not end in cash")
    equities = [float(config["starting_equity"])] + [float(row["equity"]) for row in daily_rows]
    return {
        "schema_version": 1,
        "policy_id": policy,
        "window_id": window["id"],
        "window_start": window["start"],
        "window_end": window["end"],
        "cost_label": cost_label,
        "fee_rate": fee_rate,
        "starting_equity": float(config["starting_equity"]),
        "ending_equity": previous_equity,
        "net_profit_abs": previous_equity - float(config["starting_equity"]),
        "net_return": previous_equity / float(config["starting_equity"]) - 1.0,
        "max_drawdown": _max_drawdown(equities),
        "scheduled_nonzero_rebalances": scheduled_nonzero,
        "turnover_terms": turnover_terms,
        "turnover_sum": sum(turnover_terms),
        "asset_pnl": asset_pnl,
        "daily": daily_rows,
        "events": events,
        "status": "PASS",
    }


def simulate_buy_hold(
    market: pd.DataFrame,
    *,
    comparator_id: str,
    window: Mapping[str, str],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    """Run a non-selectable per-window cash, BTC, or static equal-weight comparator."""
    if comparator_id not in ("cash", "btc_buy_hold", "equal_weight_buy_hold"):
        raise C2AAllocationError("unknown comparator")
    start, end = _iso(window["start"]), _iso(window["end"])
    positions = [index for index, when in enumerate(market.index) if start <= when < end]
    if not positions:
        raise C2AAllocationError("empty comparator window")
    fee_rate = _finite(config["cost_rates"][cost_label], "comparator fee")
    state = PortfolioState(float(config["starting_equity"]), {pair: 0.0 for pair in PAIR_ORDER})
    previous_equity = state.cash
    daily_returns: list[float] = []
    equities = [previous_equity]
    for offset, position in enumerate(positions):
        open_prices = {pair: float(market.iloc[position][(pair, "open")]) for pair in PAIR_ORDER}
        close_prices = {pair: float(market.iloc[position][(pair, "close")]) for pair in PAIR_ORDER}
        previous_close = {pair: float(market.iloc[position - 1][(pair, "close")]) for pair in PAIR_ORDER}
        units_before = dict(state.units)
        pnl = sum(units_before[pair] * (open_prices[pair] - previous_close[pair]) for pair in PAIR_ORDER)
        if offset == 0 and comparator_id != "cash":
            if comparator_id == "btc_buy_hold":
                targets = {pair: (1.0 if pair == "BTC/USDT" else 0.0) for pair in PAIR_ORDER}
            else:
                targets = {pair: 1.0 / 3.0 for pair in PAIR_ORDER}
            event = _execute_target(
                state,
                open_prices,
                targets,
                fee_rate=fee_rate,
                no_trade_band=0.0,
                turnover_cap=None,
            )
            pnl -= float(event["fee_total"])
        pnl += sum(state.units[pair] * (close_prices[pair] - open_prices[pair]) for pair in PAIR_ORDER)
        if offset == len(positions) - 1 and comparator_id != "cash":
            event = _execute_target(
                state,
                close_prices,
                {pair: 0.0 for pair in PAIR_ORDER},
                fee_rate=fee_rate,
                no_trade_band=0.0,
                turnover_cap=None,
            )
            pnl -= float(event["fee_total"])
        equity = state.cash + sum(state.units[pair] * close_prices[pair] for pair in PAIR_ORDER)
        if not math.isclose(equity - previous_equity, pnl, abs_tol=1e-6, rel_tol=1e-9):
            raise C2AAllocationError("comparator PnL reconciliation failed")
        daily_returns.append((equity - previous_equity) / previous_equity if previous_equity > 0 else 0.0)
        equities.append(equity)
        previous_equity = equity
    return {
        "comparator_id": comparator_id,
        "window_id": window["id"],
        "cost_label": cost_label,
        "net_profit_abs": previous_equity - float(config["starting_equity"]),
        "net_return": previous_equity / float(config["starting_equity"]) - 1.0,
        "max_drawdown": _max_drawdown(equities),
        "daily_returns": daily_returns,
        "status": "PASS",
    }


def _share(values: Sequence[float]) -> float:
    positives = [max(0.0, float(value)) for value in values]
    total = sum(positives)
    return max(positives) / total if total > EPSILON else 1.0


def _top_share(values: Sequence[float], count: int) -> float:
    positives = sorted((max(0.0, float(value)) for value in values), reverse=True)
    total = sum(positives)
    return sum(positives[:count]) / total if total > EPSILON else 1.0


def aggregate_policy(
    rows: Sequence[Mapping[str, Any]],
    *,
    policy: str,
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    selected = [row for row in rows if row["policy_id"] == policy and row["cost_label"] == cost_label]
    selected.sort(key=lambda row: row["window_id"])
    if [row["window_id"] for row in selected] != ["S1", "S2", "S3"]:
        raise C2AAllocationError("aggregate requires exactly S1/S2/S3")
    returns = [float(row["net_return"]) for row in selected]
    aggregate_return = math.prod(1.0 + value for value in returns) - 1.0
    daily_returns = [float(day["daily_return"]) for row in selected for day in row["daily"]]
    daily_pnl = [float(day["daily_pnl"]) for row in selected for day in row["daily"]]
    mean = float(np.mean(daily_returns)) if daily_returns else 0.0
    std = float(np.std(daily_returns, ddof=0)) if daily_returns else 0.0
    sharpe = mean / std * math.sqrt(365.0) if std > EPSILON else 0.0
    asset_pnl = {pair: sum(float(row["asset_pnl"][pair]) for row in selected) for pair in PAIR_ORDER}
    total_days = sum((_iso(row["window_end"]) - _iso(row["window_start"])).days for row in selected)
    turnover = sum(float(row["turnover_sum"]) for row in selected) * 365.0 / total_days
    positive_assets = [pair for pair, value in asset_pnl.items() if value > EPSILON]
    positive_daily = [value for value in daily_pnl if value > 0]
    return {
        "policy_id": policy,
        "cost_label": cost_label,
        "window_returns": dict(zip(("S1", "S2", "S3"), returns, strict=True)),
        "minimum_window_net_return": min(returns),
        "median_window_net_return": median(returns),
        "positive_windows": sum(value > 0 for value in returns),
        "aggregate_net_return": aggregate_return,
        "aggregate_sharpe": sharpe,
        "maximum_window_drawdown": max(float(row["max_drawdown"]) for row in selected),
        "scheduled_nonzero_rebalances": sum(int(row["scheduled_nonzero_rebalances"]) for row in selected),
        "minimum_window_nonzero_rebalances": min(int(row["scheduled_nonzero_rebalances"]) for row in selected),
        "annualized_one_way_turnover": turnover,
        "asset_pnl": asset_pnl,
        "positive_assets": positive_assets,
        "maximum_asset_positive_pnl_share": _share(list(asset_pnl.values())),
        "maximum_window_positive_pnl_share": _share([float(row["net_profit_abs"]) for row in selected]),
        "maximum_single_positive_daily_contribution_share": _share(positive_daily),
        "top_three_positive_daily_contribution_share": _top_share(positive_daily, 3),
        "status": "PASS",
    }


def aggregate_comparator(rows: Sequence[Mapping[str, Any]], comparator_id: str, cost_label: str) -> dict[str, Any]:
    selected = [
        row for row in rows if row["comparator_id"] == comparator_id and row["cost_label"] == cost_label
    ]
    selected.sort(key=lambda row: row["window_id"])
    if [row["window_id"] for row in selected] != ["S1", "S2", "S3"]:
        raise C2AAllocationError("comparator aggregate requires S1/S2/S3")
    returns = [float(row["net_return"]) for row in selected]
    return {
        "comparator_id": comparator_id,
        "cost_label": cost_label,
        "aggregate_net_return": math.prod(1.0 + value for value in returns) - 1.0,
        "maximum_window_drawdown": max(float(row["max_drawdown"]) for row in selected),
        "window_returns": dict(zip(("S1", "S2", "S3"), returns, strict=True)),
    }


def decide(
    policy_aggregates: Sequence[Mapping[str, Any]],
    comparator_aggregates: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    expected = {row["policy_id"]: row for row in policy_aggregates if row["cost_label"] == "1.0x"}
    stress = {row["policy_id"]: row for row in policy_aggregates if row["cost_label"] == "1.5x"}
    if set(expected) != set(POLICIES) or set(stress) != set(POLICIES):
        raise C2AAllocationError("decision aggregates incomplete")
    benchmark = next(
        (
            row
            for row in comparator_aggregates
            if row["comparator_id"] == "equal_weight_buy_hold" and row["cost_label"] == "1.0x"
        ),
        None,
    )
    if benchmark is None:
        raise C2AAllocationError("equal-weight comparator missing")
    gate = config["gate"]
    decisions: list[dict[str, Any]] = []
    for policy in POLICIES:
        row, stress_row = expected[policy], stress[policy]
        benchmark_capture = (
            row["aggregate_net_return"] >= gate["minimum_positive_benchmark_capture"] * benchmark["aggregate_net_return"]
            or row["maximum_window_drawdown"]
            <= benchmark["maximum_window_drawdown"]
            * (1.0 - gate["minimum_drawdown_reduction_vs_positive_benchmark"])
            if benchmark["aggregate_net_return"] > 0
            else row["aggregate_net_return"] > 0
        )
        checks = {
            "positive_windows": row["positive_windows"] >= gate["minimum_positive_windows"],
            "positive_median": row["median_window_net_return"] > 0,
            "positive_aggregate": row["aggregate_net_return"] > 0,
            "nonnegative_stress": stress_row["aggregate_net_return"] >= 0,
            "drawdown": row["maximum_window_drawdown"] <= gate["maximum_window_drawdown_ratio"],
            "sharpe": row["aggregate_sharpe"] >= gate["minimum_aggregate_sharpe"],
            "rebalance_total": row["scheduled_nonzero_rebalances"] >= gate["minimum_nonzero_scheduled_rebalances"],
            "rebalance_each_window": row["minimum_window_nonzero_rebalances"]
            >= gate["minimum_nonzero_scheduled_rebalances_per_window"],
            "turnover": row["annualized_one_way_turnover"] <= gate["maximum_annualized_one_way_turnover"],
            "asset_breadth": len(row["positive_assets"]) >= gate["minimum_positive_assets"],
            "asset_concentration": row["maximum_asset_positive_pnl_share"]
            <= gate["maximum_asset_positive_pnl_share"],
            "window_concentration": row["maximum_window_positive_pnl_share"]
            <= gate["maximum_window_positive_pnl_share"],
            "single_day_concentration": row["maximum_single_positive_daily_contribution_share"]
            <= gate["maximum_single_positive_daily_contribution_share"],
            "top_three_day_concentration": row["top_three_positive_daily_contribution_share"]
            <= gate["maximum_top_daily_cluster_positive_contribution_share"],
            "benchmark_capture_or_drawdown": benchmark_capture,
        }
        decisions.append(
            {
                "policy_id": policy,
                "eligible": all(checks.values()),
                "checks": checks,
                "expected": dict(row),
                "stress": dict(stress_row),
            }
        )
    eligible = [item for item in decisions if item["eligible"]]
    eligible.sort(
        key=lambda item: (
            -float(item["expected"]["minimum_window_net_return"]),
            -float(item["expected"]["median_window_net_return"]),
            -float(item["stress"]["aggregate_net_return"]),
            float(item["expected"]["maximum_window_drawdown"]),
            float(item["expected"]["annualized_one_way_turnover"]),
            item["policy_id"],
        )
    )
    selected = eligible[0]["policy_id"] if eligible else None
    return {
        "schema_version": 1,
        "stage": "C2A",
        "economic_result": "SELECTED" if selected else "REJECTED",
        "selected_policy": selected,
        "ranking": [item["policy_id"] for item in eligible],
        "decisions": decisions,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
