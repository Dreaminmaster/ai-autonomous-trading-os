"""Physically separate source-ordered recomputation for C9A evidence."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from statistics import mean, stdev
from typing import Any

from scipy.stats import kurtosis, norm, skew

from atos.c9a_contract import (
    COLLATERAL_CAPITAL_FRACTION,
    COST_RATES,
    FUNDING_LOOKBACK,
    HOUR,
    MAXIMUM_ENTRY_ABS_BASIS,
    MAXIMUM_RISK_ABS_BASIS,
    MINIMUM_COLLATERAL_BUFFER,
    MINIMUM_FUNDING_SUM,
    MINIMUM_POSITIVE_SHARE,
    RECONCILIATION_TOLERANCE,
    RESIZING_BAND,
    SOLVER_ITERATIONS,
    SPOT_CAPITAL_FRACTION,
    SPOT_INSTRUMENTS,
    SPOT_TO_SWAP,
    STARTING_EQUITY,
    SWAP_INSTRUMENTS,
    decimal_value,
    iso,
    safety_boundary,
)
from atos.c9a_historical_schedule import window_by_id

ZERO = Decimal(0)
ONE = Decimal(1)
COMPONENTS = (
    "spot_price_pnl",
    "perpetual_price_pnl",
    "funding_pnl",
    "spot_cost",
    "swap_cost",
)


class C9AHistoricalIndependentError(RuntimeError):
    """Raised when independent recomputation cannot be completed."""


def _time(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise C9AHistoricalIndependentError(f"invalid timestamp: {value!r}") from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise C9AHistoricalIndependentError("timestamp must be UTC")
    return result


def _prices(
    rows: Sequence[Mapping[str, Any]], fields: tuple[str, ...]
) -> dict[datetime, dict[str, Decimal]]:
    output = {}
    previous = None
    for row in rows:
        stamp = _time(row.get("timestamp"))
        if previous is not None and stamp <= previous:
            raise C9AHistoricalIndependentError(
                "source candles are duplicate or unordered"
            )
        previous = stamp
        output[stamp] = {
            field: decimal_value(row.get(field), f"independent {field}", positive=True)
            for field in fields
        }
    return output


def _funding(rows: Sequence[Mapping[str, Any]]) -> tuple[tuple[datetime, Decimal], ...]:
    output = []
    previous = None
    for row in rows:
        stamp = _time(row.get("funding_time"))
        if previous is not None and stamp <= previous:
            raise C9AHistoricalIndependentError("funding is duplicate or unordered")
        previous = stamp
        output.append((stamp, decimal_value(row.get("realized_rate"), "funding rate")))
    return tuple(output)


def _close(
    left: Any, right: Any, tolerance: Decimal = RECONCILIATION_TOLERANCE
) -> bool:
    try:
        return abs(Decimal(str(left)) - Decimal(str(right))) <= tolerance
    except Exception:  # noqa: BLE001
        return False


def _independent_signal(
    stamp: datetime,
    *,
    spot_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    marks: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    funding: Mapping[str, tuple[tuple[datetime, Decimal], ...]],
) -> dict[str, Any]:
    output = {}
    for spot in SPOT_INSTRUMENTS:
        swap = SPOT_TO_SWAP[spot]
        values = [
            rate
            for when, rate in funding[swap]
            if stamp - FUNDING_LOOKBACK <= when < stamp
        ]
        if not values:
            raise C9AHistoricalIndependentError("independent funding lookback is empty")
        total = sum(values, ZERO)
        positive = sum(value > 0 for value in values)
        share = Decimal(positive) / Decimal(len(values))
        source = stamp - 2 * HOUR
        spot_close = spot_trade[spot][source]["close"]
        mark_close = marks[swap][source]["close"]
        basis = mark_close / spot_close - ONE
        output[spot] = {
            "swap_instrument": swap,
            "lookback_start_inclusive": iso(stamp - FUNDING_LOOKBACK),
            "lookback_end_exclusive": iso(stamp),
            "settlement_count": len(values),
            "positive_settlement_count": positive,
            "funding_sum_28d": str(total),
            "positive_funding_share_28d": str(share),
            "basis_source_timestamp": iso(source),
            "basis_source_close_time": iso(source + HOUR),
            "spot_close": str(spot_close),
            "mark_close": str(mark_close),
            "basis": str(basis),
            "eligible": total > MINIMUM_FUNDING_SUM
            and share >= MINIMUM_POSITIVE_SHARE
            and abs(basis) <= MAXIMUM_ENTRY_ABS_BASIS,
        }
    return output


def _dict_equal(expected: Any, observed: Any) -> bool:
    if isinstance(expected, Mapping) and isinstance(observed, Mapping):
        return set(expected) == set(observed) and all(
            _dict_equal(expected[key], observed[key]) for key in expected
        )
    if isinstance(expected, list) and isinstance(observed, list):
        return len(expected) == len(observed) and all(
            _dict_equal(left, right)
            for left, right in zip(expected, observed, strict=True)
        )
    if isinstance(expected, str) and isinstance(observed, str):
        try:
            return _close(Decimal(expected), Decimal(observed))
        except Exception:  # noqa: BLE001
            return expected == observed
    return expected == observed


def _independent_plan(
    states: Mapping[str, Mapping[str, Any]],
    *,
    eligible: Sequence[str],
    total_equity: Decimal,
    spot_opens: Mapping[str, Decimal],
    timestamp: datetime,
) -> dict[str, dict[str, Any]]:
    selected = set(eligible)
    sleeve_capital = total_equity / Decimal(len(selected)) if selected else ZERO
    output = {}
    for spot in SPOT_INSTRUMENTS:
        state = states[spot]
        blocked_until = state["blocked_until"]
        blocked = blocked_until is not None and timestamp < blocked_until
        active = state["q"] > 0
        if spot not in selected or blocked:
            action = "CLOSE" if active else ("BLOCKED" if blocked else "HOLD_CASH")
            output[spot] = {
                "action": action,
                "raw_sleeve_capital": ZERO,
                "raw_spot_notional": ZERO,
                "raw_margin": ZERO,
            }
            continue
        raw_spot = sleeve_capital * SPOT_CAPITAL_FRACTION
        current_spot = state["q"] * spot_opens[spot]
        if not active:
            action = "OPEN"
        elif abs(raw_spot - current_spot) < RESIZING_BAND * current_spot:
            action = "HOLD"
        else:
            action = "RESIZE"
        output[spot] = {
            "action": action,
            "raw_sleeve_capital": sleeve_capital,
            "raw_spot_notional": raw_spot,
            "raw_margin": sleeve_capital * COLLATERAL_CAPITAL_FRACTION,
        }
    return output


def _independent_scale(
    states: Mapping[str, Mapping[str, Any]],
    *,
    cash: Decimal,
    plan: Mapping[str, Mapping[str, Any]],
    spot_opens: Mapping[str, Decimal],
    swap_opens: Mapping[str, Decimal],
    cost_rate: Decimal,
) -> Decimal:
    def constraints(scale: Decimal, *, flat_zero: bool = False) -> tuple[bool, bool]:
        free_cash = cash
        margin_ok = True
        for spot in SPOT_INSTRUMENTS:
            state = states[spot]
            if plan[spot]["action"] != "CLOSE" or state["q"] <= 0:
                continue
            spot_fee = state["q"] * spot_opens[spot] * cost_rate
            swap_fee = state["q"] * swap_opens[spot] * cost_rate
            remaining_margin = state["margin"] - swap_fee
            margin_ok &= remaining_margin >= 0
            free_cash += state["q"] * spot_opens[spot] - spot_fee + remaining_margin
        for spot in SPOT_INSTRUMENTS:
            if plan[spot]["action"] not in {"OPEN", "RESIZE"}:
                continue
            state = states[spot]
            target_notional = Decimal(str(plan[spot]["raw_spot_notional"])) * scale
            target_quantity = (
                target_notional / spot_opens[spot] if target_notional else ZERO
            )
            target_margin = Decimal(str(plan[spot]["raw_margin"])) * scale
            spot_fee = abs(target_quantity - state["q"]) * spot_opens[spot] * cost_rate
            swap_fee = abs(target_quantity - state["q"]) * swap_opens[spot] * cost_rate
            if target_quantity == 0 and flat_zero:
                remaining_margin = state["margin"] - swap_fee
                margin_ok &= remaining_margin >= 0
                free_cash += state["q"] * spot_opens[spot] - spot_fee + remaining_margin
            else:
                free_cash -= (
                    (target_quantity - state["q"]) * spot_opens[spot]
                    + spot_fee
                    + target_margin
                    - state["margin"]
                )
                margin_ok &= target_margin - swap_fee > 0
        return free_cash >= -RECONCILIATION_TOLERANCE, margin_ok

    def unavailable(flat_feasible: bool) -> Decimal:
        if flat_feasible:
            return ZERO
        raise C9AHistoricalIndependentError("no independently feasible target scale")

    with localcontext() as context:
        context.prec = 60
        flat_feasible = all(constraints(ZERO, flat_zero=True))
        if constraints(ONE)[0]:
            cash_upper = ONE
        elif not constraints(ZERO)[0]:
            return unavailable(flat_feasible)
        else:
            cash_low, cash_high = ZERO, ONE
            for _ in range(SOLVER_ITERATIONS):
                middle = (cash_low + cash_high) / Decimal(2)
                if constraints(middle)[0]:
                    cash_low = middle
                else:
                    cash_high = middle
            cash_upper = cash_low

        margin_lower = ZERO
        margin_upper = ONE
        for spot in SPOT_INSTRUMENTS:
            if plan[spot]["action"] not in {"OPEN", "RESIZE"}:
                continue
            raw_notional = Decimal(str(plan[spot]["raw_spot_notional"]))
            raw_margin = Decimal(str(plan[spot]["raw_margin"]))
            if raw_notional <= 0 or raw_margin <= 0:
                return unavailable(flat_feasible)
            quantity_slope = raw_notional / spot_opens[spot]
            fee_per_quantity = swap_opens[spot] * cost_rate
            fee_slope = fee_per_quantity * quantity_slope
            lower = fee_per_quantity * states[spot]["q"] / (raw_margin + fee_slope)
            margin_lower = max(margin_lower, lower)
            if fee_slope > raw_margin:
                upper = fee_per_quantity * states[spot]["q"] / (fee_slope - raw_margin)
                margin_upper = min(margin_upper, upper)
            elif fee_slope == raw_margin and states[spot]["q"] == 0:
                return unavailable(flat_feasible)

        upper = min(ONE, cash_upper, margin_upper)
        if upper <= margin_lower:
            return unavailable(flat_feasible)
        interior = (margin_lower + upper) / Decimal(2)
        if not all(constraints(interior)):
            return unavailable(flat_feasible)
        if all(constraints(upper)):
            return upper
        low, high = interior, upper
        for _ in range(SOLVER_ITERATIONS):
            middle = (low + high) / Decimal(2)
            if all(constraints(middle)):
                low = middle
            else:
                high = middle
        return low if all(constraints(low)) else unavailable(flat_feasible)


def _audit_carry(
    replay: Mapping[str, Any],
    *,
    spot_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    swap_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    marks: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    funding: Mapping[str, tuple[tuple[datetime, Decimal], ...]],
) -> dict[str, Any]:
    with localcontext() as context:
        context.prec = 60
        return _audit_carry_at_precision(
            replay,
            spot_trade=spot_trade,
            swap_trade=swap_trade,
            marks=marks,
            funding=funding,
        )


def _audit_carry_at_precision(
    replay: Mapping[str, Any],
    *,
    spot_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    swap_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    marks: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    funding: Mapping[str, tuple[tuple[datetime, Decimal], ...]],
) -> dict[str, Any]:
    window = window_by_id(str(replay.get("window_id")))
    policy = str(replay.get("policy"))
    cost_label = str(replay.get("cost_label"))
    if policy not in {"candidate", "always_on"} or cost_label not in COST_RATES:
        raise C9AHistoricalIndependentError("independent replay identity drift")
    rate = COST_RATES[cost_label]
    states = {
        spot: {
            "q": ZERO,
            "margin": ZERO,
            "last_spot": None,
            "last_perp": None,
            "pending": False,
            "blocked_until": None,
            "buffer_breaches": 0,
            "hedge_mismatches": 0,
            "components": {name: ZERO for name in COMPONENTS},
        }
        for spot in SPOT_INSTRUMENTS
    }
    cash = STARTING_EQUITY
    active_funding_count = 0
    gross_funding_receipts = ZERO
    gross_funding_payments = ZERO
    checks = defaultdict(lambda: True)

    def components() -> dict[str, Decimal]:
        return {
            name: sum((state["components"][name] for state in states.values()), ZERO)
            for name in COMPONENTS
        }

    def net(values: Mapping[str, Decimal]) -> Decimal:
        return (
            values["spot_price_pnl"]
            + values["perpetual_price_pnl"]
            + values["funding_pnl"]
            - values["spot_cost"]
            - values["swap_cost"]
        )

    def equity() -> Decimal:
        value = cash + sum(
            (
                state["q"] * state["last_spot"] + state["margin"]
                for state in states.values()
                if state["last_spot"] is not None
            ),
            ZERO,
        )
        checks["positive_finite_equity"] &= value.is_finite() and value > 0
        checks["ledger_reconciliation"] &= (
            abs(value - STARTING_EQUITY - net(components())) <= RECONCILIATION_TOLERANCE
        )
        return value

    retained_price_events = list(replay.get("price_events", []))
    price_map = {
        (str(row["kind"]), _time(row["timestamp"])): row
        for row in retained_price_events
    }
    checks["unique_price_event_keys"] = len(price_map) == len(retained_price_events)
    used_price_events: set[tuple[str, datetime]] = set()
    retained_trade_events = list(replay.get("trade_events", []))
    trade_map = {
        (str(row["kind"]), _time(row["timestamp"])): row
        for row in retained_trade_events
    }
    checks["unique_trade_event_keys"] = len(trade_map) == len(retained_trade_events)
    used_trade_events: set[tuple[str, datetime]] = set()
    funding_map: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    for row in replay.get("funding_events", []):
        funding_map[_time(row["timestamp"])].append(row)
    observed_funding_identities = [
        (_time(row["timestamp"]), str(row["instrument"]))
        for row in replay.get("funding_events", [])
    ]
    expected_funding_identities = [
        (stamp, swap)
        for swap in SWAP_INSTRUMENTS
        for stamp, _ in funding[swap]
        if window.start <= stamp < window.end_exclusive
    ]
    checks["funding_event_identity_inventory"] = sorted(
        observed_funding_identities
    ) == sorted(expected_funding_identities)
    interior_by_hour: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    for stamp, rows in funding_map.items():
        hour = stamp.replace(minute=0, second=0, microsecond=0)
        if stamp != hour:
            interior_by_hour[hour].extend(rows)
    retained_risk_events = list(replay.get("risk_events", []))
    risk_map = {
        (_time(row["timestamp"]), str(row["spot_instrument"]), str(row["source"])): row
        for row in retained_risk_events
    }
    checks["unique_risk_event_keys"] = len(risk_map) == len(retained_risk_events)
    used_risk_events: set[tuple[datetime, str, str]] = set()
    turnover = list(replay.get("turnover_events", []))
    used_turnover: set[int] = set()

    def price_transition(kind: str, stamp: datetime, source_stamp: datetime) -> None:
        key = (kind, stamp)
        row = price_map.get(key)
        if not isinstance(row, Mapping):
            checks["complete_price_event_coverage"] = False
            return
        used_price_events.add(key)
        observed = {
            str(value.get("spot_instrument")): value for value in row.get("rows", [])
        }
        for spot in SPOT_INSTRUMENTS:
            state = states[spot]
            new_spot = spot_trade[spot][source_stamp][
                "open" if kind == "OPEN_TRANSITION" else "close"
            ]
            swap = SPOT_TO_SWAP[spot]
            new_perp = (
                swap_trade[swap][source_stamp]["open"]
                if kind == "OPEN_TRANSITION"
                else marks[swap][source_stamp]["close"]
            )
            old_spot, old_perp = state["last_spot"], state["last_perp"]
            spot_pnl = ZERO if old_spot is None else state["q"] * (new_spot - old_spot)
            perp_pnl = ZERO if old_perp is None else state["q"] * (old_perp - new_perp)
            state["margin"] += perp_pnl
            state["components"]["spot_price_pnl"] += spot_pnl
            state["components"]["perpetual_price_pnl"] += perp_pnl
            state["last_spot"], state["last_perp"] = new_spot, new_perp
            retained = observed.get(spot, {})
            checks["price_pnl_recompute"] &= _close(
                retained.get("spot_price_pnl"), spot_pnl
            ) and _close(retained.get("perpetual_price_pnl"), perp_pnl)
            checks["price_source_recompute"] &= _close(
                retained.get("new_spot_price"), new_spot
            ) and _close(retained.get("new_perpetual_price"), new_perp)
        equity()

    def observe_risk(spot: str, stamp: datetime, source: str) -> None:
        state = states[spot]
        if state["q"] == 0:
            return
        source_stamp = (
            stamp.replace(minute=0, second=0, microsecond=0) - HOUR
            if source == "FUNDING"
            else stamp - HOUR
        )
        mark = marks[SPOT_TO_SWAP[spot]][source_stamp]["close"]
        spot_px = spot_trade[spot][source_stamp]["close"]
        buffer = state["margin"] / (state["q"] * mark)
        basis = mark / spot_px - ONE
        key = (stamp, spot, source)
        row = risk_map.get(key)
        if isinstance(row, Mapping):
            used_risk_events.add(key)
        checks["risk_observation_recompute"] &= (
            isinstance(row, Mapping)
            and _close(row.get("buffer"), buffer)
            and _close(row.get("basis"), basis)
        )
        breach = (
            buffer < MINIMUM_COLLATERAL_BUFFER or abs(basis) > MAXIMUM_RISK_ABS_BASIS
        )
        if breach and not state["pending"] and buffer < MINIMUM_COLLATERAL_BUFFER:
            state["buffer_breaches"] += 1
        state["pending"] = state["pending"] or breach

    def apply_funding(row: Mapping[str, Any]) -> None:
        nonlocal active_funding_count, gross_funding_payments, gross_funding_receipts
        stamp = _time(row["timestamp"])
        swap = str(row["instrument"])
        spot = next(key for key, value in SPOT_TO_SWAP.items() if value == swap)
        state = states[spot]
        source_stamp = stamp.replace(minute=0, second=0, microsecond=0) - HOUR
        source_mark = marks[swap][source_stamp]["close"]
        source_rate = dict(funding[swap]).get(stamp)
        pnl = (
            state["q"] * source_mark * source_rate
            if source_rate is not None
            else Decimal("NaN")
        )
        checks["funding_source_recompute"] &= (
            source_rate is not None
            and _time(row["preceding_mark_timestamp"]) == source_stamp
        )
        checks["funding_quantity_recompute"] &= _close(
            row.get("short_quantity"), state["q"]
        )
        checks["funding_active_state_recompute"] &= row.get("active_before") == (
            state["q"] > 0
        )
        checks["funding_pnl_recompute"] &= _close(row.get("funding_pnl"), pnl)
        if state["q"] > 0:
            active_funding_count += 1
        gross_funding_receipts += max(pnl, ZERO)
        gross_funding_payments += max(-pnl, ZERO)
        state["margin"] += pnl
        state["components"]["funding_pnl"] += pnl
        equity()
        observe_risk(spot, stamp, "FUNDING")

    def apply_trade_group(kind: str, stamp: datetime) -> None:
        nonlocal cash
        key = (kind, stamp)
        group = trade_map.get(key)
        if not isinstance(group, Mapping):
            return
        used_trade_events.add(key)
        pre_group_equity = equity()
        trades = group.get("trades", [])
        group_paired = ZERO
        risk_pre_equity: dict[str, Decimal] = {}
        for trade in trades:
            spot = str(trade.get("spot_instrument"))
            state = states[spot]
            before_q = state["q"]
            before_margin = state["margin"]
            was_pending = bool(state["pending"])
            individual_pre_equity = equity()
            risk_pre_equity[spot] = individual_pre_equity
            new_q = Decimal(str(trade["quantity_after"]))
            source_spot = spot_trade[spot][stamp]["open"]
            source_swap = swap_trade[SPOT_TO_SWAP[spot]][stamp]["open"]
            spot_fee = abs(new_q - before_q) * source_spot * rate
            swap_fee = abs(new_q - before_q) * source_swap * rate
            checks["trade_source_recompute"] &= _close(
                trade.get("spot_trade_price"), source_spot
            ) and _close(trade.get("swap_trade_price"), source_swap)
            checks["trade_position_recompute"] &= (
                _close(trade.get("quantity_before"), before_q)
                and _close(trade.get("short_before"), before_q)
                and _close(trade.get("short_after"), new_q)
            )
            checks["fee_recompute"] &= _close(
                trade.get("spot_cost"), spot_fee
            ) and _close(trade.get("swap_cost"), swap_fee)
            cash -= (new_q - before_q) * source_spot + spot_fee
            if new_q == 0:
                cash += before_margin - swap_fee
                state["margin"] = ZERO
                state["pending"] = False
            else:
                checks["blocked_reopen_guard"] &= not (
                    state["blocked_until"] is not None
                    and stamp < state["blocked_until"]
                )
                retained_margin = Decimal(str(trade["margin_after"]))
                target_margin = retained_margin + swap_fee
                cash -= target_margin - before_margin
                state["margin"] = retained_margin
            state["q"] = new_q
            state["last_spot"], state["last_perp"] = source_spot, source_swap
            state["components"]["spot_cost"] += spot_fee
            state["components"]["swap_cost"] += swap_fee
            checks["cash_margin_recompute"] &= _close(
                trade.get("free_cash_after"), cash
            ) and _close(trade.get("margin_after"), state["margin"])
            group_paired += (
                abs(new_q - before_q) * source_spot
                + abs(new_q - before_q) * source_swap
            ) / Decimal(2)
            if kind == "RISK_CLOSE":
                checks["risk_close_requires_breach"] &= was_pending and new_q == 0
                expected_block = stamp + timedelta(days=(7 - stamp.weekday()) % 7)
                expected_block = expected_block.replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                if expected_block <= stamp:
                    expected_block += timedelta(days=7)
                checks["risk_reentry_block_recompute"] &= (
                    _time(trade.get("blocked_until")) == expected_block
                )
                state["blocked_until"] = expected_block
            equity()
        if kind in {"SCHEDULED_REBALANCE", "TERMINAL_CLOSE"}:
            matches = [
                (index, row)
                for index, row in enumerate(turnover)
                if index not in used_turnover
                and row.get("kind") == kind
                and _time(row.get("timestamp")) == stamp
            ]
            checks["simultaneous_turnover_denominator"] &= (
                len(matches) == 1
                and _close(matches[0][1].get("pre_event_equity"), pre_group_equity)
                and _close(
                    matches[0][1].get("paired_turnover_ratio"),
                    group_paired / pre_group_equity,
                )
            )
            if matches:
                used_turnover.add(matches[0][0])
        elif kind == "RISK_CLOSE":
            for trade in trades:
                spot = trade["spot_instrument"]
                matches = [
                    (index, row)
                    for index, row in enumerate(turnover)
                    if index not in used_turnover
                    and row.get("kind") == kind
                    and row.get("spot_instrument") == spot
                    and _time(row.get("timestamp")) == stamp
                ]
                checks["risk_turnover_recompute"] &= len(matches) == 1
                if matches:
                    expected_ratio = (
                        abs(Decimal(trade["spot_delta"]))
                        * (
                            Decimal(trade["spot_trade_price"])
                            + Decimal(trade["swap_trade_price"])
                        )
                        / Decimal(2)
                        / risk_pre_equity[spot]
                    )
                    checks["risk_turnover_recompute"] &= _close(
                        matches[0][1].get("pre_event_equity"),
                        risk_pre_equity[spot],
                    ) and _close(
                        matches[0][1].get("paired_turnover_ratio"),
                        expected_ratio,
                    )
                    used_turnover.add(matches[0][0])

    retained_signals = list(replay.get("signals", []))
    signal_by_time = {
        _time(row["timestamp"]): row["assets"] for row in replay.get("signals", [])
    }
    retained_decisions = list(replay.get("decisions", []))
    decisions_by_time = {
        _time(row["timestamp"]): row for row in replay.get("decisions", [])
    }
    expected_decision_times = []
    expected_decision = window.start
    while expected_decision < window.end_exclusive:
        expected_decision_times.append(expected_decision)
        expected_decision += timedelta(days=7)
    checks["signal_timestamp_inventory"] = len(signal_by_time) == len(
        retained_signals
    ) and set(signal_by_time) == set(expected_decision_times)
    checks["decision_timestamp_inventory"] = len(decisions_by_time) == len(
        retained_decisions
    ) and set(decisions_by_time) == set(expected_decision_times)
    week_snapshots = []
    week_start = window.start
    week_start_equity = STARTING_EQUITY
    week_start_components = components()
    week_active = False
    week_risk = False
    equity_path = [STARTING_EQUITY]

    current = window.start
    while current <= window.end_exclusive:
        price_transition("OPEN_TRANSITION", current, current)
        if current == window.end_exclusive:
            expected_terminal = {
                spot for spot, state in states.items() if state["q"] > 0
            }
            terminal_group = trade_map.get(("TERMINAL_CLOSE", current))
            observed_terminal = (
                [str(row.get("spot_instrument")) for row in terminal_group["trades"]]
                if isinstance(terminal_group, Mapping)
                and isinstance(terminal_group.get("trades"), list)
                else []
            )
            checks["terminal_trade_inventory"] &= (
                isinstance(terminal_group, Mapping) == bool(expected_terminal)
                and len(observed_terminal) == len(set(observed_terminal))
                and set(observed_terminal) == expected_terminal
            )
            apply_trade_group("TERMINAL_CLOSE", current)
            final = equity()
            week_snapshots.append(
                (
                    week_start,
                    current,
                    week_start_equity,
                    final,
                    week_start_components,
                    components(),
                    week_active,
                    week_risk,
                )
            )
            equity_path.append(final)
            break
        if current > window.start and current.weekday() == 0 and current.hour == 0:
            boundary = equity()
            week_snapshots.append(
                (
                    week_start,
                    current,
                    week_start_equity,
                    boundary,
                    week_start_components,
                    components(),
                    week_active,
                    week_risk,
                )
            )
            week_start, week_start_equity, week_start_components = (
                current,
                boundary,
                components(),
            )
            week_active = any(state["q"] > 0 for state in states.values())
            week_risk = False
        for row in sorted(
            funding_map.get(current, []), key=lambda value: value["instrument"]
        ):
            apply_funding(row)
        pending_before = {spot for spot, state in states.items() if state["pending"]}
        risk_group = trade_map.get(("RISK_CLOSE", current))
        observed_risk_closes = (
            [str(row.get("spot_instrument")) for row in risk_group["trades"]]
            if isinstance(risk_group, Mapping)
            and isinstance(risk_group.get("trades"), list)
            else []
        )
        checks["risk_close_inventory"] &= (
            isinstance(risk_group, Mapping) == bool(pending_before)
            and len(observed_risk_closes) == len(set(observed_risk_closes))
            and set(observed_risk_closes) == pending_before
        )
        apply_trade_group("RISK_CLOSE", current)
        week_risk = week_risk or bool(pending_before)
        if current.weekday() == 0 and current.hour == 0:
            expected_signal = _independent_signal(
                current, spot_trade=spot_trade, marks=marks, funding=funding
            )
            checks["signal_recompute"] &= _dict_equal(
                expected_signal, signal_by_time.get(current)
            )
            decision = decisions_by_time.get(current, {})
            expected_eligible = (
                [spot for spot in SPOT_INSTRUMENTS if expected_signal[spot]["eligible"]]
                if policy == "candidate"
                else list(SPOT_INSTRUMENTS)
            )
            checks["eligibility_recompute"] &= (
                decision.get("eligible_assets") == expected_eligible
            )
            pre_rebalance_equity = equity()
            expected_plan = _independent_plan(
                states,
                eligible=expected_eligible,
                total_equity=pre_rebalance_equity,
                spot_opens={
                    spot: spot_trade[spot][current]["open"] for spot in SPOT_INSTRUMENTS
                },
                timestamp=current,
            )
            observed_actions = decision.get("actions", {})
            checks["action_inventory_recompute"] &= isinstance(
                observed_actions, Mapping
            ) and set(observed_actions) == set(SPOT_INSTRUMENTS)
            for spot in SPOT_INSTRUMENTS:
                observed_action = observed_actions.get(spot, {})
                expected_action = expected_plan[spot]
                checks["action_plan_recompute"] &= observed_action.get(
                    "action"
                ) == expected_action["action"] and all(
                    _close(observed_action.get(key), expected_action[key])
                    for key in (
                        "raw_sleeve_capital",
                        "raw_spot_notional",
                        "raw_margin",
                    )
                )
            spot_opens = {
                spot: spot_trade[spot][current]["open"] for spot in SPOT_INSTRUMENTS
            }
            swap_opens = {
                spot: swap_trade[SPOT_TO_SWAP[spot]][current]["open"]
                for spot in SPOT_INSTRUMENTS
            }
            try:
                expected_scale = _independent_scale(
                    states,
                    cash=cash,
                    plan=expected_plan,
                    spot_opens=spot_opens,
                    swap_opens=swap_opens,
                    cost_rate=rate,
                )
            except C9AHistoricalIndependentError as exc:
                raise C9AHistoricalIndependentError(
                    "independent scale failed for "
                    f"{policy}:{cost_label} at {iso(current)}"
                ) from exc
            checks["maximum_scale_recompute"] &= _close(
                decision.get("target_scale"), expected_scale
            )
            expected_scheduled = {
                spot
                for spot, value in expected_plan.items()
                if value["action"] in {"CLOSE", "OPEN", "RESIZE"}
            }
            scheduled_group = trade_map.get(("SCHEDULED_REBALANCE", current))
            observed_scheduled = (
                [str(row.get("spot_instrument")) for row in scheduled_group["trades"]]
                if isinstance(scheduled_group, Mapping)
                and isinstance(scheduled_group.get("trades"), list)
                else []
            )
            checks["scheduled_trade_inventory"] &= (
                isinstance(scheduled_group, Mapping) == bool(expected_scheduled)
                and len(observed_scheduled) == len(set(observed_scheduled))
                and set(observed_scheduled) == expected_scheduled
            )
            apply_trade_group("SCHEDULED_REBALANCE", current)
            for spot in SPOT_INSTRUMENTS:
                action = observed_actions.get(spot, {})
                if expected_plan[spot]["action"] in {"OPEN", "RESIZE"}:
                    target = (
                        Decimal(str(expected_plan[spot]["raw_spot_notional"]))
                        * expected_scale
                        / spot_trade[spot][current]["open"]
                    )
                    checks["continuous_target_recompute"] &= _close(
                        action.get("quantity_after"), target
                    ) and _close(action.get("short_after"), target)
                    expected_margin = (
                        Decimal(str(expected_plan[spot]["raw_margin"])) * expected_scale
                    )
                    matching = [
                        trade
                        for trade in trade_map.get(
                            ("SCHEDULED_REBALANCE", current), {}
                        ).get("trades", [])
                        if trade.get("spot_instrument") == spot
                    ]
                    checks["target_margin_recompute"] &= len(matching) == 1 and _close(
                        Decimal(matching[0]["margin_after"])
                        + Decimal(matching[0]["swap_cost"]),
                        expected_margin,
                    )
                state = states[spot]
                checks["decision_post_state_recompute"] &= (
                    _close(action.get("quantity_after"), state["q"])
                    and _close(action.get("short_after"), state["q"])
                    and _close(action.get("margin_after"), state["margin"])
                )
                expected_blocked = (
                    None
                    if state["blocked_until"] is None
                    else iso(state["blocked_until"])
                )
                checks["decision_block_state_recompute"] &= (
                    action.get("blocked_until") == expected_blocked
                )
            checks["decision_cash_recompute"] &= _close(
                decision.get("free_cash_after"), cash
            )
        week_active = week_active or any(state["q"] > 0 for state in states.values())
        interior = interior_by_hour.get(current, [])
        for row in sorted(
            interior, key=lambda value: (_time(value["timestamp"]), value["instrument"])
        ):
            apply_funding(row)
        price_transition("CLOSE_TRANSITION", current + HOUR, current)
        for spot in SPOT_INSTRUMENTS:
            was_pending = states[spot]["pending"]
            observe_risk(spot, current + HOUR, "HOURLY_CLOSE")
            week_risk = week_risk or (states[spot]["pending"] and not was_pending)
        value = equity()
        equity_path.append(value)
        current += HOUR

    retained_weekly = replay.get("weekly_buckets", [])
    checks["weekly_bucket_count"] &= len(week_snapshots) == len(retained_weekly) == 26
    for retained, snapshot in zip(retained_weekly, week_snapshots, strict=False):
        start, end, start_eq, end_eq, start_comp, end_comp, active, risk_exit = snapshot
        delta = {name: end_comp[name] - start_comp[name] for name in COMPONENTS}
        checks["weekly_equity_recompute"] &= (
            _time(retained.get("start")) == start
            and _time(retained.get("end_exclusive")) == end
            and _close(retained.get("start_equity"), start_eq)
            and _close(retained.get("end_equity"), end_eq)
            and _close(retained.get("weekly_pnl"), end_eq - start_eq)
            and _close(retained.get("weekly_return"), (end_eq - start_eq) / start_eq)
        )
        checks["weekly_component_recompute"] &= all(
            _close(retained.get("components", {}).get(name), delta[name])
            for name in COMPONENTS
        )
        checks["weekly_activity_recompute"] &= (
            retained.get("active") == active and retained.get("risk_exit") == risk_exit
        )
    expected_weekly_returns = [
        (snapshot[3] - snapshot[2]) / snapshot[2] for snapshot in week_snapshots
    ]
    retained_weekly_returns = replay.get("weekly_returns", [])
    checks["weekly_return_vector_recompute"] &= len(retained_weekly_returns) == len(
        expected_weekly_returns
    ) and all(
        _close(retained, expected)
        for retained, expected in zip(
            retained_weekly_returns, expected_weekly_returns, strict=False
        )
    )
    final_components = components()
    checks["final_equity_recompute"] &= _close(replay.get("final_equity"), equity())
    checks["final_component_recompute"] &= all(
        _close(replay.get("components", {}).get(name), final_components[name])
        for name in COMPONENTS
    )
    checks["complete_equity_path_recompute"] &= len(
        replay.get("complete_hourly_equity_path", [])
    ) == len(equity_path) and all(
        _close(row.get("equity"), expected)
        for row, expected in zip(
            replay.get("complete_hourly_equity_path", []), equity_path, strict=False
        )
    )
    checks["funding_event_inventory"] &= sum(
        1
        for swap in SWAP_INSTRUMENTS
        for stamp, _ in funding[swap]
        if window.start <= stamp < window.end_exclusive
    ) == len(replay.get("funding_events", []))
    checks["used_price_event_inventory"] &= used_price_events == set(price_map)
    checks["used_trade_event_inventory"] &= used_trade_events == set(trade_map)
    checks["used_risk_event_inventory"] &= used_risk_events == set(risk_map)
    checks["turnover_event_inventory"] &= len(used_turnover) == len(turnover)
    total_turnover = sum(
        (Decimal(str(row["paired_turnover_ratio"])) for row in turnover), ZERO
    ) / Decimal("0.5")
    checks["turnover_metric_recompute"] &= _close(
        replay.get("annualized_one_way_paired_turnover"), total_turnover
    )
    peak = equity_path[0]
    drawdown = ZERO
    for value in equity_path:
        peak = max(peak, value)
        drawdown = max(drawdown, ONE - value / peak)
    checks["drawdown_recompute"] &= _close(replay.get("maximum_drawdown"), drawdown)
    checks["risk_counter_recompute"] &= int(
        replay.get("collateral_buffer_breach_count", -1)
    ) == sum(int(state["buffer_breaches"]) for state in states.values())
    checks["funding_activity_recompute"] &= int(
        replay.get("active_funding_settlement_count", -1)
    ) == active_funding_count and int(
        replay.get("accounted_funding_settlement_count", -1)
    ) == len(expected_funding_identities)
    checks["gross_funding_recompute"] &= _close(
        replay.get("gross_positive_funding_receipts"), gross_funding_receipts
    ) and _close(replay.get("gross_funding_payments"), gross_funding_payments)
    checks["active_week_count_recompute"] &= int(
        replay.get("active_week_count", -1)
    ) == sum(bool(snapshot[6]) for snapshot in week_snapshots)
    checks["asset_contribution_recompute"] &= all(
        _close(
            replay.get("asset_contributions", {}).get(spot.split("-")[0]),
            (
                states[spot]["components"]["spot_price_pnl"]
                + states[spot]["components"]["perpetual_price_pnl"]
                + states[spot]["components"]["funding_pnl"]
                - states[spot]["components"]["spot_cost"]
                - states[spot]["components"]["swap_cost"]
            ),
        )
        for spot in SPOT_INSTRUMENTS
    )
    checks["declared_failure_counters_recompute"] &= (
        int(replay.get("base_hedge_mismatch_count", -1)) == 0
        and int(replay.get("missing_decision_count", -1)) == 0
        and int(replay.get("unaccounted_funding_settlement_count", -1)) == 0
        and int(replay.get("non_finite_state_count", -1)) == 0
        and int(replay.get("non_positive_equity_state_count", -1)) == 0
        and int(replay.get("reconciliation_failure_count", -1)) == 0
    )
    checks["source_ordered_state_recompute"] = all(checks.values())
    return {
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": dict(checks),
        "reference_final_equity": str(equity()),
        "reference_components": {
            name: str(value) for name, value in final_components.items()
        },
    }


def _audit_spot_buy_hold(
    replay: Mapping[str, Any],
    *,
    spot_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
) -> bool:
    window = window_by_id(str(replay["window_id"]))
    rate = COST_RATES[str(replay["cost_label"])]
    quantities = {
        spot: (STARTING_EQUITY / Decimal(2))
        / (spot_trade[spot][window.start]["open"] * (ONE + rate))
        for spot in SPOT_INSTRUMENTS
    }
    gross = sum(
        (
            quantities[spot] * spot_trade[spot][window.end_exclusive]["open"]
            for spot in SPOT_INSTRUMENTS
        ),
        ZERO,
    )
    exit_cost = sum(
        (
            quantities[spot] * spot_trade[spot][window.end_exclusive]["open"] * rate
            for spot in SPOT_INSTRUMENTS
        ),
        ZERO,
    )
    return _close(replay.get("final_equity"), gross - exit_cost) and all(
        _close(replay.get("quantities", {}).get(spot), quantities[spot])
        for spot in SPOT_INSTRUMENTS
    )


def review_historical_window(
    producer: Mapping[str, Any],
    *,
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    spot_trade = {
        spot: _prices(trade_rows[spot], ("open", "close")) for spot in SPOT_INSTRUMENTS
    }
    swap_trade = {
        swap: _prices(trade_rows[swap], ("open", "close")) for swap in SWAP_INSTRUMENTS
    }
    marks = {swap: _prices(mark_rows[swap], ("close",)) for swap in SWAP_INSTRUMENTS}
    funding = {swap: _funding(funding_rows[swap]) for swap in SWAP_INSTRUMENTS}
    reviews = {}
    for policy in ("candidate", "always_on"):
        for cost in COST_RATES:
            key = f"{policy}:{cost}"
            reviews[key] = _audit_carry(
                producer["replays"][policy][cost],
                spot_trade=spot_trade,
                swap_trade=swap_trade,
                marks=marks,
                funding=funding,
            )
    comparator_checks = {}
    for cost in COST_RATES:
        cash = producer["replays"]["cash"][cost]
        comparator_checks[f"cash:{cost}"] = (
            cash.get("final_equity") == "1000"
            and cash.get("weekly_returns") == ["0"] * 26
        )
        comparator_checks[f"spot_buy_and_hold:{cost}"] = _audit_spot_buy_hold(
            producer["replays"]["spot_buy_and_hold"][cost], spot_trade=spot_trade
        )
    passed = all(value["status"] == "PASS" for value in reviews.values()) and all(
        comparator_checks.values()
    )
    return {
        "schema_version": 1,
        "stage": "C9A_WINDOW_INDEPENDENT_RECOMPUTE",
        "window_id": producer.get("window", {}).get("window_id"),
        "status": "PASS" if passed else "FAIL",
        "replay_reviews": reviews,
        "comparator_checks": comparator_checks,
        "imports_production_replay": False,
        "imports_production_policy": False,
        "imports_production_metric_or_gate": False,
        **safety_boundary(),
    }


def _stats(values: Sequence[Decimal]) -> dict[str, float | int | bool]:
    raw = [float(value) for value in values]
    sample_std = stdev(raw)
    if sample_std <= 0 or not math.isfinite(sample_std):
        return {
            "n": len(raw),
            "annualized_weekly_sharpe": 0.0,
            "psr_probability": 0.0,
            "valid": False,
        }
    sharpe = mean(raw) / sample_std
    asymmetry = float(skew(raw, bias=False))
    ordinary = float(kurtosis(raw, fisher=False, bias=False))
    radicand = 1 - asymmetry * sharpe + ((ordinary - 1) / 4) * sharpe**2
    probability = (
        float(norm.cdf(sharpe * math.sqrt(len(raw) - 1) / math.sqrt(radicand)))
        if math.isfinite(radicand) and radicand > 0
        else 0.0
    )
    return {
        "n": len(raw),
        "annualized_weekly_sharpe": sharpe * math.sqrt(52),
        "psr_probability": probability,
        "valid": math.isfinite(probability),
    }


def _share(values: Sequence[Decimal], count: int = 1) -> Decimal | None:
    positive = sorted((max(value, ZERO) for value in values), reverse=True)
    denominator = sum(positive, ZERO)
    return None if denominator <= 0 else sum(positive[:count], ZERO) / denominator


def review_pooled_summary(
    producer: Mapping[str, Any], windows: Mapping[str, Any]
) -> dict[str, Any]:
    reference: dict[str, dict[str, dict[str, Any]]] = {}
    for policy in ("candidate", "always_on", "cash", "spot_buy_and_hold"):
        reference[policy] = {}
        for cost in COST_RATES:
            rows = [
                windows[f"W{index}"]["replays"][policy][cost] for index in range(1, 6)
            ]
            finals = [Decimal(row["final_equity"]) for row in rows]
            weekly = [Decimal(value) for row in rows for value in row["weekly_returns"]]
            reference[policy][cost] = {
                "aggregate_return": sum(finals, ZERO) / Decimal(5000) - ONE,
                "statistics": _stats(weekly),
                "maximum_drawdown": max(
                    Decimal(row["maximum_drawdown"]) for row in rows
                ),
                "turnover": sum(
                    (
                        Decimal(row.get("annualized_one_way_paired_turnover", "0"))
                        for row in rows
                    ),
                    ZERO,
                )
                / Decimal(5),
                "window_returns": [Decimal(row["net_return"]) for row in rows],
                "window_pnl": [value - STARTING_EQUITY for value in finals],
                "weekly_pnl": [
                    Decimal(bucket["weekly_pnl"])
                    for row in rows
                    for bucket in row["weekly_buckets"]
                ],
            }
            if policy in {"candidate", "always_on"}:
                reference[policy][cost].update(
                    {
                        "costs": sum(
                            (
                                Decimal(row["components"]["spot_cost"])
                                + Decimal(row["components"]["swap_cost"])
                                for row in rows
                            ),
                            ZERO,
                        ),
                        "receipts": sum(
                            (
                                Decimal(row["gross_positive_funding_receipts"])
                                for row in rows
                            ),
                            ZERO,
                        ),
                        "active_weeks": [int(row["active_week_count"]) for row in rows],
                        "active_funding": sum(
                            int(row["active_funding_settlement_count"]) for row in rows
                        ),
                        "buffer_breaches": sum(
                            int(row["collateral_buffer_breach_count"]) for row in rows
                        ),
                        "hedge_mismatches": sum(
                            int(row["base_hedge_mismatch_count"]) for row in rows
                        ),
                        "error_counts": sum(
                            int(row[key])
                            for row in rows
                            for key in (
                                "missing_decision_count",
                                "unaccounted_funding_settlement_count",
                                "non_finite_state_count",
                                "non_positive_equity_state_count",
                                "reconciliation_failure_count",
                            )
                        ),
                        "asset_pnl": [
                            sum(
                                (
                                    Decimal(row["asset_contributions"][asset])
                                    for row in rows
                                ),
                                ZERO,
                            )
                            for asset in ("BTC", "ETH")
                        ],
                    }
                )
    candidate = reference["candidate"]["1.0x"]
    always = reference["always_on"]["1.0x"]
    costs = candidate["costs"]
    asset_share = _share(candidate["asset_pnl"])
    window_share = _share(candidate["window_pnl"])
    week_share = _share(candidate["weekly_pnl"])
    top_three = _share(candidate["weekly_pnl"], 3)
    gates = {
        "all_windows_positive": all(value > 0 for value in candidate["window_returns"]),
        "aggregate_expected_return_positive": candidate["aggregate_return"] > 0,
        "aggregate_1_5x_return_positive": reference["candidate"]["1.5x"][
            "aggregate_return"
        ]
        > 0,
        "aggregate_2x_return_non_negative": reference["candidate"]["2.0x"][
            "aggregate_return"
        ]
        >= 0,
        "annualized_weekly_sharpe": Decimal(
            str(candidate["statistics"]["annualized_weekly_sharpe"])
        )
        >= Decimal(1),
        "weekly_psr": Decimal(str(candidate["statistics"]["psr_probability"]))
        >= Decimal("0.95"),
        "maximum_drawdown": candidate["maximum_drawdown"] <= Decimal("0.10"),
        "zero_collateral_buffer_breaches": candidate["buffer_breaches"] == 0,
        "zero_base_hedge_mismatches": candidate["hedge_mismatches"] == 0,
        "zero_missing_decisions": candidate["error_counts"] == 0,
        "zero_unaccounted_funding": candidate["error_counts"] == 0,
        "zero_non_finite_states": candidate["error_counts"] == 0,
        "zero_non_positive_equity_states": candidate["error_counts"] == 0,
        "zero_reconciliation_failures": candidate["error_counts"] == 0,
        "annualized_turnover": candidate["turnover"] <= Decimal(6),
        "funding_cost_coverage": costs > 0
        and candidate["receipts"] / costs >= Decimal(2),
        "active_weeks_total": sum(candidate["active_weeks"]) >= 52,
        "active_weeks_each_window": all(
            value >= 6 for value in candidate["active_weeks"]
        ),
        "active_funding_settlements": candidate["active_funding"] >= 100,
        "both_assets_positive": all(value > 0 for value in candidate["asset_pnl"]),
        "asset_concentration": asset_share is not None
        and asset_share <= Decimal("0.70"),
        "window_concentration": window_share is not None
        and window_share <= Decimal("0.40"),
        "week_concentration": week_share is not None and week_share <= Decimal("0.15"),
        "top_three_week_concentration": top_three is not None
        and top_three <= Decimal("0.35"),
        "return_delta_vs_always_on": candidate["aggregate_return"]
        - always["aggregate_return"]
        > 0,
        "sharpe_delta_vs_always_on": Decimal(
            str(candidate["statistics"]["annualized_weekly_sharpe"])
        )
        - Decimal(str(always["statistics"]["annualized_weekly_sharpe"]))
        >= Decimal("0.10"),
        "drawdown_not_worse_than_always_on": candidate["maximum_drawdown"]
        <= always["maximum_drawdown"],
        "turnover_not_worse_than_always_on": candidate["turnover"]
        <= always["turnover"],
    }
    retained_gates = producer.get("eligibility_gates")
    pooled_match = True
    for policy, costs_by_label in reference.items():
        for cost, values in costs_by_label.items():
            observed = producer.get("pooled", {}).get(policy, {}).get(cost, {})
            pooled_match &= _close(
                observed.get("aggregate_return"), values["aggregate_return"]
            )
            pooled_match &= _close(
                observed.get("maximum_drawdown"), values["maximum_drawdown"]
            )
            pooled_match &= _close(
                observed.get("annualized_one_way_paired_turnover"), values["turnover"]
            )
            pooled_match &= _close(
                observed.get("statistics", {}).get("annualized_weekly_sharpe"),
                values["statistics"]["annualized_weekly_sharpe"],
            )
            pooled_match &= _close(
                observed.get("statistics", {}).get("psr_probability"),
                values["statistics"]["psr_probability"],
            )
    verdict = "ECONOMIC_PASS" if all(gates.values()) else "ECONOMIC_FAIL"
    passed = (
        pooled_match
        and retained_gates == gates
        and producer.get("overall_economic_verdict") == verdict
    )
    return {
        "schema_version": 1,
        "stage": "C9A_POOLED_INDEPENDENT_RECOMPUTE",
        "status": "PASS" if passed else "FAIL",
        "pooled_metrics_match": pooled_match,
        "gate_recompute_match": retained_gates == gates,
        "reference_gates": gates,
        "reference_final_verdict": verdict,
        "imports_production_replay": False,
        "imports_production_policy": False,
        "imports_production_metric_or_gate": False,
        **safety_boundary(),
    }
