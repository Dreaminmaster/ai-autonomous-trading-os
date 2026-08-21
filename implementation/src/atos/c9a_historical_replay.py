"""Frozen C9A source-ordered continuous-notional historical replay."""

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
    CANDIDATE_ID,
    COLLATERAL_CAPITAL_FRACTION,
    COST_RATES,
    EXPECTED_DECISIONS_PER_WINDOW,
    FUNDING_LOOKBACK,
    HISTORICAL_DATA_STATUS,
    HOUR,
    MAXIMUM_ENTRY_ABS_BASIS,
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
    C9AError,
    decimal_value,
    iso,
    safety_boundary,
)
from atos.c9a_historical_ledger import (
    COMPONENT_NAMES,
    Portfolio,
    component_delta,
    component_net,
)
from atos.c9a_historical_schedule import (
    HISTORICAL_WINDOWS,
    decision_times,
    window_by_id,
)

ZERO = Decimal(0)
ONE = Decimal(1)


class C9AHistoricalReplayError(RuntimeError):
    """Raised when source data or accounting cannot support an economic result."""


def _wrap(exc: Exception) -> C9AHistoricalReplayError:
    return C9AHistoricalReplayError(str(exc))


def _index_prices(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    fields: tuple[str, ...],
) -> dict[datetime, dict[str, Decimal]]:
    output: dict[datetime, dict[str, Decimal]] = {}
    previous: datetime | None = None
    try:
        for row in rows:
            stamp = datetime.fromisoformat(str(row.get("timestamp")))
            if (
                stamp.tzinfo is None
                or stamp.utcoffset() != timedelta(0)
                or stamp.minute
                or stamp.second
                or stamp.microsecond
            ):
                raise C9AError(
                    f"{instrument} candle timestamp is not an exact UTC hour"
                )
            if previous is not None and stamp <= previous:
                raise C9AError(f"{instrument} candles are duplicate or unordered")
            previous = stamp
            output[stamp] = {
                field: decimal_value(
                    row.get(field), f"{instrument} {field}", positive=True
                )
                for field in fields
            }
    except (TypeError, ValueError, C9AError) as exc:
        raise _wrap(exc) from exc
    if not output:
        raise C9AHistoricalReplayError(f"{instrument} candle series is empty")
    return output


def _index_funding(
    rows: Sequence[Mapping[str, Any]], *, instrument: str
) -> tuple[tuple[datetime, Decimal], ...]:
    output = []
    previous: datetime | None = None
    try:
        for row in rows:
            stamp = datetime.fromisoformat(str(row.get("funding_time")))
            if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
                raise C9AError("funding timestamp must be UTC")
            if previous is not None:
                if stamp <= previous:
                    raise C9AError(f"{instrument} funding is duplicate or unordered")
                if stamp - previous > timedelta(hours=8, minutes=1):
                    raise C9AError(
                        f"{instrument} funding gap exceeds eight hours plus tolerance"
                    )
            previous = stamp
            output.append(
                (
                    stamp,
                    decimal_value(row.get("realized_rate"), "realized funding rate"),
                )
            )
    except (TypeError, ValueError, C9AError) as exc:
        raise _wrap(exc) from exc
    if not output:
        raise C9AHistoricalReplayError(f"{instrument} funding series is empty")
    return tuple(output)


def _require_hours(
    series: Mapping[datetime, Any],
    *,
    start: datetime,
    end_exclusive: datetime,
    label: str,
) -> None:
    current = start
    while current < end_exclusive:
        if current not in series:
            raise C9AHistoricalReplayError(
                f"missing exact {label} hour: {iso(current)}"
            )
        current += HOUR


def _predecessor(
    stamp: datetime, values: Mapping[datetime, Mapping[str, Decimal]], field: str
) -> tuple[datetime, Decimal]:
    source = stamp.replace(minute=0, second=0, microsecond=0) - HOUR
    row = values.get(source)
    if row is None:
        raise C9AHistoricalReplayError(
            f"funding lacks preceding completed candle: {iso(stamp)}"
        )
    return source, row[field]


def build_signal(
    decision_time: datetime,
    *,
    spot_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    marks: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    funding: Mapping[str, tuple[tuple[datetime, Decimal], ...]],
) -> dict[str, Any]:
    if decision_time not in decision_times(
        next(
            window
            for window in HISTORICAL_WINDOWS
            if window.start <= decision_time < window.end_exclusive
        )
    ):
        raise C9AHistoricalReplayError("signal timestamp is outside frozen Monday grid")
    output: dict[str, Any] = {}
    signal_candle = decision_time - 2 * HOUR
    lookback_start = decision_time - FUNDING_LOOKBACK
    for spot in SPOT_INSTRUMENTS:
        swap = SPOT_TO_SWAP[spot]
        selected = [
            rate
            for stamp, rate in funding[swap]
            if lookback_start <= stamp < decision_time
        ]
        if not selected:
            raise C9AHistoricalReplayError(f"funding lookback is empty: {swap}")
        funding_sum = sum(selected, ZERO)
        positive = sum(rate > 0 for rate in selected)
        share = Decimal(positive) / Decimal(len(selected))
        try:
            spot_close = spot_trade[spot][signal_candle]["close"]
            mark_close = marks[swap][signal_candle]["close"]
        except KeyError as exc:
            raise C9AHistoricalReplayError(
                "signal lacks strict t-2h basis candle"
            ) from exc
        basis = mark_close / spot_close - ONE
        eligible = (
            funding_sum > MINIMUM_FUNDING_SUM
            and share >= MINIMUM_POSITIVE_SHARE
            and abs(basis) <= MAXIMUM_ENTRY_ABS_BASIS
        )
        output[spot] = {
            "swap_instrument": swap,
            "lookback_start_inclusive": iso(lookback_start),
            "lookback_end_exclusive": iso(decision_time),
            "settlement_count": len(selected),
            "positive_settlement_count": positive,
            "funding_sum_28d": str(funding_sum),
            "positive_funding_share_28d": str(share),
            "basis_source_timestamp": iso(signal_candle),
            "basis_source_close_time": iso(signal_candle + HOUR),
            "spot_close": str(spot_close),
            "mark_close": str(mark_close),
            "basis": str(basis),
            "eligible": eligible,
        }
    return output


def _next_hour_values(
    stamp: datetime,
    *,
    spot_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    swap_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
) -> tuple[dict[str, Decimal], dict[str, Decimal]]:
    try:
        return (
            {spot: spot_trade[spot][stamp]["open"] for spot in SPOT_INSTRUMENTS},
            {
                spot: swap_trade[SPOT_TO_SWAP[spot]][stamp]["open"]
                for spot in SPOT_INSTRUMENTS
            },
        )
    except KeyError as exc:
        raise C9AHistoricalReplayError(
            f"missing transaction open: {iso(stamp)}"
        ) from exc


