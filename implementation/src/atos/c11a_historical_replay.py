"""Deterministic C11A signal, continuous-notional ledger, and replay."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from statistics import mean, stdev
from typing import Any

from scipy.stats import kurtosis, norm, skew

from atos.c11a_contract import (
    BTC_BETA_BENCHMARK,
    CANDIDATE_ID,
    COST_RATES,
    EXPECTED_DECISIONS_PER_WINDOW,
    EXPECTED_NONFLAT_DIRECTIONS,
    EXPECTED_TOTAL_DECISIONS,
    GROSS_NOTIONAL,
    HISTORICAL_WINDOWS,
    HOUR,
    LONG_COUNT,
    MINIMUM_EQUITY_TO_GROSS_NOTIONAL,
    PER_POSITION_ABS_NOTIONAL,
    RECONCILIATION_TOLERANCE,
    REGRESSION_LOOKBACK_RETURNS,
    SHORT_COUNT,
    STARTING_EQUITY,
    HistoricalWindow,
    decision_times,
    iso,
    safety_boundary,
    window_by_id,
)
from atos.c11a_research_program_guard import (
    EXPECTED_FAMILYWISE_TRIALS,
    bonferroni_adjusted_psr,
)

POLICIES = (
    CANDIDATE_ID,
    "TotalVolatilityComparator",
    "AlwaysLongSelectedUniverseComparator",
    "CashComparator",
)


class C11AHistoricalReplayError(RuntimeError):
    """Raised when source, signal, ledger, or accounting fails closed."""


def _time(value: Any) -> datetime:
    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise C11AHistoricalReplayError(f"invalid timestamp: {value!r}") from exc
    if stamp.tzinfo is None:
        raise C11AHistoricalReplayError("timestamp must be timezone-aware")
    return stamp.astimezone(UTC)


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise C11AHistoricalReplayError(f"{label} must be decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise C11AHistoricalReplayError(f"{label} must be decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise C11AHistoricalReplayError(f"{label} must be {qualifier}")
    return result


def _hourly_prices(
    rows_by_instrument: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    selected_universe: Sequence[str],
    field: str,
    label: str,
) -> dict[str, dict[datetime, Decimal]]:
    selected = tuple(selected_universe)
    if set(rows_by_instrument) != set(selected) or len(selected) != len(set(selected)):
        raise C11AHistoricalReplayError(f"{label} instrument inventory drift")
    output: dict[str, dict[datetime, Decimal]] = {}
    reference: tuple[datetime, ...] | None = None
    for instrument in selected:
        rows = rows_by_instrument[instrument]
        values: dict[datetime, Decimal] = {}
        previous = None
        for row in rows:
            stamp = _time(row.get("timestamp"))
            if stamp.minute or stamp.second or stamp.microsecond:
                raise C11AHistoricalReplayError(f"{label} timestamp is off-grid")
            if previous is not None and stamp <= previous:
                raise C11AHistoricalReplayError(f"{label} rows are duplicate or unordered")
            previous = stamp
            values[stamp] = _decimal(row.get(field), f"{label} {field}", positive=True)
        timestamps = tuple(values)
        if not timestamps or (reference is not None and timestamps != reference):
            raise C11AHistoricalReplayError(f"{label} timestamps are empty or misaligned")
        reference = timestamps
        output[instrument] = values
    return output


def _funding_rows(
    rows_by_instrument: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    selected_universe: Sequence[str],
) -> dict[datetime, dict[str, Decimal]]:
    selected = tuple(selected_universe)
    if set(rows_by_instrument) != set(selected):
        raise C11AHistoricalReplayError("funding instrument inventory drift")
    output: dict[datetime, dict[str, Decimal]] = {}
    for instrument in selected:
        previous = None
        for row in rows_by_instrument[instrument]:
            stamp = _time(row.get("funding_time"))
            if previous is not None and stamp <= previous:
                raise C11AHistoricalReplayError(
                    "funding rows are duplicate or unordered within instrument"
                )
            previous = stamp
            by_instrument = output.setdefault(stamp, {})
            if instrument in by_instrument:
                raise C11AHistoricalReplayError("duplicate funding settlement")
            by_instrument[instrument] = _decimal(
                row.get("realized_rate"), "realized funding rate"
            )
    return output


def _require_exact_hours(
    values: Mapping[datetime, Decimal],
    *,
    start: datetime,
    end_exclusive: datetime,
    label: str,
) -> None:
    expected = []
    current = start
    while current < end_exclusive:
        expected.append(current)
        current += HOUR
    missing = [stamp for stamp in expected if stamp not in values]
    if missing:
        raise C11AHistoricalReplayError(
            f"{label} missing exact hour: {iso(missing[0])}"
        )


def _ols(y: Sequence[float], x: Sequence[float]) -> tuple[float, float]:
    if len(y) != REGRESSION_LOOKBACK_RETURNS or len(x) != len(y):
        raise C11AHistoricalReplayError("OLS observation count drift")
    mean_x = math.fsum(x) / len(x)
    mean_y = math.fsum(y) / len(y)
    covariance = math.fsum(
        (x_value - mean_x) * (y_value - mean_y)
        for x_value, y_value in zip(x, y, strict=True)
    )
    variance = math.fsum((value - mean_x) ** 2 for value in x)
    if not math.isfinite(covariance) or not math.isfinite(variance) or variance <= 0:
        raise C11AHistoricalReplayError("OLS factor variance is zero or invalid")
    beta = covariance / variance
    alpha = mean_y - beta * mean_x
    if not math.isfinite(alpha) or not math.isfinite(beta):
        raise C11AHistoricalReplayError("OLS coefficient is non-finite")
    return alpha, beta


def build_signal(
    decision_time: datetime,
    *,
    selected_universe: Sequence[str],
    mark_closes: Mapping[str, Mapping[datetime, Decimal]],
    policy: str = CANDIDATE_ID,
) -> dict[str, Any]:
    """Build one frozen signal using no candle later than t minus two hours."""

    selected = tuple(selected_universe)
    if (
        policy not in {CANDIDATE_ID, "TotalVolatilityComparator"}
        or len(selected) != 8
        or len(set(selected)) != 8
        or set(mark_closes) != set(selected)
    ):
        raise C11AHistoricalReplayError("signal policy or selected universe drift")
    decision = _time(decision_time)
    if decision.weekday() != 0 or any(
        (decision.hour, decision.minute, decision.second, decision.microsecond)
    ):
        raise C11AHistoricalReplayError("signal decision is not Monday 00:00 UTC")
    last_stamp = decision - 2 * HOUR
    first_stamp = last_stamp - REGRESSION_LOOKBACK_RETURNS * HOUR
    stamps = tuple(
        first_stamp + offset * HOUR
        for offset in range(REGRESSION_LOOKBACK_RETURNS + 1)
    )
    returns: dict[str, tuple[float, ...]] = {}
    for instrument in selected:
        prices = mark_closes[instrument]
        try:
            points = [prices[stamp] for stamp in stamps]
        except KeyError as exc:
            raise C11AHistoricalReplayError(
                f"signal missing exact mark hour: {instrument} {iso(exc.args[0])}"
            ) from exc
        values = tuple(
            math.log(float(right / left))
            for left, right in pairwise(points)
        )
        if len(values) != REGRESSION_LOOKBACK_RETURNS or not all(
            math.isfinite(value) for value in values
        ):
            raise C11AHistoricalReplayError("signal return vector is invalid")
        returns[instrument] = values

    rows: list[dict[str, Any]] = []
    for instrument in selected:
        own = returns[instrument]
        others = [returns[value] for value in selected if value != instrument]
        factor = tuple(
            math.fsum(series[index] for series in others) / len(others)
            for index in range(REGRESSION_LOOKBACK_RETURNS)
        )
        alpha, beta = _ols(own, factor)
        residuals = tuple(
            own[index] - alpha - beta * factor[index]
            for index in range(REGRESSION_LOOKBACK_RETURNS)
        )
        total_volatility_score = stdev(own)
        idiosyncratic_volatility_score = stdev(residuals)
        score = (
            idiosyncratic_volatility_score
            if policy == CANDIDATE_ID
            else total_volatility_score
        )
        if not all(
            math.isfinite(value)
            for value in (
                alpha,
                beta,
                total_volatility_score,
                idiosyncratic_volatility_score,
                score,
            )
        ):
            raise C11AHistoricalReplayError("signal statistic is non-finite")
        rows.append(
            {
                "instrument": instrument,
                "alpha": alpha,
                "beta": beta,
                "total_volatility_score": total_volatility_score,
                "idiosyncratic_volatility_score": idiosyncratic_volatility_score,
                "ranking_score": score,
            }
        )
    rows.sort(key=lambda row: (-float(row["ranking_score"]), str(row["instrument"])))
    longs = tuple(str(row["instrument"]) for row in rows[:LONG_COUNT])
    shorts = tuple(str(row["instrument"]) for row in rows[-SHORT_COUNT:])
    if set(longs) & set(shorts) or len(longs) != LONG_COUNT or len(shorts) != SHORT_COUNT:
        raise C11AHistoricalReplayError("signal long/short rank construction failed")
    directions = {
        instrument: 1 if instrument in longs else -1 if instrument in shorts else 0
        for instrument in selected
    }
    return {
        "stage": "C11A_SIGNAL",
        "policy": policy,
        "decision_time": iso(decision),
        "last_permitted_mark_timestamp": iso(last_stamp),
        "regression_return_count": REGRESSION_LOOKBACK_RETURNS,
        "rows": rows,
        "longs": list(longs),
        "shorts": list(shorts),
        "directions": directions,
        **safety_boundary(),
    }


def _maximum_drawdown(values: Sequence[Decimal]) -> Decimal:
    if not values or any(not value.is_finite() or value <= 0 for value in values):
        raise C11AHistoricalReplayError("drawdown path is empty or invalid")
    peak = values[0]
    maximum = Decimal(0)
    for value in values:
        peak = max(peak, value)
        maximum = max(maximum, Decimal(1) - value / peak)
    return maximum


def _cash_window(window: HistoricalWindow, cost_label: str) -> dict[str, Any]:
    return {
        "stage": "C11A_HISTORICAL_WINDOW",
        "window": window.to_dict(),
        "policy": "CashComparator",
        "cost_label": cost_label,
        "cost_rate": format(COST_RATES[cost_label], "f"),
        "starting_equity": format(STARTING_EQUITY, "f"),
        "final_equity": format(STARTING_EQUITY, "f"),
        "net_return": "0",
        "weekly_returns": ["0"] * EXPECTED_DECISIONS_PER_WINDOW,
        "weekly_buckets": [
            {
                "start": iso(start),
                "end_exclusive": iso(start + 7 * 24 * HOUR),
                "start_equity": format(STARTING_EQUITY, "f"),
                "end_equity": format(STARTING_EQUITY, "f"),
                "weekly_pnl": "0",
                "weekly_return": "0",
            }
            for start in decision_times(window)
        ],
        "maximum_drawdown": "0",
        "turnover_sum": "0",
        "decision_count": EXPECTED_DECISIONS_PER_WINDOW,
        "signal_count": 0,
        "nonflat_direction_count": 0,
        "funding_settlement_count": 0,
        "equity_buffer_breach_count": 0,
        "forced_close_count": 0,
        "contributions": {},
        "component_totals": {"price_pnl": "0", "funding_pnl": "0", "costs": "0"},
        "reconciliation_residual": "0",
        "complete_hourly_equity_path": [
            {
                "timestamp": iso(window.start),
                "event": "WINDOW_START",
                "equity": format(STARTING_EQUITY, "f"),
            },
            {
                "timestamp": iso(window.end_exclusive),
                "event": "TERMINAL_CLOSE",
                "equity": format(STARTING_EQUITY, "f"),
            },
        ],
        "signals": [],
        **safety_boundary(),
    }


def evaluate_historical_window(
    window: HistoricalWindow | str,
    *,
    selected_universe: Sequence[str],
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    cost_label: str,
    policy: str = CANDIDATE_ID,
) -> dict[str, Any]:
    """Replay one independent 26-week window with exact event ordering."""

    selected_window = window_by_id(window) if isinstance(window, str) else window
    if selected_window not in HISTORICAL_WINDOWS:
        raise C11AHistoricalReplayError("window is not frozen C11A history")
    selected = tuple(selected_universe)
    if len(selected) != 8 or len(set(selected)) != 8:
        raise C11AHistoricalReplayError("selected universe must contain eight instruments")
    if cost_label not in COST_RATES or policy not in POLICIES:
        raise C11AHistoricalReplayError("unknown C11A policy or cost")
    if policy == "CashComparator":
        return _cash_window(selected_window, cost_label)

    trades = _hourly_prices(
        trade_rows,
        selected_universe=selected,
        field="open",
        label="trade",
    )
    marks = _hourly_prices(
        mark_rows,
        selected_universe=selected,
        field="close",
        label="mark",
    )
    funding = _funding_rows(funding_rows, selected_universe=selected)
    delayed_funding: dict[
        datetime, list[tuple[datetime, dict[str, Decimal]]]
    ] = {}
    for stamp, values in funding.items():
        if stamp.minute or stamp.second or stamp.microsecond:
            following_hour = stamp.replace(minute=0, second=0, microsecond=0) + HOUR
            delayed_funding.setdefault(following_hour, []).append((stamp, values))
    for events in delayed_funding.values():
        events.sort(key=lambda item: item[0])
    _require_exact_hours(
        next(iter(trades.values())),
        start=selected_window.start,
        end_exclusive=selected_window.end_exclusive + HOUR,
        label="trade",
    )
    _require_exact_hours(
        next(iter(marks.values())),
        start=selected_window.start - (REGRESSION_LOOKBACK_RETURNS + 2) * HOUR,
        end_exclusive=selected_window.end_exclusive,
        label="mark",
    )
    decisions = set(decision_times(selected_window))
    quantities = {instrument: Decimal(0) for instrument in selected}
    reference_marks: dict[str, Decimal | None] = {instrument: None for instrument in selected}
    price_pnl = {instrument: Decimal(0) for instrument in selected}
    funding_pnl = {instrument: Decimal(0) for instrument in selected}
    costs = {instrument: Decimal(0) for instrument in selected}
    equity = STARTING_EQUITY
    path = [equity]
    path_rows = [
        {
            "timestamp": iso(selected_window.start),
            "event": "WINDOW_START",
            "equity": format(equity, "f"),
        }
    ]
    turnover_sum = Decimal(0)
    funding_count = 0
    processed_funding: set[tuple[datetime, str]] = set()
    buffer_breaches = 0
    forced_closes = 0
    suppressed_decisions = 0
    pending_forced_close = False
    weekly_start: Decimal | None = None
    weekly_start_time: datetime | None = None
    weekly_returns: list[Decimal] = []
    weekly_buckets: list[dict[str, str]] = []
    signals: list[dict[str, Any]] = []
    nonflat_directions = 0
    cost_rate = COST_RATES[cost_label]

    def apply_price(instrument: str, new_price: Decimal) -> None:
        nonlocal equity
        old = reference_marks[instrument]
        if old is not None:
            change = quantities[instrument] * (new_price - old)
            price_pnl[instrument] += change
            equity += change
        reference_marks[instrument] = new_price

    def apply_cost(instrument: str, delta: Decimal, price: Decimal) -> Decimal:
        nonlocal equity
        value = abs(delta) * price * cost_rate
        costs[instrument] += value
        equity -= value
        return value

    def gross_at_reference(
        valuation_prices: Mapping[str, Decimal] | None = None,
    ) -> Decimal:
        return sum(
            abs(quantities[instrument])
            * (
                valuation_prices[instrument]
                if valuation_prices is not None
                else reference_marks[instrument] or Decimal(0)
            )
            for instrument in selected
        )

    def observe_buffer(
        valuation_prices: Mapping[str, Decimal] | None = None,
    ) -> None:
        nonlocal pending_forced_close, buffer_breaches
        gross = gross_at_reference(valuation_prices)
        if gross > 0 and equity / gross < MINIMUM_EQUITY_TO_GROSS_NOTIONAL:
            if not pending_forced_close:
                buffer_breaches += 1
            pending_forced_close = True

    def record_event(timestamp: datetime, event: str) -> None:
        path.append(equity)
        path_rows.append(
            {
                "timestamp": iso(timestamp),
                "event": event,
                "equity": format(equity, "f"),
            }
        )

    def apply_funding(timestamp: datetime, values: Mapping[str, Decimal]) -> None:
        nonlocal equity, funding_count
        predecessor_time = (timestamp - HOUR).replace(
            minute=0, second=0, microsecond=0
        )
        try:
            predecessor_marks = {
                instrument: marks[instrument][predecessor_time]
                for instrument in selected
            }
        except KeyError as exc:
            raise C11AHistoricalReplayError(
                "funding has no completed predecessor mark"
            ) from exc
        for instrument, rate in values.items():
            key = (timestamp, instrument)
            if key in processed_funding:
                raise C11AHistoricalReplayError(
                    "funding settlement accounted twice"
                )
            if quantities[instrument] != 0:
                change = -quantities[instrument] * predecessor_marks[instrument] * rate
                funding_pnl[instrument] += change
                equity += change
            processed_funding.add(key)
            funding_count += 1
        if values:
            record_event(timestamp, "FUNDING")
            observe_buffer(predecessor_marks)

    current = selected_window.start
    while current < selected_window.end_exclusive:
        is_decision = current in decisions
        apply_funding(current, funding.get(current, {}))
        observe_buffer()
        if is_decision:
            if weekly_start is not None:
                weekly_return = equity / weekly_start - Decimal(1)
                weekly_returns.append(weekly_return)
                if weekly_start_time is None:
                    raise C11AHistoricalReplayError("weekly start time is missing")
                weekly_buckets.append(
                    {
                        "start": iso(weekly_start_time),
                        "end_exclusive": iso(current),
                        "start_equity": format(weekly_start, "f"),
                        "end_equity": format(equity, "f"),
                        "weekly_pnl": format(equity - weekly_start, "f"),
                        "weekly_return": format(weekly_return, "f"),
                    }
                )
            weekly_start = equity
            weekly_start_time = current

        suppress_decision = False
        if pending_forced_close:
            for instrument in selected:
                open_price = trades[instrument][current]
                apply_price(instrument, open_price)
            record_event(current, "FORCED_OPEN_MARK")
            if equity <= 0:
                raise C11AHistoricalReplayError("non-positive equity before forced close")
            pretrade_equity = equity
            changed_notional = Decimal(0)
            for instrument in selected:
                delta = -quantities[instrument]
                changed_notional += abs(delta) * trades[instrument][current]
                apply_cost(instrument, delta, trades[instrument][current])
                quantities[instrument] = Decimal(0)
            turnover_sum += changed_notional / pretrade_equity
            pending_forced_close = False
            forced_closes += 1
            record_event(current, "FORCED_CLOSE")
            suppress_decision = is_decision
            if suppress_decision:
                suppressed_decisions += 1

        if is_decision and not suppress_decision:
            pretrade_equity = equity
            for instrument in selected:
                apply_price(instrument, trades[instrument][current])
            record_event(current, "SCHEDULED_OPEN_MARK")
            if pretrade_equity <= 0 or equity <= 0:
                raise C11AHistoricalReplayError("non-positive pretrade equity")
            pretrade_equity = equity
            if policy == "AlwaysLongSelectedUniverseComparator":
                directions = {instrument: 1 for instrument in selected}
                per_position = GROSS_NOTIONAL / Decimal(len(selected))
                signal = {
                    "stage": "C11A_ALWAYS_LONG_SIGNAL",
                    "policy": policy,
                    "decision_time": iso(current),
                    "directions": directions,
                    **safety_boundary(),
                }
            else:
                signal = build_signal(
                    current,
                    selected_universe=selected,
                    mark_closes=marks,
                    policy=policy,
                )
                directions = signal["directions"]
                per_position = PER_POSITION_ABS_NOTIONAL
                nonflat_directions += sum(
                    1 for direction in directions.values() if direction != 0
                )
            changed_notional = Decimal(0)
            signed_target = Decimal(0)
            gross_target = Decimal(0)
            for instrument in selected:
                direction = Decimal(int(directions[instrument]))
                target_notional = direction * per_position * pretrade_equity
                open_price = trades[instrument][current]
                target_quantity = target_notional / open_price
                delta = target_quantity - quantities[instrument]
                changed_notional += abs(delta) * open_price
                signed_target += target_quantity * open_price
                gross_target += abs(target_quantity) * open_price
                apply_cost(instrument, delta, open_price)
                quantities[instrument] = target_quantity
            if policy != "AlwaysLongSelectedUniverseComparator" and abs(
                signed_target
            ) > RECONCILIATION_TOLERANCE:
                raise C11AHistoricalReplayError("dollar-neutral target drift")
            expected_gross = GROSS_NOTIONAL * pretrade_equity
            if abs(gross_target - expected_gross) > RECONCILIATION_TOLERANCE:
                raise C11AHistoricalReplayError("gross target drift")
            turnover_sum += changed_notional / pretrade_equity
            signal["pretrade_equity"] = format(pretrade_equity, "f")
            signal["changed_notional"] = format(changed_notional, "f")
            signal["gross_target_notional"] = format(gross_target, "f")
            signal["signed_target_notional"] = format(signed_target, "f")
            signals.append(signal)
            record_event(current, "SCHEDULED_REBALANCE")

        for funding_time, values in delayed_funding.get(current + HOUR, ()):
            apply_funding(funding_time, values)

        for instrument in selected:
            apply_price(instrument, marks[instrument][current])
        if not equity.is_finite() or equity <= 0:
            raise C11AHistoricalReplayError("hourly equity is non-positive or non-finite")
        observe_buffer()
        record_event(current + HOUR, "HOURLY_MARK")
        current += HOUR

    if weekly_start is None or weekly_start_time is None:
        raise C11AHistoricalReplayError("window produced no weekly start")
    changed_notional = Decimal(0)
    for instrument in selected:
        boundary_open = trades[instrument][selected_window.end_exclusive]
        apply_price(instrument, boundary_open)
    record_event(selected_window.end_exclusive, "TERMINAL_OPEN_MARK")
    if equity <= 0:
        raise C11AHistoricalReplayError("non-positive terminal pretrade equity")
    preterminal_equity = equity
    for instrument in selected:
        boundary_open = trades[instrument][selected_window.end_exclusive]
        delta = -quantities[instrument]
        changed_notional += abs(delta) * boundary_open
        apply_cost(instrument, delta, boundary_open)
        quantities[instrument] = Decimal(0)
    turnover_sum += changed_notional / preterminal_equity
    terminal_weekly_return = equity / weekly_start - Decimal(1)
    weekly_returns.append(terminal_weekly_return)
    weekly_buckets.append(
        {
            "start": iso(weekly_start_time),
            "end_exclusive": iso(selected_window.end_exclusive),
            "start_equity": format(weekly_start, "f"),
            "end_equity": format(equity, "f"),
            "weekly_pnl": format(equity - weekly_start, "f"),
            "weekly_return": format(terminal_weekly_return, "f"),
        }
    )
    record_event(selected_window.end_exclusive, "TERMINAL_CLOSE")

    expected_funding = {
        (stamp, instrument)
        for stamp, by_instrument in funding.items()
        if selected_window.start <= stamp < selected_window.end_exclusive
        for instrument in by_instrument
    }
    if processed_funding != expected_funding:
        raise C11AHistoricalReplayError("funding settlements are unaccounted")
    if (
        len(weekly_returns) != EXPECTED_DECISIONS_PER_WINDOW
        or len(weekly_buckets) != EXPECTED_DECISIONS_PER_WINDOW
    ):
        raise C11AHistoricalReplayError("weekly return count drift")
    expected_signal_count = EXPECTED_DECISIONS_PER_WINDOW - suppressed_decisions
    if len(signals) != expected_signal_count:
        raise C11AHistoricalReplayError("decision signal count drift")

    contributions = {
        instrument: price_pnl[instrument] + funding_pnl[instrument] - costs[instrument]
        for instrument in selected
    }
    component_total = sum(price_pnl.values()) + sum(funding_pnl.values()) - sum(costs.values())
    residual = equity - STARTING_EQUITY - component_total
    if abs(residual) > RECONCILIATION_TOLERANCE or any(quantities.values()):
        raise C11AHistoricalReplayError("window accounting reconciliation failure")
    return {
        "stage": "C11A_HISTORICAL_WINDOW",
        "window": selected_window.to_dict(),
        "policy": policy,
        "cost_label": cost_label,
        "cost_rate": format(cost_rate, "f"),
        "starting_equity": format(STARTING_EQUITY, "f"),
        "final_equity": format(equity, "f"),
        "net_return": format(equity / STARTING_EQUITY - Decimal(1), "f"),
        "weekly_returns": [format(value, "f") for value in weekly_returns],
        "weekly_buckets": weekly_buckets,
        "maximum_drawdown": format(_maximum_drawdown(path), "f"),
        "turnover_sum": format(turnover_sum, "f"),
        "decision_count": EXPECTED_DECISIONS_PER_WINDOW,
        "signal_count": len(signals),
        "nonflat_direction_count": nonflat_directions,
        "funding_settlement_count": funding_count,
        "equity_buffer_breach_count": buffer_breaches,
        "forced_close_count": forced_closes,
        "contributions": {
            instrument: {
                "price_pnl": format(price_pnl[instrument], "f"),
                "funding_pnl": format(funding_pnl[instrument], "f"),
                "costs": format(costs[instrument], "f"),
                "net": format(contributions[instrument], "f"),
            }
            for instrument in selected
        },
        "component_totals": {
            "price_pnl": format(sum(price_pnl.values()), "f"),
            "funding_pnl": format(sum(funding_pnl.values()), "f"),
            "costs": format(sum(costs.values()), "f"),
        },
        "reconciliation_residual": format(residual, "f"),
        "complete_hourly_equity_path": path_rows,
        "signals": signals,
        **safety_boundary(),
    }


def _btc_weekly_mark_returns(
    window: HistoricalWindow,
    rows: Sequence[Mapping[str, Any]],
) -> list[str]:
    marks = _hourly_prices(
        {BTC_BETA_BENCHMARK: rows},
        selected_universe=(BTC_BETA_BENCHMARK,),
        field="close",
        label="BTC beta benchmark mark",
    )[BTC_BETA_BENCHMARK]
    _require_exact_hours(
        marks,
        start=window.start - HOUR,
        end_exclusive=window.end_exclusive,
        label="BTC beta benchmark mark",
    )
    output = []
    for start in decision_times(window):
        end = start + 7 * 24 * HOUR
        value = marks[end - HOUR] / marks[start - HOUR] - Decimal(1)
        if not value.is_finite():
            raise C11AHistoricalReplayError("BTC weekly benchmark return is invalid")
        output.append(format(value, "f"))
    return output


def evaluate_historical_window_matrix(
    window: HistoricalWindow | str,
    *,
    selected_universe: Sequence[str],
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Evaluate the frozen 12 policy/cost cells for one historical window."""

    selected_window = window_by_id(window) if isinstance(window, str) else window
    selected = tuple(selected_universe)
    expected_marks = {*selected, BTC_BETA_BENCHMARK}
    if (
        len(selected) != 8
        or set(trade_rows) != set(selected)
        or set(funding_rows) != set(selected)
        or set(mark_rows) != expected_marks
    ):
        raise C11AHistoricalReplayError("window matrix source inventory drift")
    selected_marks = {instrument: mark_rows[instrument] for instrument in selected}
    replays = {
        policy: {
            cost_label: evaluate_historical_window(
                selected_window,
                selected_universe=selected,
                trade_rows=trade_rows,
                mark_rows=selected_marks,
                funding_rows=funding_rows,
                cost_label=cost_label,
                policy=policy,
            )
            for cost_label in COST_RATES
        }
        for policy in POLICIES
    }
    return {
        "schema_version": 1,
        "stage": "C11A_HISTORICAL_WINDOW_MATRIX",
        "window": selected_window.to_dict(),
        "selected_universe": list(selected),
        "result_cell_count": len(POLICIES) * len(COST_RATES),
        "replays": replays,
        "btc_weekly_mark_returns": _btc_weekly_mark_returns(
            selected_window, mark_rows[BTC_BETA_BENCHMARK]
        ),
        "within_stage_candidate_count": 1,
        "declared_program_familywise_trial_count": EXPECTED_FAMILYWISE_TRIALS,
        **safety_boundary(),
    }


