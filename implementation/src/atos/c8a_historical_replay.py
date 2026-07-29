"""Deterministic C8A H1-H5 replay over retained official-public rows.

This is a pure historical calculation.  It has no network client, account or
order path, Paper/Shadow side effect, or Live transition.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from statistics import median
from typing import Any

from atos.c8a_contract import (
    COST_RATES,
    EXPECTED_INSTRUMENT_DIRECTIONS,
    EXPECTED_TOTAL_DECISIONS,
    INSTRUMENTS,
    MAXIMUM_ABS_BETA,
    MAXIMUM_ANNUALIZED_TURNOVER,
    MAXIMUM_INSTRUMENT_CONCENTRATION,
    MAXIMUM_TOP_THREE_WEEK_CONCENTRATION,
    MAXIMUM_WEEK_CONCENTRATION,
    MAXIMUM_WINDOW_CONCENTRATION,
    MAXIMUM_WINDOW_DRAWDOWN,
    MINIMUM_ANNUALIZED_SHARPE,
    MINIMUM_COMPARATOR_SHARPE_ADVANTAGE,
    MINIMUM_NONFLAT_DIRECTIONS,
    MINIMUM_POSITIVE_WINDOWS,
    MINIMUM_PSR,
    MINIMUM_SLEEVE_BUFFER,
    MINIMUM_WORST_WINDOW_RETURN,
    POLICIES,
    SIGNAL_CLOSE_COUNT,
    TARGET_ABS_WEIGHT,
)
from atos.c8a_historical_schedule import HOUR, WEEK, decision_times, iso, window_by_id


class C8AHistoricalReplayError(RuntimeError):
    """Raised when source rows or accounting cannot be proven complete."""


@dataclass(frozen=True)
class MomentumSignal:
    decision_time: str
    endpoints: Mapping[str, Mapping[str, Any]]
    momentum_7d: Mapping[str, float]
    directions: Mapping[str, int]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _time(value: Any, label: str, *, exact_hour: bool = False) -> datetime:
    try:
        parsed = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except (TypeError, ValueError) as exc:
        raise C8AHistoricalReplayError(f"invalid {label}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise C8AHistoricalReplayError(f"{label} must be timezone-aware")
    parsed = parsed.astimezone(UTC)
    if exact_hour and any((parsed.minute, parsed.second, parsed.microsecond)):
        raise C8AHistoricalReplayError(f"{label} must be aligned to an exact hour")
    return parsed


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise C8AHistoricalReplayError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C8AHistoricalReplayError(f"{label} must be numeric") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise C8AHistoricalReplayError(f"{label} must be {qualifier}")
    return result


def _indexed_prices(
    rows: Sequence[Mapping[str, Any]], *, field: str, label: str
) -> dict[datetime, float]:
    if not rows:
        raise C8AHistoricalReplayError(f"empty price series: {label}")
    output: dict[datetime, float] = {}
    prior: datetime | None = None
    for row in rows:
        stamp = _time(row.get("timestamp"), f"{label} timestamp", exact_hour=True)
        if prior is not None and stamp <= prior:
            raise C8AHistoricalReplayError(
                f"unordered or duplicate price series: {label}"
            )
        output[stamp] = _number(row.get(field), f"{label} {field}", positive=True)
        prior = stamp
    return output


def _indexed_funding(
    rows: Sequence[Mapping[str, Any]], *, label: str
) -> tuple[tuple[datetime, float], ...]:
    if not rows:
        raise C8AHistoricalReplayError(f"empty funding series: {label}")
    output: list[tuple[datetime, float]] = []
    prior: datetime | None = None
    for row in rows:
        stamp = _time(row.get("funding_time"), f"{label} funding timestamp")
        if prior is not None and stamp <= prior:
            raise C8AHistoricalReplayError(
                f"unordered or duplicate funding series: {label}"
            )
        output.append(
            (stamp, _number(row.get("realized_rate"), f"{label} realized rate"))
        )
        prior = stamp
    return tuple(output)


def _require_hours(
    values: Mapping[datetime, float],
    start: datetime,
    end_exclusive: datetime,
    label: str,
) -> None:
    expected = int((end_exclusive - start) / HOUR)
    if expected <= 0:
        raise C8AHistoricalReplayError(f"invalid required interval: {label}")
    for offset in range(expected):
        stamp = start + offset * HOUR
        if stamp not in values:
            raise C8AHistoricalReplayError(f"missing exact {label} hour: {iso(stamp)}")


def _predecessor_mark(
    values: Mapping[datetime, float], stamp: datetime, label: str
) -> tuple[datetime, float]:
    selected = (stamp - HOUR).replace(minute=0, second=0, microsecond=0)
    if selected not in values:
        raise C8AHistoricalReplayError(
            f"missing predecessor mark: {label} {iso(stamp)}"
        )
    if stamp - (selected + HOUR) > HOUR:
        raise C8AHistoricalReplayError(f"stale predecessor mark: {label} {iso(stamp)}")
    return selected, values[selected]


def build_signal(
    decision: datetime, mark_prices: Mapping[str, Mapping[datetime, float]]
) -> MomentumSignal:
    endpoints: dict[str, dict[str, Any]] = {}
    momentum: dict[str, float] = {}
    directions: dict[str, int] = {}
    first = decision - timedelta(hours=SIGNAL_CLOSE_COUNT + 1)
    latest = decision - 2 * HOUR
    for instrument in INSTRUMENTS:
        _require_hours(
            mark_prices[instrument], first, decision - HOUR, f"{instrument} signal"
        )
        oldest_price = mark_prices[instrument][first]
        latest_price = mark_prices[instrument][latest]
        value = latest_price / oldest_price - 1.0
        direction = 1 if value > 0 else -1 if value < 0 else 0
        endpoints[instrument] = {
            "oldest_timestamp": iso(first),
            "oldest_close_time": iso(first + HOUR),
            "oldest_close": oldest_price,
            "latest_timestamp": iso(latest),
            "latest_close_time": iso(latest + HOUR),
            "latest_close": latest_price,
            "close_count": SIGNAL_CLOSE_COUNT,
        }
        momentum[instrument] = value
        directions[instrument] = direction
    return MomentumSignal(iso(decision), endpoints, momentum, directions)


def _post_cost_targets(
    equity_before: float,
    current_values: Mapping[str, float],
    directions: Mapping[str, int],
    fee_rate: float,
) -> tuple[float, dict[str, float], dict[str, float]]:
    if (
        equity_before <= 0
        or set(current_values) != set(INSTRUMENTS)
        or set(directions) != set(INSTRUMENTS)
    ):
        raise C8AHistoricalReplayError("invalid rebalance state")
    weights = {
        instrument: int(directions[instrument]) * TARGET_ABS_WEIGHT
        for instrument in INSTRUMENTS
    }
    if any(directions[instrument] not in {-1, 0, 1} for instrument in INSTRUMENTS):
        raise C8AHistoricalReplayError("direction must be -1, 0, or 1")

    def residual(after: float) -> float:
        traded = sum(abs(weights[i] * after - current_values[i]) for i in INSTRUMENTS)
        return after + fee_rate * traded - equity_before

    low, high = 0.0, equity_before
    if residual(low) > 1e-12 or residual(high) < -1e-12:
        raise C8AHistoricalReplayError("post-cost rebalance root is not bracketed")
    for _ in range(200):
        mid = (low + high) / 2.0
        value = residual(mid)
        if abs(value) <= 1e-13:
            low = high = mid
            break
        if value > 0:
            high = mid
        else:
            low = mid
    after = (low + high) / 2.0
    targets = {instrument: weights[instrument] * after for instrument in INSTRUMENTS}
    fees = {
        instrument: fee_rate * abs(targets[instrument] - current_values[instrument])
        for instrument in INSTRUMENTS
    }
    if abs(after - (equity_before - sum(fees.values()))) > 1e-9:
        raise C8AHistoricalReplayError("post-cost rebalance does not reconcile")
    return after, targets, fees


def _maximum_drawdown(path: Sequence[float]) -> float:
    peak = path[0]
    maximum = 0.0
    for equity in path:
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak)
    return maximum


def _policy_directions(policy: str, signal: MomentumSignal) -> dict[str, int]:
    if policy == "candidate":
        return dict(signal.directions)
    if policy == "cash":
        return {instrument: 0 for instrument in INSTRUMENTS}
    if policy == "always_long_perpetual":
        return {instrument: 1 for instrument in INSTRUMENTS}
    raise C8AHistoricalReplayError(f"unknown policy: {policy!r}")


def _simulate(
    *,
    window_id: str,
    signals: Sequence[MomentumSignal],
    marks: Mapping[str, Mapping[datetime, float]],
    trades: Mapping[str, Mapping[datetime, float]],
    funding: Mapping[str, Sequence[tuple[datetime, float]]],
    policy: str,
    cost_label: str,
) -> dict[str, Any]:
    window = window_by_id(window_id)
    decisions = decision_times(window)
    if len(signals) != len(decisions) or cost_label not in COST_RATES:
        raise C8AHistoricalReplayError("signal count or cost label drift")
    fee_rate = COST_RATES[cost_label]
    states = {
        instrument: {
            "quantity": 0.0,
            "last_price": None,
            "sleeve_equity": 0.5,
            "locked_until": None,
            "pending_breach": False,
            "minimum_buffer": math.inf,
        }
        for instrument in INSTRUMENTS
    }
    components = {
        instrument: {"price_pnl": 0.0, "funding_pnl": 0.0, "costs": 0.0}
        for instrument in INSTRUMENTS
    }
    trade_events: list[dict[str, Any]] = []
    price_events: list[dict[str, Any]] = []
    funding_events: list[dict[str, Any]] = []
    hourly_states: list[dict[str, Any]] = []
    risk_events: list[dict[str, Any]] = []
    weekly_returns: list[float] = []
    weekly_contributions: list[float] = []
    weekly_equity: list[dict[str, Any]] = []
    turnover_ratios: list[float] = []
    equity_path = [1.0]
    requested_directions: list[dict[str, int]] = []
    executed_directions: list[dict[str, int]] = []
    prior_requested = {instrument: 0 for instrument in INSTRUMENTS}
    reversals = 0
    accounted_funding: set[tuple[str, datetime]] = set()
    funding_by_open: dict[str, dict[datetime, list[tuple[datetime, float]]]] = {
        instrument: {} for instrument in INSTRUMENTS
    }
    for instrument in INSTRUMENTS:
        for stamp, rate in funding[instrument]:
            bucket = stamp.replace(minute=0, second=0, microsecond=0)
            if bucket != stamp:
                bucket += HOUR
            funding_by_open[instrument].setdefault(bucket, []).append((stamp, rate))

    def total_equity() -> float:
        value = sum(float(states[i]["sleeve_equity"]) for i in INSTRUMENTS)
        if not math.isfinite(value) or value <= 0:
            raise C8AHistoricalReplayError("non-positive or non-finite total equity")
        return value

    def append_equity() -> None:
        equity_path.append(total_equity())

    def accrue_to_open(
        stamp: datetime, instruments: Sequence[str] = INSTRUMENTS
    ) -> None:
        for instrument in instruments:
            state = states[instrument]
            quantity = float(state["quantity"])
            opening = trades[instrument][stamp]
            last = state["last_price"]
            if quantity and last is not None:
                pnl = quantity * (opening - float(last))
                state["sleeve_equity"] = float(state["sleeve_equity"]) + pnl
                components[instrument]["price_pnl"] += pnl
                price_events.append(
                    {
                        "timestamp": iso(stamp),
                        "instrument": instrument,
                        "destination_kind": "TRADE_OPEN",
                        "quantity": quantity,
                        "from_price": float(last),
                        "to_price": opening,
                        "price_pnl": pnl,
                    }
                )
            state["last_price"] = opening
        append_equity()

    def close_for_risk(instrument: str, stamp: datetime) -> None:
        state = states[instrument]
        quantity = float(state["quantity"])
        if not quantity:
            state["pending_breach"] = False
            return
        equity_before = total_equity()
        value = quantity * trades[instrument][stamp]
        fee = fee_rate * abs(value)
        state["sleeve_equity"] = float(state["sleeve_equity"]) - fee
        components[instrument]["costs"] += fee
        turnover_ratios.append(abs(value) / equity_before)
        state["quantity"] = 0.0
        state["last_price"] = trades[instrument][stamp]
        state["pending_breach"] = False
        future = [decision for decision in decisions if decision > stamp]
        state["locked_until"] = future[0] if future else window.end_exclusive
        trade_events.append(
            {
                "timestamp": iso(stamp),
                "instrument": instrument,
                "kind": "RISK_CLOSE",
                "execution_price": trades[instrument][stamp],
                "equity_before": equity_before,
                "old_quantity": quantity,
                "target_quantity": 0.0,
                "old_signed_notional": value,
                "target_signed_notional": 0.0,
                "one_way_notional": abs(value),
                "cost": fee,
            }
        )
        append_equity()

    def check_buffer(instrument: str, stamp: datetime, mark_value: float) -> None:
        state = states[instrument]
        quantity = float(state["quantity"])
        if not quantity:
            return
        notional = abs(quantity * mark_value)
        buffer = float(state["sleeve_equity"]) / notional
        state["minimum_buffer"] = min(float(state["minimum_buffer"]), buffer)
        if buffer < MINIMUM_SLEEVE_BUFFER and not state["pending_breach"]:
            state["pending_breach"] = True
            risk_events.append(
                {
                    "breach_timestamp": iso(stamp),
                    "instrument": instrument,
                    "buffer": buffer,
                }
            )

    def apply_funding(instrument: str, stamp: datetime, rate: float) -> None:
        if (instrument, stamp) in accounted_funding:
            raise C8AHistoricalReplayError("funding settlement accounted twice")
        predecessor_time, predecessor = _predecessor_mark(
            marks[instrument], stamp, instrument
        )
        state = states[instrument]
        signed_notional = float(state["quantity"]) * predecessor
        pnl = -signed_notional * rate
        state["sleeve_equity"] = float(state["sleeve_equity"]) + pnl
        components[instrument]["funding_pnl"] += pnl
        accounted_funding.add((instrument, stamp))
        funding_events.append(
            {
                "timestamp": iso(stamp),
                "instrument": instrument,
                "rate": rate,
                "predecessor_mark_timestamp": iso(predecessor_time),
                "predecessor_mark_close_time": iso(predecessor_time + HOUR),
                "predecessor_mark": predecessor,
                "quantity": float(state["quantity"]),
                "signed_mark_notional": signed_notional,
                "funding_pnl": pnl,
                "buffer_after": (
                    float(state["sleeve_equity"]) / abs(signed_notional)
                    if signed_notional
                    else None
                ),
            }
        )
        check_buffer(instrument, stamp, predecessor)
        append_equity()

    # A settlement exactly at the independent window start is accounted while flat.
    for instrument in INSTRUMENTS:
        for stamp, rate in funding[instrument]:
            if stamp == window.first_scored_decision:
                apply_funding(instrument, stamp, rate)

    for week_index, (decision, signal) in enumerate(
        zip(decisions, signals, strict=True)
    ):
        week_start_equity = total_equity()
        requested = _policy_directions(policy, signal)
        requested_directions.append(dict(requested))
        for instrument in INSTRUMENTS:
            if (
                requested[instrument]
                and prior_requested[instrument]
                and requested[instrument] == -prior_requested[instrument]
            ):
                reversals += 1
            prior_requested[instrument] = requested[instrument]
        actual = dict(requested)
        for instrument in INSTRUMENTS:
            locked = states[instrument]["locked_until"]
            if locked is not None and decision < locked:
                actual[instrument] = 0
            elif locked is not None and decision >= locked:
                states[instrument]["locked_until"] = None
        executed_directions.append(dict(actual))

        accrue_to_open(decision)
        equity_before = total_equity()
        current = {
            instrument: float(states[instrument]["quantity"])
            * trades[instrument][decision]
            for instrument in INSTRUMENTS
        }
        _, targets, fees = _post_cost_targets(equity_before, current, actual, fee_rate)
        for instrument in INSTRUMENTS:
            opening = trades[instrument][decision]
            traded = abs(targets[instrument] - current[instrument])
            states[instrument]["sleeve_equity"] = (
                float(states[instrument]["sleeve_equity"]) - fees[instrument]
            )
            components[instrument]["costs"] += fees[instrument]
            states[instrument]["quantity"] = targets[instrument] / opening
            states[instrument]["last_price"] = opening
            turnover_ratios.append(traded / equity_before)
            trade_events.append(
                {
                    "timestamp": iso(decision),
                    "instrument": instrument,
                    "kind": "SCHEDULED_REBALANCE",
                    "execution_price": opening,
                    "equity_before": equity_before,
                    "old_quantity": current[instrument] / opening,
                    "target_quantity": targets[instrument] / opening,
                    "requested_direction": requested[instrument],
                    "executed_direction": actual[instrument],
                    "old_signed_notional": current[instrument],
                    "target_signed_notional": targets[instrument],
                    "one_way_notional": traded,
                    "cost": fees[instrument],
                }
            )
        append_equity()

        week_end = decision + WEEK
        current_hour = decision
        while current_hour < week_end:
            # OKX ts is candle open; this mark becomes observable one hour later.
            mark_close_time = current_hour + HOUR
            next_hour = mark_close_time
            # A delayed settlement inside the candle precedes its close.
            for instrument in INSTRUMENTS:
                for stamp, rate in funding_by_open[instrument].get(next_hour, []):
                    if current_hour < stamp < next_hour:
                        apply_funding(instrument, stamp, rate)
            for instrument in INSTRUMENTS:
                state = states[instrument]
                mark = marks[instrument][current_hour]
                quantity = float(state["quantity"])
                last = state["last_price"]
                if quantity and last is not None:
                    pnl = quantity * (mark - float(last))
                    state["sleeve_equity"] = float(state["sleeve_equity"]) + pnl
                    components[instrument]["price_pnl"] += pnl
                    price_events.append(
                        {
                            "timestamp": iso(mark_close_time),
                            "source_timestamp": iso(current_hour),
                            "instrument": instrument,
                            "destination_kind": "MARK_CLOSE",
                            "quantity": quantity,
                            "from_price": float(last),
                            "to_price": mark,
                            "price_pnl": pnl,
                        }
                    )
                state["last_price"] = mark
                check_buffer(instrument, mark_close_time, mark)
            append_equity()
            hourly_states.append(
                {
                    "timestamp": iso(mark_close_time),
                    "source_timestamp": iso(current_hour),
                    "equity": total_equity(),
                    "sleeves": {
                        instrument: {
                            "equity": float(states[instrument]["sleeve_equity"]),
                            "quantity": float(states[instrument]["quantity"]),
                            "mark_price": marks[instrument][current_hour],
                            "signed_mark_notional": float(
                                states[instrument]["quantity"]
                            )
                            * marks[instrument][current_hour],
                            "buffer": (
                                float(states[instrument]["sleeve_equity"])
                                / abs(
                                    float(states[instrument]["quantity"])
                                    * marks[instrument][current_hour]
                                )
                                if float(states[instrument]["quantity"])
                                else None
                            ),
                        }
                        for instrument in INSTRUMENTS
                    },
                }
            )
            # A settlement exactly at the close uses that completed mark and
            # still precedes the boundary trade.
            for instrument in INSTRUMENTS:
                for stamp, rate in funding_by_open[instrument].get(next_hour, []):
                    if stamp == next_hour:
                        apply_funding(instrument, stamp, rate)
            accrue_to_open(next_hour)
            for instrument in INSTRUMENTS:
                if states[instrument]["pending_breach"]:
                    close_for_risk(instrument, next_hour)
            current_hour = next_hour

        if week_index == len(decisions) - 1:
            # Terminal close at the exclusive-end open; price was accrued above.
            for instrument in INSTRUMENTS:
                state = states[instrument]
                quantity = float(state["quantity"])
                value = quantity * trades[instrument][week_end]
                if quantity:
                    equity_before = total_equity()
                    fee = fee_rate * abs(value)
                    state["sleeve_equity"] = float(state["sleeve_equity"]) - fee
                    components[instrument]["costs"] += fee
                    turnover_ratios.append(abs(value) / equity_before)
                    trade_events.append(
                        {
                            "timestamp": iso(week_end),
                            "instrument": instrument,
                            "kind": "TERMINAL_CLOSE",
                            "execution_price": trades[instrument][week_end],
                            "equity_before": equity_before,
                            "old_quantity": quantity,
                            "target_quantity": 0.0,
                            "old_signed_notional": value,
                            "target_signed_notional": 0.0,
                            "one_way_notional": abs(value),
                            "cost": fee,
                        }
                    )
                    state["quantity"] = 0.0
                    state["last_price"] = trades[instrument][week_end]
                    append_equity()
        week_end_equity = total_equity()
        weekly_returns.append(week_end_equity / week_start_equity - 1.0)
        weekly_contributions.append(week_end_equity - week_start_equity)
        weekly_equity.append(
            {
                "decision_time": iso(decision),
                "end_exclusive": iso(week_end),
                "start_equity": week_start_equity,
                "end_equity": week_end_equity,
                "weekly_return": weekly_returns[-1],
            }
        )

    expected_funding = {
        (instrument, stamp)
        for instrument in INSTRUMENTS
        for stamp, _ in funding[instrument]
        if window.first_scored_decision <= stamp <= window.end_exclusive
    }
    unaccounted = expected_funding - accounted_funding
    if unaccounted:
        raise C8AHistoricalReplayError("unaccounted funding settlement")
    final_equity = total_equity()
    price_pnl = sum(value["price_pnl"] for value in components.values())
    funding_pnl = sum(value["funding_pnl"] for value in components.values())
    costs = sum(value["costs"] for value in components.values())
    if abs(final_equity - (1.0 + price_pnl + funding_pnl - costs)) > 1e-8:
        raise C8AHistoricalReplayError("replay accounting does not reconcile")
    if abs(math.prod(1.0 + value for value in weekly_returns) - final_equity) > 1e-8:
        raise C8AHistoricalReplayError("weekly returns do not compound to final equity")
    minimum_buffer = min(float(states[i]["minimum_buffer"]) for i in INSTRUMENTS)
    return {
        "policy": policy,
        "cost_label": cost_label,
        "cost_rate": fee_rate,
        "initial_equity": 1.0,
        "final_equity": final_equity,
        "net_return": final_equity - 1.0,
        "gross_price_pnl": price_pnl,
        "funding_pnl": funding_pnl,
        "costs": costs,
        "one_way_turnover_ratio": sum(turnover_ratios),
        "maximum_drawdown": _maximum_drawdown(equity_path),
        "minimum_sleeve_buffer": minimum_buffer
        if math.isfinite(minimum_buffer)
        else None,
        "margin_buffer_breach_count": len(risk_events),
        "missing_decision_count": 0,
        "unaccounted_funding_settlement_count": 0,
        "weekly_returns": weekly_returns,
        "weekly_contributions": weekly_contributions,
        "weekly_equity": weekly_equity,
        "instrument_contributions": {
            instrument: components[instrument]["price_pnl"]
            + components[instrument]["funding_pnl"]
            - components[instrument]["costs"]
            for instrument in INSTRUMENTS
        },
        "requested_directions": requested_directions,
        "executed_directions": executed_directions,
        "long_direction_count": sum(
            value > 0 for item in requested_directions for value in item.values()
        ),
        "short_direction_count": sum(
            value < 0 for item in requested_directions for value in item.values()
        ),
        "flat_direction_count": sum(
            value == 0 for item in requested_directions for value in item.values()
        ),
        "reversal_count": reversals,
        "trade_events": trade_events,
        "price_events": price_events,
        "funding_events": funding_events,
        "risk_events": risk_events,
        "hourly_equity": hourly_states,
        "complete_equity_path": equity_path,
    }


def evaluate_historical_window(
    *,
    window_id: str,
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    if (
        set(mark_rows) != set(INSTRUMENTS)
        or set(trade_rows) != set(INSTRUMENTS)
        or set(funding_rows) != set(INSTRUMENTS)
    ):
        raise C8AHistoricalReplayError("source instrument set drift")
    window = window_by_id(window_id)
    decisions = decision_times(window)
    marks = {
        instrument: _indexed_prices(
            mark_rows[instrument], field="close", label=f"{instrument} marks"
        )
        for instrument in INSTRUMENTS
    }
    trades = {
        instrument: _indexed_prices(
            trade_rows[instrument], field="open", label=f"{instrument} trades"
        )
        for instrument in INSTRUMENTS
    }
    funding = {
        instrument: _indexed_funding(funding_rows[instrument], label=instrument)
        for instrument in INSTRUMENTS
    }
    for instrument in INSTRUMENTS:
        _require_hours(
            marks[instrument],
            decisions[0] - timedelta(hours=SIGNAL_CLOSE_COUNT + 1),
            window.end_exclusive,
            f"{instrument} mark",
        )
        _require_hours(
            trades[instrument],
            decisions[0],
            window.end_exclusive + HOUR,
            f"{instrument} trade",
        )
        selected = [
            stamp
            for stamp, _ in funding[instrument]
            if window.first_scored_decision <= stamp <= window.end_exclusive
        ]
        if not selected:
            raise C8AHistoricalReplayError(
                f"funding coverage is empty inside window: {instrument}"
            )
        points = [window.first_scored_decision, *selected, window.end_exclusive]
        if any(
            right - left > timedelta(hours=8, minutes=1)
            for left, right in pairwise(points)
        ):
            raise C8AHistoricalReplayError(
                f"funding coverage gap exceeds tolerance: {instrument}"
            )
    signals = tuple(build_signal(decision, marks) for decision in decisions)
    replays = {
        policy: {
            cost_label: _simulate(
                window_id=window_id,
                signals=signals,
                marks=marks,
                trades=trades,
                funding=funding,
                policy=policy,
                cost_label=cost_label,
            )
            for cost_label in COST_RATES
        }
        for policy in POLICIES
    }
    btc_weekly_mark_returns = []
    for decision in decisions:
        start = marks[INSTRUMENTS[0]][decision - 2 * HOUR]
        end = marks[INSTRUMENTS[0]][decision + WEEK - 2 * HOUR]
        btc_weekly_mark_returns.append(end / start - 1.0)
    return {
        "schema_version": 1,
        "stage": "C8A_HISTORICAL_WINDOW_REPLAY",
        "window": window.to_dict(),
        "decision_count": len(decisions),
        "signals": [signal.to_dict() for signal in signals],
        "btc_weekly_mark_returns": btc_weekly_mark_returns,
        "replays": replays,
        "paper_side_effect": False,
        "shadow_side_effect": False,
        "live_state": "LIVE_FORBIDDEN",
    }


def _sample_statistics(values: Sequence[float]) -> dict[str, float]:
    n = len(values)
    if n < 2:
        return {"annualized_sharpe": 0.0, "psr": 0.0}
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    if not math.isfinite(variance) or variance <= 0:
        return {"annualized_sharpe": 0.0, "psr": 0.0}
    std = math.sqrt(variance)
    raw_sharpe = mean / std
    m2 = sum((value - mean) ** 2 for value in values) / n
    m3 = sum((value - mean) ** 3 for value in values) / n
    m4 = sum((value - mean) ** 4 for value in values) / n
    skew = (
        (math.sqrt(n * (n - 1)) / (n - 2)) * (m3 / (m2**1.5))
        if n > 2 and m2 > 0
        else 0.0
    )
    kurtosis = m4 / (m2 * m2) if m2 > 0 else 3.0
    radicand = (
        1.0 - skew * raw_sharpe + ((kurtosis - 1.0) / 4.0) * raw_sharpe * raw_sharpe
    ) / (n - 1)
    psr = (
        0.0
        if not math.isfinite(radicand) or radicand <= 0
        else 0.5 * (1.0 + math.erf((raw_sharpe / math.sqrt(radicand)) / math.sqrt(2.0)))
    )
    return {
        "weekly_mean": mean,
        "weekly_sample_std": std,
        "weekly_sharpe_raw": raw_sharpe,
        "annualized_sharpe": raw_sharpe * math.sqrt(52.0),
        "sample_skewness": skew,
        "ordinary_kurtosis": kurtosis,
        "psr": psr,
    }


def _beta(candidate: Sequence[float], benchmark: Sequence[float]) -> float:
    if len(candidate) != len(benchmark) or len(candidate) < 2:
        raise C8AHistoricalReplayError("beta inputs are incomplete")
    mean_x = sum(benchmark) / len(benchmark)
    mean_y = sum(candidate) / len(candidate)
    denominator = sum((value - mean_x) ** 2 for value in benchmark)
    if denominator <= 0 or not math.isfinite(denominator):
        raise C8AHistoricalReplayError("BTC weekly variance is zero or non-finite")
    value = (
        sum(
            (x - mean_x) * (y - mean_y)
            for x, y in zip(benchmark, candidate, strict=True)
        )
        / denominator
    )
    if not math.isfinite(value):
        raise C8AHistoricalReplayError("strategy beta is non-finite")
    return value


def _concentration(values: Sequence[float], count: int = 1) -> float:
    positive = sorted((value for value in values if value > 0), reverse=True)
    total = sum(positive)
    return math.inf if total <= 0 else sum(positive[:count]) / total


def _pooled_policy(
    windows: Mapping[str, Any], policy: str, cost_label: str
) -> dict[str, Any]:
    ordered = [
        windows[f"H{index}"]["replays"][policy][cost_label] for index in range(1, 6)
    ]
    weekly = [value for replay in ordered for value in replay["weekly_returns"]]
    stats = _sample_statistics(weekly)
    return {
        "policy": policy,
        "cost_label": cost_label,
        "window_net_returns": [replay["net_return"] for replay in ordered],
        "pooled_net_return": math.prod(1.0 + replay["net_return"] for replay in ordered)
        - 1.0,
        "weekly_returns": weekly,
        "statistics": stats,
        "maximum_window_drawdown": max(
            replay["maximum_drawdown"] for replay in ordered
        ),
        "margin_buffer_breach_count": sum(
            replay["margin_buffer_breach_count"] for replay in ordered
        ),
        "annualized_one_way_turnover": sum(
            replay["one_way_turnover_ratio"] for replay in ordered
        )
        / 2.5,
        "instrument_contributions": {
            instrument: sum(
                replay["instrument_contributions"][instrument] for replay in ordered
            )
            for instrument in INSTRUMENTS
        },
        "weekly_contributions": [
            value for replay in ordered for value in replay["weekly_contributions"]
        ],
        "flat_direction_count": sum(
            replay["flat_direction_count"] for replay in ordered
        ),
        "missing_decision_count": sum(
            replay["missing_decision_count"] for replay in ordered
        ),
        "unaccounted_funding_settlement_count": sum(
            replay["unaccounted_funding_settlement_count"] for replay in ordered
        ),
    }


def summarize_h1_h5(windows: Mapping[str, Any]) -> dict[str, Any]:
    if set(windows) != {"H1", "H2", "H3", "H4", "H5"}:
        raise C8AHistoricalReplayError("exactly H1-H5 are required")
    candidate = {
        cost: _pooled_policy(windows, "candidate", cost) for cost in COST_RATES
    }
    comparator = {
        cost: _pooled_policy(windows, "always_long_perpetual", cost)
        for cost in COST_RATES
    }
    expected = candidate["1.0x"]
    expected_comparator = comparator["1.0x"]
    btc = [
        value
        for index in range(1, 6)
        for value in windows[f"H{index}"]["btc_weekly_mark_returns"]
    ]
    strategy_beta = _beta(expected["weekly_returns"], btc)
    window_returns = expected["window_net_returns"]
    instrument_concentration = _concentration(
        list(expected["instrument_contributions"].values())
    )
    window_concentration = _concentration(window_returns)
    week_concentration = _concentration(expected["weekly_contributions"])
    top_three_week_concentration = _concentration(expected["weekly_contributions"], 3)
    nonflat = EXPECTED_INSTRUMENT_DIRECTIONS - expected["flat_direction_count"]
    gates = {
        "positive_windows": sum(value > 0 for value in window_returns)
        >= MINIMUM_POSITIVE_WINDOWS,
        "median_window_positive": median(window_returns) > 0,
        "worst_window": min(window_returns) > MINIMUM_WORST_WINDOW_RETURN,
        "pooled_expected_positive": expected["pooled_net_return"] > 0,
        "pooled_1_5x_positive": candidate["1.5x"]["pooled_net_return"] > 0,
        "pooled_2x_nonnegative": candidate["2.0x"]["pooled_net_return"] >= 0,
        "annualized_sharpe": expected["statistics"]["annualized_sharpe"]
        >= MINIMUM_ANNUALIZED_SHARPE,
        "psr": expected["statistics"]["psr"] >= MINIMUM_PSR,
        "maximum_drawdown": expected["maximum_window_drawdown"]
        <= MAXIMUM_WINDOW_DRAWDOWN,
        "absolute_beta": abs(strategy_beta) <= MAXIMUM_ABS_BETA,
        "zero_margin_breaches": expected["margin_buffer_breach_count"] == 0,
        "zero_missing_decisions": expected["missing_decision_count"] == 0,
        "zero_unaccounted_funding": expected["unaccounted_funding_settlement_count"]
        == 0,
        "exact_decision_count": sum(
            windows[f"H{index}"]["decision_count"] for index in range(1, 6)
        )
        == EXPECTED_TOTAL_DECISIONS,
        "nonflat_breadth": nonflat >= MINIMUM_NONFLAT_DIRECTIONS,
        "turnover": expected["annualized_one_way_turnover"]
        <= MAXIMUM_ANNUALIZED_TURNOVER,
        "both_instruments_positive": all(
            value > 0 for value in expected["instrument_contributions"].values()
        ),
        "instrument_concentration": instrument_concentration
        <= MAXIMUM_INSTRUMENT_CONCENTRATION,
        "window_concentration": window_concentration <= MAXIMUM_WINDOW_CONCENTRATION,
        "week_concentration": week_concentration <= MAXIMUM_WEEK_CONCENTRATION,
        "top_three_week_concentration": top_three_week_concentration
        <= MAXIMUM_TOP_THREE_WEEK_CONCENTRATION,
        "beats_always_long_return": expected["pooled_net_return"]
        > expected_comparator["pooled_net_return"],
        "beats_always_long_sharpe": expected["statistics"]["annualized_sharpe"]
        >= expected_comparator["statistics"]["annualized_sharpe"]
        + MINIMUM_COMPARATOR_SHARPE_ADVANTAGE,
        "drawdown_no_worse_than_always_long": expected["maximum_window_drawdown"]
        <= expected_comparator["maximum_window_drawdown"],
    }
    return {
        "schema_version": 1,
        "stage": "C8A_H1_H5_POOLED_SUMMARY",
        "candidate": candidate,
        "always_long_perpetual_comparator": comparator,
        "cash_comparator_pooled_net_return": 0.0,
        "strategy_beta_to_btc": strategy_beta,
        "nonflat_instrument_directions": nonflat,
        "concentration": {
            "maximum_positive_instrument_share": instrument_concentration,
            "maximum_positive_window_share": window_concentration,
            "maximum_positive_week_share": week_concentration,
            "top_three_positive_week_share": top_three_week_concentration,
        },
        "gates": gates,
        "overall_economic_verdict": "ECONOMIC_PASS"
        if all(gates.values())
        else "ECONOMIC_FAIL",
        "within_stage_candidate_count": 1,
        "weekly_statistic": "PSR_NOT_DSR",
        "program_level_sequential_history_corrected": False,
        "historical_data_status": "HISTORICAL_DEVELOPMENT_ONLY",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