def _action_plan(
    portfolio: Portfolio,
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
        sleeve = portfolio.sleeves[spot]
        blocked = sleeve.blocked_until is not None and timestamp < sleeve.blocked_until
        if spot not in selected or blocked:
            action = (
                "CLOSE" if sleeve.active else ("BLOCKED" if blocked else "HOLD_CASH")
            )
            output[spot] = {
                "action": action,
                "raw_sleeve_capital": ZERO,
                "raw_spot_notional": ZERO,
                "raw_margin": ZERO,
            }
            continue
        raw_spot = sleeve_capital * SPOT_CAPITAL_FRACTION
        current_spot = sleeve.spot_quantity * spot_opens[spot]
        if not sleeve.active:
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


def _apply_plan(
    portfolio: Portfolio,
    *,
    plan: Mapping[str, Mapping[str, Any]],
    scale: Decimal,
    spot_opens: Mapping[str, Decimal],
    swap_opens: Mapping[str, Decimal],
    cost_rate: Decimal,
) -> list[dict[str, str]]:
    with localcontext() as context:
        context.prec = 60
        return _apply_plan_at_precision(
            portfolio,
            plan=plan,
            scale=scale,
            spot_opens=spot_opens,
            swap_opens=swap_opens,
            cost_rate=cost_rate,
        )


def _apply_plan_at_precision(
    portfolio: Portfolio,
    *,
    plan: Mapping[str, Mapping[str, Any]],
    scale: Decimal,
    spot_opens: Mapping[str, Decimal],
    swap_opens: Mapping[str, Decimal],
    cost_rate: Decimal,
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for spot in SPOT_INSTRUMENTS:
        if plan[spot]["action"] == "CLOSE":
            output.append(
                portfolio.trade_target(
                    spot=spot,
                    new_quantity=ZERO,
                    target_margin_before_fee=ZERO,
                    spot_trade_price=spot_opens[spot],
                    swap_trade_price=swap_opens[spot],
                    cost_rate=cost_rate,
                )
            )
    pending = []
    for spot in SPOT_INSTRUMENTS:
        if plan[spot]["action"] not in {"OPEN", "RESIZE"}:
            continue
        target_notional = (
            decimal_value(plan[spot]["raw_spot_notional"], "raw target") * scale
        )
        quantity = target_notional / spot_opens[spot] if target_notional else ZERO
        target_margin = decimal_value(plan[spot]["raw_margin"], "raw margin") * scale
        sleeve = portfolio.sleeves[spot]
        cash_need = (quantity - sleeve.spot_quantity) * spot_opens[spot] + (
            target_margin - sleeve.margin_cash
        )
        pending.append((cash_need, spot, quantity, target_margin))
    for _, spot, quantity, target_margin in sorted(pending, key=lambda row: row[0]):
        output.append(
            portfolio.trade_target(
                spot=spot,
                new_quantity=quantity,
                target_margin_before_fee=target_margin,
                spot_trade_price=spot_opens[spot],
                swap_trade_price=swap_opens[spot],
                cost_rate=cost_rate,
            )
        )
    portfolio.assert_reconciled()
    return output


def _solve_scale(
    portfolio: Portfolio,
    *,
    plan: Mapping[str, Mapping[str, Any]],
    spot_opens: Mapping[str, Decimal],
    swap_opens: Mapping[str, Decimal],
    cost_rate: Decimal,
) -> Decimal:
    def constraints(scale: Decimal, *, flat_zero: bool = False) -> tuple[bool, bool]:
        """Return cash and active-margin feasibility without sequential artifacts.

        For positive scale, free cash is monotonically non-increasing in scale.
        Active post-fee margin is piecewise linear and can have both a strict
        lower and strict upper feasible bound.  Scale zero is the explicitly
        flat target for every new/resized sleeve.
        """
        cash = portfolio.free_cash
        margin_ok = True
        for spot in SPOT_INSTRUMENTS:
            state = portfolio.sleeves[spot]
            action = str(plan[spot]["action"])
            if action != "CLOSE" or not state.active:
                continue
            spot_fee = state.spot_quantity * spot_opens[spot] * cost_rate
            swap_fee = state.short_quantity * swap_opens[spot] * cost_rate
            remaining_margin = state.margin_cash - swap_fee
            margin_ok &= remaining_margin >= 0
            cash += state.spot_quantity * spot_opens[spot] - spot_fee + remaining_margin
        for spot in SPOT_INSTRUMENTS:
            action = str(plan[spot]["action"])
            if action not in {"OPEN", "RESIZE"}:
                continue
            state = portfolio.sleeves[spot]
            target_notional = (
                decimal_value(plan[spot]["raw_spot_notional"], "raw target") * scale
            )
            target_quantity = (
                target_notional / spot_opens[spot] if target_notional else ZERO
            )
            target_margin = (
                decimal_value(plan[spot]["raw_margin"], "raw margin") * scale
            )
            spot_fee = (
                abs(target_quantity - state.spot_quantity)
                * spot_opens[spot]
                * cost_rate
            )
            swap_fee = (
                abs(target_quantity - state.short_quantity)
                * swap_opens[spot]
                * cost_rate
            )
            if target_quantity == 0 and flat_zero:
                remaining_margin = state.margin_cash - swap_fee
                margin_ok &= remaining_margin >= 0
                cash += (
                    state.spot_quantity * spot_opens[spot] - spot_fee + remaining_margin
                )
            else:
                cash -= (
                    (target_quantity - state.spot_quantity) * spot_opens[spot]
                    + spot_fee
                    + target_margin
                    - state.margin_cash
                )
                margin_ok &= target_margin - swap_fee > 0
        return cash >= 0, margin_ok

    with localcontext() as context:
        context.prec = 60
        flat_zero_feasible = all(constraints(ZERO, flat_zero=True))

        # First find the closed upper bound imposed by free cash.  Transaction
        # costs are below one, so every individual cash term is non-increasing
        # in the common positive scale even across a resize direction change.
        if constraints(ONE)[0]:
            cash_upper = ONE
        elif not constraints(ZERO)[0]:
            if flat_zero_feasible:
                return ZERO
            raise C9AHistoricalReplayError("no feasible C9A target scale")
        else:
            cash_low, cash_high = ZERO, ONE
            for _ in range(SOLVER_ITERATIONS):
                middle = (cash_low + cash_high) / Decimal(2)
                if constraints(middle)[0]:
                    cash_low = middle
                else:
                    cash_high = middle
            cash_upper = cash_low

        # For one OPEN/RESIZE sleeve, post-fee margin is
        #   m*s - k*abs(c*s-q) > 0.
        # Intersect every sleeve's exact strict interval before maximizing.
        margin_lower = ZERO
        margin_upper = ONE
        for spot in SPOT_INSTRUMENTS:
            if str(plan[spot]["action"]) not in {"OPEN", "RESIZE"}:
                continue
            state = portfolio.sleeves[spot]
            raw_notional = decimal_value(plan[spot]["raw_spot_notional"], "raw target")
            raw_margin = decimal_value(plan[spot]["raw_margin"], "raw margin")
            if raw_notional <= 0 or raw_margin <= 0:
                if flat_zero_feasible:
                    return ZERO
                raise C9AHistoricalReplayError("no feasible C9A target scale")
            quantity_slope = raw_notional / spot_opens[spot]
            fee_per_quantity = swap_opens[spot] * cost_rate
            fee_slope = fee_per_quantity * quantity_slope
            lower = fee_per_quantity * state.short_quantity / (raw_margin + fee_slope)
            margin_lower = max(margin_lower, lower)
            if fee_slope > raw_margin:
                upper = (
                    fee_per_quantity * state.short_quantity / (fee_slope - raw_margin)
                )
                margin_upper = min(margin_upper, upper)
            elif fee_slope == raw_margin and state.short_quantity == 0:
                if flat_zero_feasible:
                    return ZERO
                raise C9AHistoricalReplayError("no feasible C9A target scale")

        upper = min(ONE, cash_upper, margin_upper)
        if upper <= margin_lower:
            if flat_zero_feasible:
                return ZERO
            raise C9AHistoricalReplayError("no feasible C9A target scale")

        interior = (margin_lower + upper) / Decimal(2)
        if not all(constraints(interior)):
            if flat_zero_feasible:
                return ZERO
            raise C9AHistoricalReplayError("no feasible C9A target scale")
        if all(constraints(upper)):
            return upper

        # A margin upper bound is strict.  Return the greatest feasible Decimal
        # approximation after the frozen number of bisection iterations.
        low, high = interior, upper
        for _ in range(SOLVER_ITERATIONS):
            middle = (low + high) / Decimal(2)
            if all(constraints(middle)):
                low = middle
            else:
                high = middle
        if all(constraints(low)):
            return low
        if flat_zero_feasible:
            return ZERO
        raise C9AHistoricalReplayError("no feasible C9A target scale")


def _paired_turnover(
    trades: Sequence[Mapping[str, str]],
    *,
    denominator: Decimal,
) -> Decimal:
    if denominator <= 0:
        raise C9AHistoricalReplayError("turnover denominator must be positive")
    paired = ZERO
    for trade in trades:
        paired += (
            abs(Decimal(trade["spot_delta"])) * Decimal(trade["spot_trade_price"])
            + abs(Decimal(trade["short_delta"])) * Decimal(trade["swap_trade_price"])
        ) / Decimal(2)
    return paired / denominator


def _maximum_drawdown(values: Sequence[Decimal]) -> Decimal:
    if not values or any(value <= 0 or not value.is_finite() for value in values):
        raise C9AHistoricalReplayError("equity path must be finite and positive")
    peak = values[0]
    maximum = ZERO
    for value in values:
        peak = max(peak, value)
        maximum = max(maximum, ONE - value / peak)
    return maximum


def _weekly_bucket(
    *,
    window_id: str,
    index: int,
    start: datetime,
    end: datetime,
    start_equity: Decimal,
    end_equity: Decimal,
    start_components: Mapping[str, Decimal],
    end_components: Mapping[str, Decimal],
    active: bool,
    risk_exit: bool,
) -> dict[str, Any]:
    delta = component_delta(end_components, start_components)
    pnl = end_equity - start_equity
    residual = pnl - component_net(delta)
    if abs(residual) > RECONCILIATION_TOLERANCE:
        raise C9AHistoricalReplayError(f"weekly reconciliation residual: {residual}")
    return {
        "window_id": window_id,
        "week_index": index,
        "start": iso(start),
        "end_exclusive": iso(end),
        "start_equity": str(start_equity),
        "end_equity": str(end_equity),
        "weekly_pnl": str(pnl),
        "weekly_return": str(pnl / start_equity),
        "components": {key: str(value) for key, value in delta.items()},
        "reconciliation_residual": str(residual),
        "active": active,
        "risk_exit": risk_exit,
    }


def _simulate_carry(
    *,
    window_id: str,
    policy: str,
    cost_label: str,
    spot_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    swap_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    marks: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
    funding: Mapping[str, tuple[tuple[datetime, Decimal], ...]],
) -> dict[str, Any]:
    if policy not in {"candidate", "always_on"} or cost_label not in COST_RATES:
        raise C9AHistoricalReplayError("unknown C9A replay identity")
    window = window_by_id(window_id)
    cost_rate = COST_RATES[cost_label]
    portfolio = Portfolio.create(STARTING_EQUITY)
    window_funding = {
        swap: tuple(
            (stamp, rate)
            for stamp, rate in funding[swap]
            if window.start <= stamp < window.end_exclusive
        )
        for swap in SWAP_INSTRUMENTS
    }
    exact_funding: dict[datetime, list[tuple[str, Decimal]]] = defaultdict(list)
    interior_funding: dict[datetime, list[tuple[datetime, str, Decimal]]] = defaultdict(
        list
    )
    for swap, rows in window_funding.items():
        for stamp, rate in rows:
            if stamp.minute == stamp.second == stamp.microsecond == 0:
                exact_funding[stamp].append((swap, rate))
            else:
                interior_funding[
                    stamp.replace(minute=0, second=0, microsecond=0)
                ].append((stamp, swap, rate))
    decisions = []
    signals = []
    trade_events = []
    funding_events = []
    price_events = []
    risk_events = []
    turnover_events = []
    equity_path: list[Decimal] = [STARTING_EQUITY]
    hourly_equity = [
        {
            "timestamp": iso(window.start),
            "equity": str(STARTING_EQUITY),
            "kind": "WINDOW_START",
        }
    ]
    weekly = []
    week_start = window.start
    week_start_equity = STARTING_EQUITY
    week_start_components = portfolio.components()
    week_active = False
    week_risk_exit = False
    accounted_funding = 0
    active_funding = 0
    gross_receipts = ZERO
    gross_payments = ZERO

    def risk_observation(spot: str, stamp: datetime, source: str) -> None:
        nonlocal week_risk_exit
        swap = SPOT_TO_SWAP[spot]
        predecessor_stamp, mark_price = _predecessor(stamp, marks[swap], "close")
        _, spot_price = _predecessor(stamp, spot_trade[spot], "close")
        observation = portfolio.observe_risk(
            spot=spot, mark_price=mark_price, spot_price=spot_price
        )
        if observation.get("active"):
            risk_events.append(
                {
                    "timestamp": iso(stamp),
                    "spot_instrument": spot,
                    "source": source,
                    "price_source_timestamp": iso(predecessor_stamp),
                    **observation,
                }
            )
            week_risk_exit = week_risk_exit or bool(observation.get("new_breach"))

    current = window.start
    while current <= window.end_exclusive:
        spot_opens, swap_opens = _next_hour_values(
            current, spot_trade=spot_trade, swap_trade=swap_trade
        )
        price_events.append(
            {
                "timestamp": iso(current),
                "kind": "OPEN_TRANSITION",
                "rows": portfolio.accrue_to(
                    spot_prices=spot_opens, perpetual_prices=swap_opens
                ),
            }
        )

        if current == window.end_exclusive:
            pre_equity = portfolio.equity()
            terminal_trades = []
            for spot in SPOT_INSTRUMENTS:
                if portfolio.sleeves[spot].active:
                    terminal_trades.append(
                        portfolio.trade_target(
                            spot=spot,
                            new_quantity=ZERO,
                            target_margin_before_fee=ZERO,
                            spot_trade_price=spot_opens[spot],
                            swap_trade_price=swap_opens[spot],
                            cost_rate=cost_rate,
                        )
                    )
            if terminal_trades:
                ratio = _paired_turnover(terminal_trades, denominator=pre_equity)
                turnover_events.append(
                    {
                        "timestamp": iso(current),
                        "kind": "TERMINAL_CLOSE",
                        "pre_event_equity": str(pre_equity),
                        "paired_turnover_ratio": str(ratio),
                    }
                )
                trade_events.append(
                    {
                        "timestamp": iso(current),
                        "kind": "TERMINAL_CLOSE",
                        "target_scale": "0",
                        "pre_event_equity": str(pre_equity),
                        "trades": terminal_trades,
                    }
                )
            final_equity = portfolio.equity()
            weekly.append(
                _weekly_bucket(
                    window_id=window_id,
                    index=len(weekly),
                    start=week_start,
                    end=current,
                    start_equity=week_start_equity,
                    end_equity=final_equity,
                    start_components=week_start_components,
                    end_components=portfolio.components(),
                    active=week_active,
                    risk_exit=week_risk_exit,
                )
            )
            equity_path.append(final_equity)
            hourly_equity.append(
                {
                    "timestamp": iso(current),
                    "equity": str(final_equity),
                    "kind": "TERMINAL_POST_TRADE",
                }
            )
            break

        if current > window.start and current.weekday() == 0 and current.hour == 0:
            boundary_equity = portfolio.equity()
            weekly.append(
                _weekly_bucket(
                    window_id=window_id,
                    index=len(weekly),
                    start=week_start,
                    end=current,
                    start_equity=week_start_equity,
                    end_equity=boundary_equity,
                    start_components=week_start_components,
                    end_components=portfolio.components(),
                    active=week_active,
                    risk_exit=week_risk_exit,
                )
            )
            week_start = current
            week_start_equity = boundary_equity
            week_start_components = portfolio.components()
            week_active = any(sleeve.active for sleeve in portfolio.sleeves.values())
            week_risk_exit = False

        for swap, rate in sorted(exact_funding.get(current, [])):
            spot = next(key for key, value in SPOT_TO_SWAP.items() if value == swap)
            predecessor_stamp, predecessor_mark = _predecessor(
                current, marks[swap], "close"
            )
            active = portfolio.sleeves[spot].active
            pnl = portfolio.apply_funding(
                spot=spot, realized_rate=rate, preceding_mark=predecessor_mark
            )
            accounted_funding += 1
            active_funding += int(active)
            gross_receipts += max(pnl, ZERO)
            gross_payments += max(-pnl, ZERO)
            funding_events.append(
                {
                    "timestamp": iso(current),
                    "instrument": swap,
                    "realized_rate": str(rate),
                    "preceding_mark_timestamp": iso(predecessor_stamp),
                    "preceding_mark_close_time": iso(predecessor_stamp + HOUR),
                    "active_before": active,
                    "short_quantity": str(portfolio.sleeves[spot].short_quantity),
                    "funding_pnl": str(pnl),
                }
            )
            risk_observation(spot, current, "FUNDING")

        forced = []
        forced_pre_equity = portfolio.equity()
        for spot in SPOT_INSTRUMENTS:
            if portfolio.sleeves[spot].risk_exit_pending:
                row = portfolio.close_for_risk(
                    spot=spot,
                    timestamp=current,
                    spot_trade_price=spot_opens[spot],
                    swap_trade_price=swap_opens[spot],
                    cost_rate=cost_rate,
                )
                forced.append(row)
                ratio = _paired_turnover((row,), denominator=forced_pre_equity)
                turnover_events.append(
                    {
                        "timestamp": iso(current),
                        "kind": "RISK_CLOSE",
                        "spot_instrument": spot,
                        "pre_event_equity": str(forced_pre_equity),
                        "paired_turnover_ratio": str(ratio),
                    }
                )
                forced_pre_equity = portfolio.equity()
        if forced:
            week_risk_exit = True
            trade_events.append(
                {
                    "timestamp": iso(current),
                    "kind": "RISK_CLOSE",
                    "target_scale": "0",
                    "trades": forced,
                }
            )

        if current.weekday() == 0 and current.hour == 0:
            signal = build_signal(
                current, spot_trade=spot_trade, marks=marks, funding=funding
            )
            signals.append({"timestamp": iso(current), "assets": signal})
            eligible = (
                tuple(spot for spot in SPOT_INSTRUMENTS if signal[spot]["eligible"])
                if policy == "candidate"
                else SPOT_INSTRUMENTS
            )
            pre_equity = portfolio.equity()
            plan = _action_plan(
                portfolio,
                eligible=eligible,
                total_equity=pre_equity,
                spot_opens=spot_opens,
                timestamp=current,
            )
            scale = _solve_scale(
                portfolio,
                plan=plan,
                spot_opens=spot_opens,
                swap_opens=swap_opens,
                cost_rate=cost_rate,
            )
            trades = _apply_plan(
                portfolio,
                plan=plan,
                scale=scale,
                spot_opens=spot_opens,
                swap_opens=swap_opens,
                cost_rate=cost_rate,
            )
            if trades:
                ratio = _paired_turnover(trades, denominator=pre_equity)
                turnover_events.append(
                    {
                        "timestamp": iso(current),
                        "kind": "SCHEDULED_REBALANCE",
                        "pre_event_equity": str(pre_equity),
                        "paired_turnover_ratio": str(ratio),
                    }
                )
                trade_events.append(
                    {
                        "timestamp": iso(current),
                        "kind": "SCHEDULED_REBALANCE",
                        "target_scale": str(scale),
                        "pre_event_equity": str(pre_equity),
                        "trades": trades,
                    }
                )
            decisions.append(
                {
                    "timestamp": iso(current),
                    "policy": policy,
                    "eligible_assets": list(eligible),
                    "target_scale": str(scale),
                    "free_cash_after": str(portfolio.free_cash),
                    "actions": {
                        spot: {
                            **{
                                key: (
                                    str(value) if isinstance(value, Decimal) else value
                                )
                                for key, value in plan[spot].items()
                            },
                            "quantity_after": str(
                                portfolio.sleeves[spot].spot_quantity
                            ),
                            "short_after": str(portfolio.sleeves[spot].short_quantity),
                            "margin_after": str(portfolio.sleeves[spot].margin_cash),
                            "blocked_until": None
                            if portfolio.sleeves[spot].blocked_until is None
                            else iso(portfolio.sleeves[spot].blocked_until),
                        }
                        for spot in SPOT_INSTRUMENTS
                    },
                }
            )

        week_active = week_active or any(
            sleeve.active for sleeve in portfolio.sleeves.values()
        )

        for stamp, swap, rate in sorted(interior_funding.get(current, [])):
            spot = next(key for key, value in SPOT_TO_SWAP.items() if value == swap)
            predecessor_stamp, predecessor_mark = _predecessor(
                stamp, marks[swap], "close"
            )
            active = portfolio.sleeves[spot].active
            pnl = portfolio.apply_funding(
                spot=spot, realized_rate=rate, preceding_mark=predecessor_mark
            )
            accounted_funding += 1
            active_funding += int(active)
            gross_receipts += max(pnl, ZERO)
            gross_payments += max(-pnl, ZERO)
            funding_events.append(
                {
                    "timestamp": iso(stamp),
                    "instrument": swap,
                    "realized_rate": str(rate),
                    "preceding_mark_timestamp": iso(predecessor_stamp),
                    "preceding_mark_close_time": iso(predecessor_stamp + HOUR),
                    "active_before": active,
                    "short_quantity": str(portfolio.sleeves[spot].short_quantity),
                    "funding_pnl": str(pnl),
                }
            )
            risk_observation(spot, stamp, "FUNDING")

        spot_closes = {
            spot: spot_trade[spot][current]["close"] for spot in SPOT_INSTRUMENTS
        }
        mark_closes = {
            spot: marks[SPOT_TO_SWAP[spot]][current]["close"]
            for spot in SPOT_INSTRUMENTS
        }
        price_events.append(
            {
                "timestamp": iso(current + HOUR),
                "kind": "CLOSE_TRANSITION",
                "source_timestamp": iso(current),
                "rows": portfolio.accrue_to(
                    spot_prices=spot_closes, perpetual_prices=mark_closes
                ),
            }
        )
        for spot in SPOT_INSTRUMENTS:
            observation = portfolio.observe_risk(
                spot=spot,
                mark_price=mark_closes[spot],
                spot_price=spot_closes[spot],
            )
            if observation.get("active"):
                risk_events.append(
                    {
                        "timestamp": iso(current + HOUR),
                        "spot_instrument": spot,
                        "source": "HOURLY_CLOSE",
                        "price_source_timestamp": iso(current),
                        **observation,
                    }
                )
                week_risk_exit = week_risk_exit or bool(observation.get("new_breach"))
        equity = portfolio.equity()
        equity_path.append(equity)
        hourly_equity.append(
            {
                "timestamp": iso(current + HOUR),
                "equity": str(equity),
                "kind": "HOURLY_POST_EVENT",
            }
        )
        current += HOUR

    if (
        len(decisions) != EXPECTED_DECISIONS_PER_WINDOW
        or len(weekly) != EXPECTED_DECISIONS_PER_WINDOW
    ):
        raise C9AHistoricalReplayError("C9A decision or weekly-bucket count drift")
    if any(sleeve.active for sleeve in portfolio.sleeves.values()):
        raise C9AHistoricalReplayError("C9A window ended with an open sleeve")
    expected_funding = sum(len(rows) for rows in window_funding.values())
    if accounted_funding != expected_funding:
        raise C9AHistoricalReplayError(
            "C9A funding settlements were not accounted exactly once"
        )
    final_equity = portfolio.equity()
    components = portfolio.components()
    residual = final_equity - STARTING_EQUITY - component_net(components)
    if abs(residual) > RECONCILIATION_TOLERANCE:
        raise C9AHistoricalReplayError(f"window reconciliation residual: {residual}")
    asset_contributions = {
        sleeve.spot_instrument.split("-")[0]: sleeve.net_component_pnl()
        for sleeve in portfolio.sleeves.values()
    }
    return {
        "schema_version": 1,
        "stage": "C9A_WINDOW_REPLAY",
        "policy": policy,
        "window_id": window_id,
        "cost_label": cost_label,
        "cost_rate": str(cost_rate),
        "starting_equity": str(STARTING_EQUITY),
        "final_equity": str(final_equity),
        "net_return": str(final_equity / STARTING_EQUITY - ONE),
        "decision_count": len(decisions),
        "weekly_bucket_count": len(weekly),
        "weekly_buckets": weekly,
        "weekly_returns": [row["weekly_return"] for row in weekly],
        "maximum_drawdown": str(_maximum_drawdown(equity_path)),
        "annualized_one_way_paired_turnover": str(
            sum(
                (Decimal(row["paired_turnover_ratio"]) for row in turnover_events), ZERO
            )
            / Decimal("0.5")
        ),
        "gross_positive_funding_receipts": str(gross_receipts),
        "gross_funding_payments": str(gross_payments),
        "active_funding_settlement_count": active_funding,
        "accounted_funding_settlement_count": accounted_funding,
        "unaccounted_funding_settlement_count": expected_funding - accounted_funding,
        "active_week_count": sum(bool(row["active"]) for row in weekly),
        "collateral_buffer_breach_count": sum(
            sleeve.collateral_buffer_breaches for sleeve in portfolio.sleeves.values()
        ),
        "base_hedge_mismatch_count": sum(
            sleeve.hedge_mismatches for sleeve in portfolio.sleeves.values()
        ),
        "missing_decision_count": 0,
        "non_finite_state_count": 0,
        "non_positive_equity_state_count": 0,
        "reconciliation_failure_count": 0,
        "components": {key: str(value) for key, value in components.items()},
        "reconciliation_residual": str(residual),
        "asset_contributions": {
            key: str(value) for key, value in asset_contributions.items()
        },
        "signals": signals,
        "decisions": decisions,
        "trade_events": trade_events,
        "funding_events": funding_events,
        "price_events": price_events,
        "risk_events": risk_events,
        "turnover_events": turnover_events,
        "complete_hourly_equity_path": hourly_equity,
        "continuous_notional": True,
        "uses_contract_or_lot_metadata": False,
        "historical_data_status": HISTORICAL_DATA_STATUS,
        **safety_boundary(),
    }


def _cash_window(window_id: str, cost_label: str) -> dict[str, Any]:
    window = window_by_id(window_id)
    weekly = []
    for index, start in enumerate(decision_times(window)):
        weekly.append(
            {
                "window_id": window_id,
                "week_index": index,
                "start": iso(start),
                "end_exclusive": iso(start + timedelta(days=7)),
                "start_equity": str(STARTING_EQUITY),
                "end_equity": str(STARTING_EQUITY),
                "weekly_pnl": "0",
                "weekly_return": "0",
                "active": False,
            }
        )
    return {
        "schema_version": 1,
        "stage": "C9A_WINDOW_REPLAY",
        "policy": "cash",
        "window_id": window_id,
        "cost_label": cost_label,
        "starting_equity": str(STARTING_EQUITY),
        "final_equity": str(STARTING_EQUITY),
        "net_return": "0",
        "decision_count": 26,
        "weekly_bucket_count": 26,
        "weekly_buckets": weekly,
        "weekly_returns": ["0"] * 26,
        "maximum_drawdown": "0",
        "annualized_one_way_paired_turnover": "0",
        "components": {name: "0" for name in COMPONENT_NAMES},
        **safety_boundary(),
    }


def _spot_buy_hold_window(
    window_id: str,
    cost_label: str,
    spot_trade: Mapping[str, Mapping[datetime, Mapping[str, Decimal]]],
) -> dict[str, Any]:
    window = window_by_id(window_id)
    rate = COST_RATES[cost_label]
    quantities = {}
    entry_cost = ZERO
    for spot in SPOT_INSTRUMENTS:
        price = spot_trade[spot][window.start]["open"]
        quantity = (STARTING_EQUITY / Decimal(2)) / (price * (ONE + rate))
        quantities[spot] = quantity
        entry_cost += quantity * price * rate

    def marked(stamp: datetime, *, boundary_open: bool = False) -> Decimal:
        field = "open" if boundary_open else "close"
        source = stamp if boundary_open else stamp - HOUR
        return sum(
            (
                quantities[spot] * spot_trade[spot][source][field]
                for spot in SPOT_INSTRUMENTS
            ),
            ZERO,
        )

    weekly = []
    start_equity = STARTING_EQUITY
    for index, start in enumerate(decision_times(window)):
        end = start + timedelta(days=7)
        if end == window.end_exclusive:
            gross = marked(end, boundary_open=True)
            exit_cost = sum(
                (
                    quantities[spot] * spot_trade[spot][end]["open"] * rate
                    for spot in SPOT_INSTRUMENTS
                ),
                ZERO,
            )
            end_equity = gross - exit_cost
        else:
            end_equity = marked(end, boundary_open=True)
        pnl = end_equity - start_equity
        weekly.append(
            {
                "window_id": window_id,
                "week_index": index,
                "start": iso(start),
                "end_exclusive": iso(end),
                "start_equity": str(start_equity),
                "end_equity": str(end_equity),
                "weekly_pnl": str(pnl),
                "weekly_return": str(pnl / start_equity),
                "active": True,
            }
        )
        start_equity = end_equity
    final = start_equity
    path = [STARTING_EQUITY]
    current = window.start
    while current < window.end_exclusive:
        path.append(marked(current + HOUR))
        current += HOUR
    path.append(final)
    return {
        "schema_version": 1,
        "stage": "C9A_WINDOW_REPLAY",
        "policy": "spot_buy_and_hold",
        "window_id": window_id,
        "cost_label": cost_label,
        "starting_equity": str(STARTING_EQUITY),
        "final_equity": str(final),
        "net_return": str(final / STARTING_EQUITY - ONE),
        "decision_count": 26,
        "weekly_bucket_count": 26,
        "weekly_buckets": weekly,
        "weekly_returns": [row["weekly_return"] for row in weekly],
        "maximum_drawdown": str(_maximum_drawdown(path)),
        "annualized_one_way_paired_turnover": "0",
        "entry_cost": str(entry_cost),
        "exit_cost": str(
            sum(
                (
                    quantities[spot]
                    * spot_trade[spot][window.end_exclusive]["open"]
                    * rate
                    for spot in SPOT_INSTRUMENTS
                ),
                ZERO,
            )
        ),
        "quantities": {key: str(value) for key, value in quantities.items()},
        **safety_boundary(),
    }


def evaluate_historical_window(
    *,
    window_id: str,
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    if set(trade_rows) != {*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS}:
        raise C9AHistoricalReplayError("C9A trade instrument set mismatch")
    if set(mark_rows) != set(SWAP_INSTRUMENTS) or set(funding_rows) != set(
        SWAP_INSTRUMENTS
    ):
        raise C9AHistoricalReplayError("C9A mark or funding instrument set mismatch")
    window = window_by_id(window_id)
    spot_trade = {
        spot: _index_prices(trade_rows[spot], instrument=spot, fields=("open", "close"))
        for spot in SPOT_INSTRUMENTS
    }
    swap_trade = {
        swap: _index_prices(trade_rows[swap], instrument=swap, fields=("open", "close"))
        for swap in SWAP_INSTRUMENTS
    }
    marks = {
        swap: _index_prices(mark_rows[swap], instrument=swap, fields=("close",))
        for swap in SWAP_INSTRUMENTS
    }
    funding = {
        swap: _index_funding(funding_rows[swap], instrument=swap)
        for swap in SWAP_INSTRUMENTS
    }
    for spot in SPOT_INSTRUMENTS:
        _require_hours(
            spot_trade[spot],
            start=window.start - 2 * HOUR,
            end_exclusive=window.end_exclusive + HOUR,
            label=f"{spot} trade",
        )
    for swap in SWAP_INSTRUMENTS:
        _require_hours(
            swap_trade[swap],
            start=window.start,
            end_exclusive=window.end_exclusive + HOUR,
            label=f"{swap} trade",
        )
        _require_hours(
            marks[swap],
            start=window.start - 2 * HOUR,
            end_exclusive=window.end_exclusive,
            label=f"{swap} mark",
        )
    replays: dict[str, dict[str, Any]] = {
        policy: {} for policy in ("candidate", "always_on", "cash", "spot_buy_and_hold")
    }
    for cost_label in COST_RATES:
        replays["candidate"][cost_label] = _simulate_carry(
            window_id=window_id,
            policy="candidate",
            cost_label=cost_label,
            spot_trade=spot_trade,
            swap_trade=swap_trade,
            marks=marks,
            funding=funding,
        )
        replays["always_on"][cost_label] = _simulate_carry(
            window_id=window_id,
            policy="always_on",
            cost_label=cost_label,
            spot_trade=spot_trade,
            swap_trade=swap_trade,
            marks=marks,
            funding=funding,
        )
        replays["cash"][cost_label] = _cash_window(window_id, cost_label)
        replays["spot_buy_and_hold"][cost_label] = _spot_buy_hold_window(
            window_id, cost_label, spot_trade
        )
    return {
        "schema_version": 1,
        "stage": "C9A_WINDOW_EVALUATION",
        "window": window.to_dict(),
        "result_cell_count": 12,
        "replays": replays,
        "within_stage_candidate_count": 1,
        "within_stage_dsr_used": False,
        "weekly_statistic": "PSR_NOT_DSR",
        "program_level_sequential_history_corrected": False,
        "historical_data_status": HISTORICAL_DATA_STATUS,
        **safety_boundary(),
    }


def _statistics(values: Sequence[Decimal]) -> dict[str, Any]:
    floats = [float(value) for value in values]
    if len(floats) != 130 or not all(math.isfinite(value) for value in floats):
        raise C9AHistoricalReplayError(
            "pooled weekly return vector must have 130 finite values"
        )
    sample_std = stdev(floats)
    if not math.isfinite(sample_std) or sample_std <= 0:
        return {
            "n": 130,
            "mean": float(mean(floats)),
            "sample_std": float(sample_std),
            "weekly_sharpe": 0.0,
            "annualized_weekly_sharpe": 0.0,
            "unbiased_skewness": 0.0,
            "unbiased_ordinary_kurtosis": 0.0,
            "psr_probability": 0.0,
            "valid": False,
        }
    average = mean(floats)
    weekly_sharpe = average / sample_std
    sample_skew = float(skew(floats, bias=False))
    ordinary_kurtosis = float(kurtosis(floats, fisher=False, bias=False))
    radicand = (
        1
        - sample_skew * weekly_sharpe
        + ((ordinary_kurtosis - 1) / 4) * weekly_sharpe**2
    )
    valid = math.isfinite(radicand) and radicand > 0
    probability = (
        float(norm.cdf(weekly_sharpe * math.sqrt(129) / math.sqrt(radicand)))
        if valid
        else 0.0
    )
    return {
        "n": 130,
        "mean": float(average),
        "sample_std": float(sample_std),
        "weekly_sharpe": float(weekly_sharpe),
        "annualized_weekly_sharpe": float(weekly_sharpe * math.sqrt(52)),
        "unbiased_skewness": sample_skew,
        "unbiased_ordinary_kurtosis": ordinary_kurtosis,
        "psr_probability": probability,
        "valid": valid
        and all(
            math.isfinite(value)
            for value in (sample_skew, ordinary_kurtosis, probability)
        ),
    }


def _positive_share(values: Mapping[str, Decimal], count: int = 1) -> Decimal | None:
    positive = sorted((max(value, ZERO) for value in values.values()), reverse=True)
    denominator = sum(positive, ZERO)
    return None if denominator <= 0 else sum(positive[:count], ZERO) / denominator


def _pool_policy(
    windows: Mapping[str, Any], *, policy: str, cost_label: str
) -> dict[str, Any]:
    ordered = [
        windows[f"W{index}"]["replays"][policy][cost_label] for index in range(1, 6)
    ]
    final_equities = [Decimal(row["final_equity"]) for row in ordered]
    weekly_returns = [
        Decimal(value) for row in ordered for value in row["weekly_returns"]
    ]
    weekly_pnl = {
        f"W{index}-week-{week}": Decimal(bucket["weekly_pnl"])
        for index, row in enumerate(ordered, start=1)
        for week, bucket in enumerate(row["weekly_buckets"])
    }
    output = {
        "policy": policy,
        "cost_label": cost_label,
        "aggregate_return": str(sum(final_equities, ZERO) / Decimal(5000) - ONE),
        "window_returns": {
            f"W{index}": row["net_return"] for index, row in enumerate(ordered, start=1)
        },
        "window_pnl": {
            f"W{index}": str(Decimal(row["final_equity"]) - STARTING_EQUITY)
            for index, row in enumerate(ordered, start=1)
        },
        "weekly_returns": [str(value) for value in weekly_returns],
        "weekly_pnl": {key: str(value) for key, value in weekly_pnl.items()},
        "statistics": _statistics(weekly_returns),
        "maximum_drawdown": str(
            max(Decimal(row["maximum_drawdown"]) for row in ordered)
        ),
        "annualized_one_way_paired_turnover": str(
            sum(
                (
                    Decimal(row.get("annualized_one_way_paired_turnover", "0"))
                    for row in ordered
                ),
                ZERO,
            )
            / Decimal(5)
        ),
    }
    if policy in {"candidate", "always_on"}:
        components = {
            name: sum((Decimal(row["components"][name]) for row in ordered), ZERO)
            for name in COMPONENT_NAMES
        }
        costs = components["spot_cost"] + components["swap_cost"]
        receipts = sum(
            (Decimal(row["gross_positive_funding_receipts"]) for row in ordered), ZERO
        )
        output.update(
            {
                "components": {key: str(value) for key, value in components.items()},
                "total_trading_costs": str(costs),
                "gross_positive_funding_receipts": str(receipts),
                "funding_cost_coverage": None if costs <= 0 else str(receipts / costs),
                "active_weeks_total": sum(
                    int(row["active_week_count"]) for row in ordered
                ),
                "active_weeks_by_window": {
                    f"W{index}": int(row["active_week_count"])
                    for index, row in enumerate(ordered, start=1)
                },
                "active_funding_settlement_count": sum(
                    int(row["active_funding_settlement_count"]) for row in ordered
                ),
                "collateral_buffer_breach_count": sum(
                    int(row["collateral_buffer_breach_count"]) for row in ordered
                ),
                "base_hedge_mismatch_count": sum(
                    int(row["base_hedge_mismatch_count"]) for row in ordered
                ),
                "missing_decision_count": sum(
                    int(row["missing_decision_count"]) for row in ordered
                ),
                "unaccounted_funding_settlement_count": sum(
                    int(row["unaccounted_funding_settlement_count"]) for row in ordered
                ),
                "non_finite_state_count": sum(
                    int(row["non_finite_state_count"]) for row in ordered
                ),
                "non_positive_equity_state_count": sum(
                    int(row["non_positive_equity_state_count"]) for row in ordered
                ),
                "reconciliation_failure_count": sum(
                    int(row["reconciliation_failure_count"]) for row in ordered
                ),
                "asset_contributions": {
                    asset: str(
                        sum(
                            (
                                Decimal(row["asset_contributions"][asset])
                                for row in ordered
                            ),
                            ZERO,
                        )
                    )
                    for asset in ("BTC", "ETH")
                },
            }
        )
    return output


def summarize_w1_w5(windows: Mapping[str, Any]) -> dict[str, Any]:
    if set(windows) != {"W1", "W2", "W3", "W4", "W5"}:
        raise C9AHistoricalReplayError("C9A summary requires exactly W1-W5")
    pooled = {
        policy: {
            cost: _pool_policy(windows, policy=policy, cost_label=cost)
            for cost in COST_RATES
        }
        for policy in ("candidate", "always_on", "cash", "spot_buy_and_hold")
    }
    candidate = pooled["candidate"]["1.0x"]
    always = pooled["always_on"]["1.0x"]
    gates = {
        "all_windows_positive": all(
            Decimal(value) > 0 for value in candidate["window_returns"].values()
        ),
        "aggregate_expected_return_positive": Decimal(candidate["aggregate_return"])
        > 0,
        "aggregate_1_5x_return_positive": Decimal(
            pooled["candidate"]["1.5x"]["aggregate_return"]
        )
        > 0,
        "aggregate_2x_return_non_negative": Decimal(
            pooled["candidate"]["2.0x"]["aggregate_return"]
        )
        >= 0,
        "annualized_weekly_sharpe": Decimal(
            str(candidate["statistics"]["annualized_weekly_sharpe"])
        )
        >= Decimal("1.00"),
        "weekly_psr": Decimal(str(candidate["statistics"]["psr_probability"]))
        >= Decimal("0.95"),
        "maximum_drawdown": Decimal(candidate["maximum_drawdown"]) <= Decimal("0.10"),
        "zero_collateral_buffer_breaches": candidate["collateral_buffer_breach_count"]
        == 0,
        "zero_base_hedge_mismatches": candidate["base_hedge_mismatch_count"] == 0,
        "zero_missing_decisions": candidate["missing_decision_count"] == 0,
        "zero_unaccounted_funding": candidate["unaccounted_funding_settlement_count"]
        == 0,
        "zero_non_finite_states": candidate["non_finite_state_count"] == 0,
        "zero_non_positive_equity_states": candidate["non_positive_equity_state_count"]
        == 0,
        "zero_reconciliation_failures": candidate["reconciliation_failure_count"] == 0,
        "annualized_turnover": Decimal(candidate["annualized_one_way_paired_turnover"])
        <= Decimal("6.0"),
        "funding_cost_coverage": candidate["funding_cost_coverage"] is not None
        and Decimal(candidate["funding_cost_coverage"]) >= Decimal("2.0"),
        "active_weeks_total": candidate["active_weeks_total"] >= 52,
        "active_weeks_each_window": all(
            value >= 6 for value in candidate["active_weeks_by_window"].values()
        ),
        "active_funding_settlements": candidate["active_funding_settlement_count"]
        >= 100,
        "both_assets_positive": all(
            Decimal(value) > 0 for value in candidate["asset_contributions"].values()
        ),
    }
    asset_share = _positive_share(
        {key: Decimal(value) for key, value in candidate["asset_contributions"].items()}
    )
    window_share = _positive_share(
        {key: Decimal(value) for key, value in candidate["window_pnl"].items()}
    )
    week_values = {
        key: Decimal(value) for key, value in candidate["weekly_pnl"].items()
    }
    week_share = _positive_share(week_values)
    top_three = _positive_share(week_values, count=3)
    gates.update(
        {
            "asset_concentration": asset_share is not None
            and asset_share <= Decimal("0.70"),
            "window_concentration": window_share is not None
            and window_share <= Decimal("0.40"),
            "week_concentration": week_share is not None
            and week_share <= Decimal("0.15"),
            "top_three_week_concentration": top_three is not None
            and top_three <= Decimal("0.35"),
            "return_delta_vs_always_on": Decimal(candidate["aggregate_return"])
            - Decimal(always["aggregate_return"])
            > 0,
            "sharpe_delta_vs_always_on": Decimal(
                str(candidate["statistics"]["annualized_weekly_sharpe"])
            )
            - Decimal(str(always["statistics"]["annualized_weekly_sharpe"]))
            >= Decimal("0.10"),
            "drawdown_not_worse_than_always_on": Decimal(candidate["maximum_drawdown"])
            <= Decimal(always["maximum_drawdown"]),
            "turnover_not_worse_than_always_on": Decimal(
                candidate["annualized_one_way_paired_turnover"]
            )
            <= Decimal(always["annualized_one_way_paired_turnover"]),
        }
    )
    selected = all(gates.values())
    return {
        "schema_version": 1,
        "stage": "C9A_H1_H5_POOLED_SUMMARY",
        "pooled": pooled,
        "eligibility_gates": gates,
        "rejection_reasons": [key for key, value in gates.items() if not value],
        "selected_policy": CANDIDATE_ID if selected else None,
        "overall_economic_verdict": "ECONOMIC_PASS" if selected else "ECONOMIC_FAIL",
        "within_stage_candidate_count": 1,
        "within_stage_dsr_used": False,
        "weekly_statistic": "PSR_NOT_DSR",
        "program_level_sequential_history_corrected": False,
        "historical_data_status": HISTORICAL_DATA_STATUS,
        "execution_feasibility_established": False,
        **safety_boundary(),
    }