def _statistics(values: Sequence[Decimal]) -> dict[str, Any]:
    raw = [float(value) for value in values]
    if len(raw) != EXPECTED_TOTAL_DECISIONS or not all(
        math.isfinite(value) for value in raw
    ):
        raise C11AHistoricalReplayError("pooled weekly return coverage is invalid")
    sample_std = stdev(raw)
    average = mean(raw)
    if not math.isfinite(sample_std) or sample_std <= 0:
        return {
            "n": len(raw),
            "mean": float(average),
            "sample_std": float(sample_std),
            "weekly_sharpe": 0.0,
            "annualized_weekly_sharpe": 0.0,
            "unbiased_skewness": 0.0,
            "unbiased_ordinary_kurtosis": 0.0,
            "psr_probability": 0.0,
            "valid": False,
        }
    weekly_sharpe = average / sample_std
    sample_skew = float(skew(raw, bias=False))
    ordinary_kurtosis = float(kurtosis(raw, fisher=False, bias=False))
    radicand = (
        1
        - sample_skew * weekly_sharpe
        + ((ordinary_kurtosis - 1) / 4) * weekly_sharpe**2
    )
    valid = math.isfinite(radicand) and radicand > 0
    probability = (
        float(
            norm.cdf(
                weekly_sharpe
                * math.sqrt(EXPECTED_TOTAL_DECISIONS - 1)
                / math.sqrt(radicand)
            )
        )
        if valid
        else 0.0
    )
    valid = valid and all(
        math.isfinite(value)
        for value in (sample_skew, ordinary_kurtosis, probability)
    )
    return {
        "n": len(raw),
        "mean": float(average),
        "sample_std": float(sample_std),
        "weekly_sharpe": float(weekly_sharpe),
        "annualized_weekly_sharpe": float(weekly_sharpe * math.sqrt(52)),
        "unbiased_skewness": sample_skew,
        "unbiased_ordinary_kurtosis": ordinary_kurtosis,
        "psr_probability": probability if valid else 0.0,
        "valid": valid,
    }


def _positive_share(values: Sequence[Decimal], count: int = 1) -> Decimal | None:
    positive = sorted((max(value, Decimal(0)) for value in values), reverse=True)
    denominator = sum(positive, Decimal(0))
    return (
        None
        if denominator <= 0
        else sum(positive[:count], Decimal(0)) / denominator
    )


def _pool_policy(
    windows: Mapping[str, Any], *, policy: str, cost_label: str
) -> dict[str, Any]:
    ordered = [windows[window.window_id]["replays"][policy][cost_label] for window in HISTORICAL_WINDOWS]
    final_equities = [Decimal(str(row["final_equity"])) for row in ordered]
    weekly_returns = [
        Decimal(str(value)) for row in ordered for value in row["weekly_returns"]
    ]
    weekly_pnl = {
        f"{window.window_id}-week-{week + 1}": Decimal(str(bucket["weekly_pnl"]))
        for window, row in zip(HISTORICAL_WINDOWS, ordered, strict=True)
        for week, bucket in enumerate(row["weekly_buckets"])
    }
    contributions: dict[str, Decimal] = {}
    for row in ordered:
        for instrument, components in row["contributions"].items():
            contributions[instrument] = contributions.get(
                instrument, Decimal(0)
            ) + Decimal(str(components["net"]))
    statistics = _statistics(weekly_returns)
    psr = Decimal(str(statistics["psr_probability"]))
    return {
        "policy": policy,
        "cost_label": cost_label,
        "aggregate_return": format(
            sum(final_equities, Decimal(0)) / Decimal(5000) - Decimal(1), "f"
        ),
        "window_returns": {
            window.window_id: str(row["net_return"])
            for window, row in zip(HISTORICAL_WINDOWS, ordered, strict=True)
        },
        "window_pnl": {
            window.window_id: format(equity - STARTING_EQUITY, "f")
            for window, equity in zip(HISTORICAL_WINDOWS, final_equities, strict=True)
        },
        "weekly_returns": [format(value, "f") for value in weekly_returns],
        "weekly_pnl": {key: format(value, "f") for key, value in weekly_pnl.items()},
        "statistics": statistics,
        "bonferroni_adjusted_psr": format(bonferroni_adjusted_psr(psr), "f"),
        "maximum_drawdown": format(
            max(Decimal(str(row["maximum_drawdown"])) for row in ordered), "f"
        ),
        "annualized_one_way_turnover": format(
            sum((Decimal(str(row["turnover_sum"])) for row in ordered), Decimal(0))
            / Decimal("2.5"),
            "f",
        ),
        "decision_count": sum(int(row["decision_count"]) for row in ordered),
        "signal_count": sum(int(row.get("signal_count", 0)) for row in ordered),
        "nonflat_direction_count": sum(
            int(row["nonflat_direction_count"]) for row in ordered
        ),
        "funding_settlement_count": sum(
            int(row["funding_settlement_count"]) for row in ordered
        ),
        "equity_buffer_breach_count": sum(
            int(row["equity_buffer_breach_count"]) for row in ordered
        ),
        "forced_close_count": sum(int(row["forced_close_count"]) for row in ordered),
        "instrument_net_contributions": {
            instrument: format(value, "f")
            for instrument, value in sorted(contributions.items())
        },
        "component_totals": {
            component: format(
                sum(
                    (Decimal(str(row["component_totals"][component])) for row in ordered),
                    Decimal(0),
                ),
                "f",
            )
            for component in ("price_pnl", "funding_pnl", "costs")
        },
        "reconciliation_residual": format(
            sum(
                (Decimal(str(row["reconciliation_residual"])) for row in ordered),
                Decimal(0),
            ),
            "f",
        ),
    }


def _btc_beta(candidate: Sequence[Decimal], benchmark: Sequence[Decimal]) -> Decimal:
    if len(candidate) != EXPECTED_TOTAL_DECISIONS or len(benchmark) != len(candidate):
        raise C11AHistoricalReplayError("BTC beta return coverage is invalid")
    mean_candidate = sum(candidate, Decimal(0)) / Decimal(len(candidate))
    mean_benchmark = sum(benchmark, Decimal(0)) / Decimal(len(benchmark))
    covariance = sum(
        (
            (left - mean_candidate) * (right - mean_benchmark)
            for left, right in zip(candidate, benchmark, strict=True)
        ),
        Decimal(0),
    )
    variance = sum(
        ((value - mean_benchmark) ** 2 for value in benchmark), Decimal(0)
    )
    if variance <= 0 or not covariance.is_finite() or not variance.is_finite():
        raise C11AHistoricalReplayError("BTC beta regression is invalid")
    result = covariance / variance
    if not result.is_finite():
        raise C11AHistoricalReplayError("BTC beta is non-finite")
    return result


def summarize_h1_h5(windows: Mapping[str, Any]) -> dict[str, Any]:
    """Pool independent capital and apply every preregistered C11A gate."""

    expected_ids = {window.window_id for window in HISTORICAL_WINDOWS}
    if set(windows) != expected_ids:
        raise C11AHistoricalReplayError("C11A summary requires exactly H1-H5")
    selected_universes = {
        tuple(windows[window.window_id].get("selected_universe", ()))
        for window in HISTORICAL_WINDOWS
    }
    if len(selected_universes) != 1:
        raise C11AHistoricalReplayError("selected universe drift across H1-H5")
    pooled = {
        policy: {
            cost_label: _pool_policy(
                windows, policy=policy, cost_label=cost_label
            )
            for cost_label in COST_RATES
        }
        for policy in POLICIES
    }
    candidate = pooled[CANDIDATE_ID]["1.0x"]
    total_volatility = pooled["TotalVolatilityComparator"]["1.0x"]
    candidate_weekly = [Decimal(value) for value in candidate["weekly_returns"]]
    btc_weekly = [
        Decimal(str(value))
        for window in HISTORICAL_WINDOWS
        for value in windows[window.window_id]["btc_weekly_mark_returns"]
    ]
    btc_beta = _btc_beta(candidate_weekly, btc_weekly)
    instrument_pnl = [
        Decimal(value) for value in candidate["instrument_net_contributions"].values()
    ]
    window_pnl = [Decimal(value) for value in candidate["window_pnl"].values()]
    week_pnl = [Decimal(value) for value in candidate["weekly_pnl"].values()]
    instrument_share = _positive_share(instrument_pnl)
    window_share = _positive_share(window_pnl)
    week_share = _positive_share(week_pnl)
    top_three_week_share = _positive_share(week_pnl, count=3)
    candidate_sharpe = Decimal(
        str(candidate["statistics"]["annualized_weekly_sharpe"])
    )
    total_volatility_sharpe = Decimal(
        str(total_volatility["statistics"]["annualized_weekly_sharpe"])
    )
    gates = {
        "all_five_windows_positive": sum(
            Decimal(value) > 0 for value in candidate["window_returns"].values()
        )
        >= 5,
        "aggregate_1_0x_return_positive": Decimal(candidate["aggregate_return"]) > 0,
        "aggregate_1_5x_return_positive": Decimal(
            pooled[CANDIDATE_ID]["1.5x"]["aggregate_return"]
        )
        > 0,
        "aggregate_2_0x_return_nonnegative": Decimal(
            pooled[CANDIDATE_ID]["2.0x"]["aggregate_return"]
        )
        >= 0,
        "annualized_weekly_sharpe": candidate_sharpe >= Decimal("1.00"),
        "weekly_psr": Decimal(str(candidate["statistics"]["psr_probability"]))
        >= Decimal("0.95"),
        "bonferroni_adjusted_psr": Decimal(candidate["bonferroni_adjusted_psr"])
        >= Decimal("0.95"),
        "maximum_window_drawdown": Decimal(candidate["maximum_drawdown"])
        <= Decimal("0.15"),
        "absolute_btc_beta": abs(btc_beta) <= Decimal("0.20"),
        "zero_equity_buffer_breaches": candidate["equity_buffer_breach_count"] == 0,
        "required_decisions": candidate["decision_count"] == EXPECTED_TOTAL_DECISIONS,
        "required_nonflat_instrument_directions": candidate[
            "nonflat_direction_count"
        ]
        == EXPECTED_NONFLAT_DIRECTIONS,
        "annualized_one_way_turnover": Decimal(
            candidate["annualized_one_way_turnover"]
        )
        <= Decimal("18.0"),
        "positive_instrument_breadth": sum(value > 0 for value in instrument_pnl)
        >= 6,
        "instrument_concentration": instrument_share is not None
        and instrument_share <= Decimal("0.35"),
        "window_concentration": window_share is not None
        and window_share <= Decimal("0.40"),
        "week_concentration": week_share is not None
        and week_share <= Decimal("0.15"),
        "top_three_week_concentration": top_three_week_share is not None
        and top_three_week_share <= Decimal("0.35"),
        "return_delta_vs_total_volatility": Decimal(candidate["aggregate_return"])
        - Decimal(total_volatility["aggregate_return"])
        > 0,
        "sharpe_delta_vs_total_volatility": (
            candidate_sharpe - total_volatility_sharpe
        )
        >= Decimal("0.10"),
        "drawdown_no_worse_than_total_volatility": Decimal(
            candidate["maximum_drawdown"]
        )
        <= Decimal(total_volatility["maximum_drawdown"]),
        "turnover_no_greater_than_total_volatility": Decimal(
            candidate["annualized_one_way_turnover"]
        )
        <= Decimal(total_volatility["annualized_one_way_turnover"]),
    }
    selected = all(gates.values())
    return {
        "schema_version": 1,
        "stage": "C11A_H1_H5_POOLED_SUMMARY",
        "selected_universe": list(next(iter(selected_universes))),
        "pooled": pooled,
        "btc_weekly_mark_returns": [format(value, "f") for value in btc_weekly],
        "candidate_btc_beta": format(btc_beta, "f"),
        "concentration_metrics": {
            "maximum_positive_instrument_pnl_share": (
                None if instrument_share is None else format(instrument_share, "f")
            ),
            "maximum_positive_window_pnl_share": (
                None if window_share is None else format(window_share, "f")
            ),
            "maximum_positive_week_pnl_share": (
                None if week_share is None else format(week_share, "f")
            ),
            "maximum_top_three_positive_week_pnl_share": (
                None
                if top_three_week_share is None
                else format(top_three_week_share, "f")
            ),
        },
        "eligibility_gates": gates,
        "rejection_reasons": [key for key, passed in gates.items() if not passed],
        "selected_policy": CANDIDATE_ID if selected else None,
        "overall_economic_verdict": "ECONOMIC_PASS" if selected else "ECONOMIC_FAIL",
        "within_stage_candidate_count": 1,
        "declared_program_familywise_trial_count": EXPECTED_FAMILYWISE_TRIALS,
        "program_level_bonferroni_corrected": True,
        **safety_boundary(),
    }


__all__ = [
    "POLICIES",
    "C11AHistoricalReplayError",
    "build_signal",
    "evaluate_historical_window",
    "evaluate_historical_window_matrix",
    "summarize_h1_h5",
]
