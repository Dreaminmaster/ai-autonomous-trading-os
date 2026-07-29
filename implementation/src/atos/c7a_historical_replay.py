"""Deterministic H1-H5 C7A replay over retained official OKX public rows.

The replay is research-only. It has no network client, account access, order
submission, Paper balance mutation, Shadow side effect, or Live transition.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from atos.c7a_contract import (
    INSTRUMENTS,
    MARK_CLOSE_COUNT,
    MAXIMUM_BETA,
    MAXIMUM_GROSS_NOTIONAL,
    MINIMUM_BETA,
    MINIMUM_POSITIVE_DAYS,
    MINIMUM_PROJECTED_CARRY_28D,
    MINIMUM_R_SQUARED,
    ONE_SIDE_COSTS,
)
from atos.c7a_funding_dispersion import estimate_ols_beta, should_resize
from atos.c7a_historical_schedule import (
    decision_times,
    required_source_bounds,
    window_by_id,
)

COST_LABELS = ("1.0x", "1.5x", "2.0x")
POLICIES = (
    "candidate",
    "cash",
    "always_on_funding_rank",
    "equal_notional_funding_rank",
)
HOUR = timedelta(hours=1)
WEEK_HOURS = 168
LOOKBACK = timedelta(days=28)


class C7AHistoricalReplayError(RuntimeError):
    """Raised when retained rows or deterministic replay fail closed."""


@dataclass(frozen=True)
class HistoricalSignal:
    decision_time: str
    eligible: bool
    reason: str
    high_funding_instrument: str | None
    low_funding_instrument: str | None
    funding_sums_28d: Mapping[str, float]
    beta: float | None
    r_squared: float | None
    long_weight: float
    short_weight: float
    projected_carry_28d: float
    positive_daily_spreads: int
    target_weights: Mapping[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parsed_stamp(value: Any, label: str) -> datetime:
    try:
        parsed = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except (TypeError, ValueError) as exc:
        raise C7AHistoricalReplayError(f"invalid {label}: {value!r}") from exc
    if parsed.tzinfo is None:
        raise C7AHistoricalReplayError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def _stamp(value: Any, label: str) -> datetime:
    result = _parsed_stamp(value, label)
    if any((result.minute, result.second, result.microsecond)):
        raise C7AHistoricalReplayError(f"{label} must be aligned to an exact hour")
    return result


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _number(value: Any, label: str, *, positive: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise C7AHistoricalReplayError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C7AHistoricalReplayError(f"{label} must be numeric") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise C7AHistoricalReplayError(f"{label} must be {qualifier}")
    return result


def _indexed_prices(
    rows: Sequence[Mapping[str, Any]],
    *,
    value_field: str,
    label: str,
) -> dict[datetime, float]:
    if not rows:
        raise C7AHistoricalReplayError(f"empty price series: {label}")
    output: dict[datetime, float] = {}
    previous: datetime | None = None
    for row in rows:
        current = _stamp(row.get("timestamp"), f"{label} timestamp")
        if previous is not None and current <= previous:
            raise C7AHistoricalReplayError(
                f"unordered or duplicate price series: {label}"
            )
        output[current] = _number(
            row.get(value_field), f"{label} {value_field}", positive=True
        )
        previous = current
    return output


def _indexed_funding(
    rows: Sequence[Mapping[str, Any]],
    *,
    label: str,
) -> dict[datetime, float]:
    if not rows:
        raise C7AHistoricalReplayError(f"empty funding series: {label}")
    output: dict[datetime, float] = {}
    previous: datetime | None = None
    for row in rows:
        current = _parsed_stamp(
            row.get("funding_time"), f"{label} funding timestamp"
        )
        if previous is not None and current <= previous:
            raise C7AHistoricalReplayError(
                f"unordered or duplicate funding series: {label}"
            )
        output[current] = _number(row.get("realized_rate"), f"{label} realized rate")
        previous = current
    return output


def _exact_hours(
    values: Mapping[datetime, float],
    *,
    start: datetime,
    end_exclusive: datetime,
    label: str,
) -> tuple[float, ...]:
    expected = int((end_exclusive - start) / HOUR)
    rows: list[float] = []
    for index in range(expected):
        current = start + index * HOUR
        try:
            rows.append(values[current])
        except KeyError as exc:
            raise C7AHistoricalReplayError(
                f"missing exact {label} hour: {_iso(current)}"
            ) from exc
    return tuple(rows)


def _funding_lookback(
    values: Mapping[datetime, float],
    *,
    decision: datetime,
    label: str,
) -> tuple[float, tuple[float, ...]]:
    start = decision - LOOKBACK
    selected = [
        (stamp, rate) for stamp, rate in values.items() if start <= stamp < decision
    ]
    if not selected:
        raise C7AHistoricalReplayError(f"empty 28-day funding lookback: {label}")
    daily: list[float] = []
    for offset in range(28):
        day_start = start + timedelta(days=offset)
        day_end = day_start + timedelta(days=1)
        rates = [rate for stamp, rate in selected if day_start <= stamp < day_end]
        if not rates:
            raise C7AHistoricalReplayError(
                f"missing daily funding evidence: {label} {_iso(day_start)}"
            )
        daily.append(sum(rates))
    return sum(daily), tuple(daily)


def _cash_signal(
    *,
    decision: datetime,
    reason: str,
    funding_sums: Mapping[str, float],
    high: str | None = None,
    low: str | None = None,
    beta: float | None = None,
    r_squared: float | None = None,
    projected: float = 0.0,
    positive_days: int = 0,
) -> HistoricalSignal:
    return HistoricalSignal(
        decision_time=_iso(decision),
        eligible=False,
        reason=reason,
        high_funding_instrument=high,
        low_funding_instrument=low,
        funding_sums_28d=dict(funding_sums),
        beta=beta,
        r_squared=r_squared,
        long_weight=0.0,
        short_weight=0.0,
        projected_carry_28d=projected,
        positive_daily_spreads=positive_days,
        target_weights={instrument: 0.0 for instrument in INSTRUMENTS},
    )


def compute_historical_signal(
    *,
    decision: datetime,
    mark_closes: Mapping[str, Mapping[datetime, float]],
    funding_rates: Mapping[str, Mapping[datetime, float]],
) -> HistoricalSignal:
    """Apply the unchanged 28-day C7A signal to one historical decision."""
    mark_returns: dict[str, tuple[float, ...]] = {}
    funding: dict[str, tuple[float, tuple[float, ...]]] = {}
    for instrument in INSTRUMENTS:
        closes = _exact_hours(
            mark_closes[instrument],
            start=decision - MARK_CLOSE_COUNT * HOUR,
            end_exclusive=decision,
            label=f"mark {instrument}",
        )
        if len(closes) != MARK_CLOSE_COUNT:
            raise C7AHistoricalReplayError("mark lookback must contain 673 closes")
        mark_returns[instrument] = tuple(
            math.log(closes[index] / closes[index - 1])
            for index in range(1, len(closes))
        )
        funding[instrument] = _funding_lookback(
            funding_rates[instrument], decision=decision, label=instrument
        )
    sums = {instrument: funding[instrument][0] for instrument in INSTRUMENTS}
    if sums[INSTRUMENTS[0]] == sums[INSTRUMENTS[1]]:
        return _cash_signal(decision=decision, reason="FUNDING_TIE", funding_sums=sums)
    high = max(INSTRUMENTS, key=lambda instrument: sums[instrument])
    low = INSTRUMENTS[0] if high == INSTRUMENTS[1] else INSTRUMENTS[1]
    regression = estimate_ols_beta(mark_returns[low], mark_returns[high])
    if not MINIMUM_BETA <= regression.beta <= MAXIMUM_BETA:
        return _cash_signal(
            decision=decision,
            reason="BETA_OUT_OF_RANGE",
            funding_sums=sums,
            high=high,
            low=low,
            beta=regression.beta,
            r_squared=regression.r_squared,
        )
    if regression.r_squared < MINIMUM_R_SQUARED:
        return _cash_signal(
            decision=decision,
            reason="R_SQUARED_BELOW_MINIMUM",
            funding_sums=sums,
            high=high,
            low=low,
            beta=regression.beta,
            r_squared=regression.r_squared,
        )
    long_weight = MAXIMUM_GROSS_NOTIONAL / (1.0 + regression.beta)
    short_weight = MAXIMUM_GROSS_NOTIONAL - long_weight
    projected = short_weight * sums[high] - long_weight * sums[low]
    daily_spreads = tuple(
        short_weight * high_rate - long_weight * low_rate
        for high_rate, low_rate in zip(funding[high][1], funding[low][1], strict=True)
    )
    positive_days = sum(value > 0 for value in daily_spreads)
    if sums[high] <= 0:
        reason = "HIGH_FUNDING_NOT_POSITIVE"
    elif projected <= MINIMUM_PROJECTED_CARRY_28D:
        reason = "PROJECTED_CARRY_BELOW_MINIMUM"
    elif positive_days < MINIMUM_POSITIVE_DAYS:
        reason = "POSITIVE_DAILY_SPREAD_COUNT_BELOW_MINIMUM"
    else:
        return HistoricalSignal(
            decision_time=_iso(decision),
            eligible=True,
            reason="ELIGIBLE",
            high_funding_instrument=high,
            low_funding_instrument=low,
            funding_sums_28d=sums,
            beta=regression.beta,
            r_squared=regression.r_squared,
            long_weight=long_weight,
            short_weight=short_weight,
            projected_carry_28d=projected,
            positive_daily_spreads=positive_days,
            target_weights={low: long_weight, high: -short_weight},
        )
    return _cash_signal(
        decision=decision,
        reason=reason,
        funding_sums=sums,
        high=high,
        low=low,
        beta=regression.beta,
        r_squared=regression.r_squared,
        projected=projected,
        positive_days=positive_days,
    )


def _policy_target(signal: HistoricalSignal, policy: str) -> dict[str, float]:
    if policy == "cash":
        return {instrument: 0.0 for instrument in INSTRUMENTS}
    if policy == "candidate":
        return dict(signal.target_weights)
    if policy == "equal_notional_funding_rank":
        if not signal.eligible or signal.high_funding_instrument is None:
            return {instrument: 0.0 for instrument in INSTRUMENTS}
        return {
            signal.low_funding_instrument: MAXIMUM_GROSS_NOTIONAL / 2,
            signal.high_funding_instrument: -MAXIMUM_GROSS_NOTIONAL / 2,
        }
    if policy == "always_on_funding_rank":
        if (
            signal.reason
            in {"FUNDING_TIE", "BETA_OUT_OF_RANGE", "R_SQUARED_BELOW_MINIMUM"}
            or signal.high_funding_instrument is None
            or signal.beta is None
        ):
            return {instrument: 0.0 for instrument in INSTRUMENTS}
        long_weight = MAXIMUM_GROSS_NOTIONAL / (1.0 + signal.beta)
        short_weight = MAXIMUM_GROSS_NOTIONAL - long_weight
        return {
            signal.low_funding_instrument: long_weight,
            signal.high_funding_instrument: -short_weight,
        }
    raise C7AHistoricalReplayError(f"unknown replay policy: {policy!r}")


def _orientation(weights: Mapping[str, float]) -> str:
    btc, eth = (weights[instrument] for instrument in INSTRUMENTS)
    if btc > 0 and eth < 0:
        return "LONG_BTC_SHORT_ETH"
    if eth > 0 and btc < 0:
        return "LONG_ETH_SHORT_BTC"
    if btc == 0 and eth == 0:
        return "CASH"
    raise C7AHistoricalReplayError("invalid two-leg replay orientation")


def _solve_post_cost_rebalance(
    *,
    equity_before: float,
    current_values: Mapping[str, float],
    target_weights: Mapping[str, float],
    fee_rate: float,
) -> dict[str, Any]:
    """Solve signed target notionals against equity remaining after trading costs."""
    equity_before = _number(equity_before, "rebalance equity", positive=True)
    fee_rate = _number(fee_rate, "rebalance fee rate")
    if (
        fee_rate < 0
        or set(current_values) != set(INSTRUMENTS)
        or set(target_weights) != set(INSTRUMENTS)
    ):
        raise C7AHistoricalReplayError("invalid post-cost rebalance inputs")
    current = {
        instrument: _number(current_values[instrument], f"current value {instrument}")
        for instrument in INSTRUMENTS
    }
    weights = {
        instrument: _number(target_weights[instrument], f"target weight {instrument}")
        for instrument in INSTRUMENTS
    }
    if sum(abs(value) for value in weights.values()) > MAXIMUM_GROSS_NOTIONAL + 1e-12:
        raise C7AHistoricalReplayError("post-cost target exceeds frozen gross cap")

    def equation(value: float) -> float:
        traded = sum(
            abs(weights[instrument] * value - current[instrument])
            for instrument in INSTRUMENTS
        )
        return value + fee_rate * traded - equity_before

    lower, upper = 0.0, equity_before
    if equation(lower) > 1e-12 or equation(upper) < -1e-12:
        raise C7AHistoricalReplayError("post-cost rebalance root is not bracketed")
    midpoint = upper
    iterations = 0
    for iterations in range(1, 201):
        midpoint = (lower + upper) / 2.0
        residual = equation(midpoint)
        if abs(residual) <= 1e-12 or upper - lower <= 1e-12:
            break
        if residual > 0:
            upper = midpoint
        else:
            lower = midpoint
    else:
        raise C7AHistoricalReplayError("post-cost rebalance root did not converge")
    target_values = {
        instrument: weights[instrument] * midpoint for instrument in INSTRUMENTS
    }
    trade_deltas = {
        instrument: target_values[instrument] - current[instrument]
        for instrument in INSTRUMENTS
    }
    fees = {
        instrument: fee_rate * abs(trade_deltas[instrument])
        for instrument in INSTRUMENTS
    }
    traded_notional = sum(abs(value) for value in trade_deltas.values())
    total_fee = sum(fees.values())
    gross = sum(abs(value) for value in target_values.values())
    residual = equity_before - total_fee - midpoint
    if abs(residual) > 1e-9 or gross > MAXIMUM_GROSS_NOTIONAL * midpoint + 1e-9:
        raise C7AHistoricalReplayError("post-cost rebalance accounting failure")
    return {
        "equity_before": equity_before,
        "equity_after": midpoint,
        "current_values": current,
        "target_weights": weights,
        "target_values": target_values,
        "trade_deltas": trade_deltas,
        "fees": fees,
        "traded_notional": traded_notional,
        "total_fee": total_fee,
        "gross_notional_after": gross,
        "gross_ratio_after": gross / midpoint,
        "residual": residual,
        "iterations": iterations,
    }


def _skipped_rebalance(
    *, equity: float, current_values: Mapping[str, float], target: Mapping[str, float]
) -> dict[str, Any]:
    gross = sum(abs(value) for value in current_values.values())
    return {
        "executed": False,
        "equity_before": equity,
        "equity_after": equity,
        "current_values": dict(current_values),
        "target_weights": dict(target),
        "target_values": dict(current_values),
        "trade_deltas": {instrument: 0.0 for instrument in INSTRUMENTS},
        "fees": {instrument: 0.0 for instrument in INSTRUMENTS},
        "traded_notional": 0.0,
        "total_fee": 0.0,
        "gross_notional_after": gross,
        "gross_ratio_after": gross / equity,
        "residual": 0.0,
        "iterations": 0,
    }


def replay_window(
    *,
    window_id: str,
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    policy: str = "candidate",
    cost_label: str = "1.0x",
) -> dict[str, Any]:
    """Replay one frozen 26-week window and liquidate at its end boundary."""
    window = window_by_id(window_id)
    decisions = decision_times(window)
    if policy not in POLICIES or cost_label not in COST_LABELS:
        raise C7AHistoricalReplayError("replay policy or cost label drift")
    if set(mark_rows) != set(INSTRUMENTS) or set(trade_rows) != set(INSTRUMENTS):
        raise C7AHistoricalReplayError("price-series instrument set mismatch")
    if set(funding_rows) != set(INSTRUMENTS):
        raise C7AHistoricalReplayError("funding-series instrument set mismatch")
    marks = {
        instrument: _indexed_prices(
            mark_rows[instrument], value_field="close", label=f"mark {instrument}"
        )
        for instrument in INSTRUMENTS
    }
    trades = {
        instrument: _indexed_prices(
            trade_rows[instrument], value_field="open", label=f"trade {instrument}"
        )
        for instrument in INSTRUMENTS
    }
    funding = {
        instrument: _indexed_funding(funding_rows[instrument], label=instrument)
        for instrument in INSTRUMENTS
    }
    funding_events: dict[datetime, list[tuple[datetime, str, float]]] = {}
    for instrument in INSTRUMENTS:
        for stamp, rate in funding[instrument].items():
            hour = stamp.replace(minute=0, second=0, microsecond=0)
            funding_events.setdefault(hour, []).append((stamp, instrument, rate))
    for events in funding_events.values():
        events.sort(key=lambda event: (event[0], event[1]))
    bounds = required_source_bounds(window)
    for instrument in INSTRUMENTS:
        _exact_hours(
            marks[instrument],
            start=_stamp(bounds["mark_start_inclusive"], "mark start"),
            end_exclusive=window.end_exclusive,
            label=f"mark source {instrument}",
        )
        _exact_hours(
            trades[instrument],
            start=window.first_scored_decision,
            end_exclusive=window.end_exclusive + HOUR,
            label=f"trade source {instrument}",
        )

    equity = 1.0
    units = {instrument: 0.0 for instrument in INSTRUMENTS}
    weekly_rows: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    processed_funding: dict[str, set[datetime]] = {
        instrument: set() for instrument in INSTRUMENTS
    }

    for week_index, decision in enumerate(decisions):
        starting = equity
        path = [equity]
        funding_pnl = receipts = payments = price_pnl = costs = traded = 0.0
        decision_rebalance: dict[str, Any] | None = None
        terminal_liquidation: dict[str, Any] | None = None
        signal = compute_historical_signal(
            decision=decision, mark_closes=marks, funding_rates=funding
        )
        signals.append(signal.to_dict())
        target = _policy_target(signal, policy)
        active_at_decision = any(target.values())
        orientation = _orientation(target)

        for hour_index in range(WEEK_HOURS):
            current = decision + hour_index * HOUR
            following = current + HOUR
            previous_marks = {
                instrument: marks[instrument][current - HOUR]
                for instrument in INSTRUMENTS
            }

            def apply_funding(
                events: Sequence[tuple[datetime, str, float]],
                event_units: Mapping[str, float],
                settlement_marks: Mapping[str, float],
            ) -> None:
                nonlocal equity, funding_pnl, receipts, payments
                for stamp, instrument, rate in events:
                    settlement_pnl = (
                        -event_units[instrument] * settlement_marks[instrument] * rate
                    )
                    equity += settlement_pnl
                    funding_pnl += settlement_pnl
                    if settlement_pnl >= 0:
                        receipts += settlement_pnl
                    else:
                        payments -= settlement_pnl
                    processed_funding[instrument].add(stamp)

            hour_events = funding_events.get(current, ())
            apply_funding(
                tuple(event for event in hour_events if event[0] == current),
                units,
                previous_marks,
            )

            hour_start_prices = previous_marks
            if hour_index == 0:
                current_opens = {
                    instrument: trades[instrument][current]
                    for instrument in INSTRUMENTS
                }
                execution_basis_pnl = sum(
                    units[instrument]
                    * (current_opens[instrument] - previous_marks[instrument])
                    for instrument in INSTRUMENTS
                )
                equity += execution_basis_pnl
                price_pnl += execution_basis_pnl
                current_values = {
                    instrument: units[instrument] * current_opens[instrument]
                    for instrument in INSTRUMENTS
                }
                current_weights = {
                    instrument: current_values[instrument] / equity
                    for instrument in INSTRUMENTS
                }
                execute = _orientation(current_weights) != orientation or should_resize(
                    current_weights, target
                )
                if execute:
                    solved = _solve_post_cost_rebalance(
                        equity_before=equity,
                        current_values=current_values,
                        target_weights=target,
                        fee_rate=ONE_SIDE_COSTS[cost_label],
                    )
                    decision_rebalance = {"executed": True, **solved}
                    equity = solved["equity_after"]
                    traded += solved["traded_notional"]
                    costs += solved["total_fee"]
                    units = {
                        instrument: solved["target_values"][instrument]
                        / current_opens[instrument]
                        for instrument in INSTRUMENTS
                    }
                else:
                    decision_rebalance = _skipped_rebalance(
                        equity=equity, current_values=current_values, target=target
                    )
                hour_start_prices = current_opens

            # A settlement completed after the hour boundary occurs after any
            # same-hour modeled trade. Its funding notional still uses the last
            # completed one-hour mark candle, without changing the source stamp.
            apply_funding(
                tuple(event for event in hour_events if event[0] > current),
                units,
                previous_marks,
            )

            current_marks = {
                instrument: marks[instrument][current] for instrument in INSTRUMENTS
            }
            hour_price = sum(
                units[instrument]
                * (current_marks[instrument] - hour_start_prices[instrument])
                for instrument in INSTRUMENTS
            )
            equity += hour_price
            price_pnl += hour_price

            if week_index == len(decisions) - 1 and hour_index == WEEK_HOURS - 1:
                liquidation_opens = {
                    instrument: trades[instrument][following]
                    for instrument in INSTRUMENTS
                }
                execution_basis_pnl = sum(
                    units[instrument]
                    * (liquidation_opens[instrument] - current_marks[instrument])
                    for instrument in INSTRUMENTS
                )
                equity += execution_basis_pnl
                price_pnl += execution_basis_pnl
                liquidation_values = {
                    instrument: units[instrument] * liquidation_opens[instrument]
                    for instrument in INSTRUMENTS
                }
                zero_target = {instrument: 0.0 for instrument in INSTRUMENTS}
                if any(liquidation_values.values()):
                    liquidation = _solve_post_cost_rebalance(
                        equity_before=equity,
                        current_values=liquidation_values,
                        target_weights=zero_target,
                        fee_rate=ONE_SIDE_COSTS[cost_label],
                    )
                    terminal_liquidation = {"executed": True, **liquidation}
                    equity = liquidation["equity_after"]
                    traded += liquidation["traded_notional"]
                    costs += liquidation["total_fee"]
                else:
                    terminal_liquidation = _skipped_rebalance(
                        equity=equity,
                        current_values=liquidation_values,
                        target=zero_target,
                    )
                units = {instrument: 0.0 for instrument in INSTRUMENTS}

            if not math.isfinite(equity) or equity <= 0:
                raise C7AHistoricalReplayError(
                    "replay equity became non-positive or non-finite"
                )
            path.append(equity)

        btc_start = marks[INSTRUMENTS[0]][decision - HOUR]
        btc_end = marks[INSTRUMENTS[0]][decision + (WEEK_HOURS - 1) * HOUR]
        weekly_rows.append(
            {
                "decision_time": _iso(decision),
                "cost_label": cost_label,
                "starting_equity": starting,
                "ending_equity": equity,
                "funding_pnl": funding_pnl,
                "gross_funding_receipts": receipts,
                "gross_funding_payments": payments,
                "relative_price_pnl": price_pnl,
                "negative_relative_price_pnl": min(price_pnl, 0.0),
                "traded_notional": traded,
                "trading_cost": costs,
                "turnover": traded / starting,
                "btc_mark_return": btc_end / btc_start - 1.0,
                "active": active_at_decision,
                "orientation": orientation,
                "missing_decision": False,
                "unaccounted_funding_settlements": 0,
                "equity_path": path,
                "decision_rebalance": decision_rebalance,
                "terminal_liquidation": terminal_liquidation,
            }
        )

    for instrument in INSTRUMENTS:
        expected = {
            stamp
            for stamp in funding[instrument]
            if window.first_scored_decision <= stamp < window.end_exclusive
        }
        if processed_funding[instrument] != expected:
            raise C7AHistoricalReplayError(
                f"unaccounted scored funding settlements: {instrument}"
            )
    if any(units.values()):
        raise C7AHistoricalReplayError(
            "window replay did not liquidate at the end boundary"
        )
    return {
        "schema_version": 1,
        "stage": "C7A_HISTORICAL_REPLAY",
        "window_id": window_id,
        "policy": policy,
        "cost_label": cost_label,
        "signals": signals,
        "weekly_rows": weekly_rows,
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "paper_side_effect": False,
        "shadow_side_effect": False,
        "live_state": "LIVE_FORBIDDEN",
    }


def _same(left: float, right: float, label: str) -> None:
    if not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-9):
        raise C7AHistoricalReplayError(f"historical reconciliation mismatch: {label}")


def _drawdown(curve: Sequence[float]) -> float:
    peak = curve[0]
    result = 0.0
    for value in curve:
        peak = max(peak, value)
        result = max(result, 1.0 - value / peak)
    return result


def _positive_share(values: Sequence[float], count: int) -> float | None:
    positive = sorted((value for value in values if value > 0), reverse=True)
    total = sum(positive)
    return None if total <= 0 else sum(positive[:count]) / total


def _statistics(values: Sequence[float]) -> dict[str, float]:
    if len(values) != 26:
        raise C7AHistoricalReplayError("historical weekly statistics require 26 rows")
    mean = sum(values) / 26
    centered = tuple(value - mean for value in values)
    m2 = sum(value * value for value in centered)
    if m2 == 0:
        if mean != 0:
            raise C7AHistoricalReplayError("nonzero weekly mean with zero variance")
        return {"weekly_sharpe_annualized": 0.0, "weekly_psr": 0.0}
    raw_sharpe = mean / math.sqrt(m2 / 25)
    variance = m2 / 26
    population_skew = (sum(value**3 for value in centered) / 26) / variance**1.5
    skewness = math.sqrt(26 * 25) / 24 * population_skew
    population_kurtosis = (sum(value**4 for value in centered) / 26) / variance**2
    kurtosis = ((26**2 - 1) * population_kurtosis - 3 * 25**2) / (24 * 23) + 3.0
    radicand = 1.0 - skewness * raw_sharpe + ((kurtosis - 1.0) / 4.0) * raw_sharpe**2
    if not math.isfinite(radicand) or radicand <= 0:
        raise C7AHistoricalReplayError("invalid historical weekly PSR radicand")
    z_score = raw_sharpe * math.sqrt(25) / math.sqrt(radicand)
    return {
        "weekly_sharpe_annualized": raw_sharpe * math.sqrt(52),
        "weekly_psr": 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0))),
    }


def _strategy_beta(strategy: Sequence[float], btc: Sequence[float]) -> float | None:
    mean_x = sum(btc) / 26
    mean_y = sum(strategy) / 26
    sxx = sum((value - mean_x) ** 2 for value in btc)
    if sxx <= 0:
        return None
    return (
        sum(
            (x_value - mean_x) * (y_value - mean_y)
            for x_value, y_value in zip(btc, strategy, strict=True)
        )
        / sxx
    )


def aggregate_candidate_window(
    *,
    window_id: str,
    rows: Sequence[Mapping[str, Any]],
    cost_label: str,
) -> dict[str, Any]:
    """Aggregate and reconcile one candidate cost replay."""
    expected_times = tuple(_iso(value) for value in decision_times(window_id))
    if cost_label not in COST_LABELS or len(rows) != 26:
        raise C7AHistoricalReplayError(
            "candidate aggregate identity or coverage mismatch"
        )
    curve: list[float] = []
    returns: list[float] = []
    weekly_pnl: list[float] = []
    btc_returns: list[float] = []
    active: list[bool] = []
    orientations: list[str] = []
    starts: list[float] = []
    ends: list[float] = []
    funding_total = receipts_total = costs_total = turnover_total = 0.0
    carry_equity: float | None = None
    previous: float | None = None

    for index, (row, expected_time) in enumerate(
        zip(rows, expected_times, strict=True)
    ):
        if _iso(_stamp(row.get("decision_time"), "decision time")) != expected_time:
            raise C7AHistoricalReplayError("candidate decision-grid mismatch")
        if row.get("cost_label") != cost_label:
            raise C7AHistoricalReplayError("candidate cost-label mismatch")
        start = _number(row.get("starting_equity"), "starting equity", positive=True)
        end = _number(row.get("ending_equity"), "ending equity", positive=True)
        funding = _number(row.get("funding_pnl"), "funding PnL")
        receipts = _number(row.get("gross_funding_receipts"), "funding receipts")
        payments = _number(row.get("gross_funding_payments"), "funding payments")
        relative = _number(row.get("relative_price_pnl"), "relative price PnL")
        negative = _number(
            row.get("negative_relative_price_pnl"), "negative relative price PnL"
        )
        traded = _number(row.get("traded_notional"), "traded notional")
        cost = _number(row.get("trading_cost"), "trading cost")
        turnover = _number(row.get("turnover"), "turnover")
        btc_return = _number(row.get("btc_mark_return"), "BTC mark return")
        if min(receipts, payments, traded, cost, turnover) < 0:
            raise C7AHistoricalReplayError(
                "candidate accounting contains a negative magnitude"
            )
        if previous is not None:
            _same(start, previous, f"candidate equity chain {index}")
        _same(funding, receipts - payments, f"candidate funding {index}")
        _same(turnover, traded / start, f"candidate turnover {index}")
        _same(cost, traded * ONE_SIDE_COSTS[cost_label], f"candidate cost {index}")
        _same(end, start + funding + relative - cost, f"candidate accounting {index}")
        if negative > 0 or negative > min(relative, 0.0) + 1e-9:
            raise C7AHistoricalReplayError(
                "negative relative-price decomposition mismatch"
            )
        is_active = row.get("active")
        orientation = row.get("orientation")
        if (
            not isinstance(is_active, bool)
            or (
                is_active
                and orientation not in {"LONG_BTC_SHORT_ETH", "LONG_ETH_SHORT_BTC"}
            )
            or (not is_active and orientation != "CASH")
        ):
            raise C7AHistoricalReplayError("candidate active/orientation mismatch")
        if (
            row.get("missing_decision") is not False
            or row.get("unaccounted_funding_settlements") != 0
        ):
            raise C7AHistoricalReplayError("candidate completeness evidence mismatch")
        path = row.get("equity_path")
        if (
            not isinstance(path, Sequence)
            or isinstance(path, (str, bytes))
            or len(path) != 169
        ):
            raise C7AHistoricalReplayError("candidate hourly path coverage mismatch")
        path_values = [_number(value, "hourly equity", positive=True) for value in path]
        _same(path_values[0], start, f"candidate path start {index}")
        _same(path_values[-1], end, f"candidate path end {index}")
        if curve:
            _same(curve[-1], path_values[0], f"candidate path chain {index}")
            curve.extend(path_values[1:])
        else:
            curve.extend(path_values)
            carry_equity = start
        starts.append(start)
        ends.append(end)
        weekly_return = end / start - 1.0
        returns.append(weekly_return)
        weekly_pnl.append(end - start)
        btc_returns.append(btc_return)
        active.append(is_active)
        orientations.append(str(orientation))
        funding_total += funding
        receipts_total += receipts
        costs_total += cost
        turnover_total += turnover
        assert carry_equity is not None
        carry_equity *= 1.0 + (funding + negative - cost) / start
        if not math.isfinite(carry_equity) or carry_equity <= 0:
            raise C7AHistoricalReplayError("carry-only stress equity is invalid")
        previous = end

    active_count = sum(active)
    active_orientations = [value for value in orientations if value != "CASH"]
    orientation_share = (
        max(active_orientations.count(value) for value in set(active_orientations))
        / active_count
        if active_count
        else None
    )
    assert carry_equity is not None
    result = {
        "schema_version": 1,
        "stage": "C7A_HISTORICAL_WINDOW_AGGREGATE",
        "status": "PASS",
        "window_id": window_id,
        "cost_label": cost_label,
        "decision_times": list(expected_times),
        "first_half_net_return": ends[12] / starts[0] - 1.0,
        "second_half_net_return": ends[-1] / starts[13] - 1.0,
        "aggregate_net_return": ends[-1] / starts[0] - 1.0,
        "maximum_drawdown": _drawdown(curve),
        "strategy_beta_to_btc": _strategy_beta(returns, btc_returns),
        "aggregate_funding_pnl": funding_total,
        "gross_funding_receipts_to_costs": (
            receipts_total / costs_total if costs_total > 0 else None
        ),
        "carry_only_stress_return": carry_equity / starts[0] - 1.0,
        "active_weeks": active_count,
        "first_half_active_weeks": sum(active[:13]),
        "second_half_active_weeks": sum(active[13:]),
        "maximum_orientation_share": orientation_share,
        "annualized_one_way_turnover": turnover_total * 2.0,
        "maximum_positive_week_pnl_share": _positive_share(weekly_pnl, 1),
        "maximum_top_three_positive_week_pnl_share": _positive_share(weekly_pnl, 3),
        "missing_decision_count": 0,
        "unaccounted_funding_settlement_count": 0,
        "non_positive_equity_count": 0,
        "live_state": "LIVE_FORBIDDEN",
    }
    result.update(_statistics(returns))
    return result


def aggregate_comparator_window(
    *, window_id: str, rows: Sequence[Mapping[str, Any]], comparator_id: str
) -> dict[str, Any]:
    if comparator_id not in POLICIES[1:] or len(rows) != 26:
        raise C7AHistoricalReplayError(
            "comparator aggregate identity or coverage mismatch"
        )
    expected_times = tuple(_iso(value) for value in decision_times(window_id))
    curve: list[float] = []
    returns: list[float] = []
    previous: float | None = None
    for index, (row, expected_time) in enumerate(
        zip(rows, expected_times, strict=True)
    ):
        if (
            _iso(_stamp(row.get("decision_time"), "comparator decision"))
            != expected_time
        ):
            raise C7AHistoricalReplayError("comparator decision-grid mismatch")
        start = _number(row.get("starting_equity"), "comparator start", positive=True)
        end = _number(row.get("ending_equity"), "comparator end", positive=True)
        if previous is not None:
            _same(start, previous, f"comparator equity chain {index}")
        path = row.get("equity_path")
        if (
            not isinstance(path, Sequence)
            or isinstance(path, (str, bytes))
            or len(path) != 169
        ):
            raise C7AHistoricalReplayError("comparator hourly path coverage mismatch")
        path_values = [
            _number(value, "comparator equity", positive=True) for value in path
        ]
        _same(path_values[0], start, f"comparator path start {index}")
        _same(path_values[-1], end, f"comparator path end {index}")
        if curve:
            _same(curve[-1], path_values[0], f"comparator path chain {index}")
            curve.extend(path_values[1:])
        else:
            curve.extend(path_values)
        returns.append(end / start - 1.0)
        previous = end
    result = {
        "schema_version": 1,
        "stage": "C7A_HISTORICAL_COMPARATOR_AGGREGATE",
        "status": "PASS",
        "window_id": window_id,
        "comparator_id": comparator_id,
        "decision_times": list(expected_times),
        "aggregate_net_return": curve[-1] / curve[0] - 1.0,
        "maximum_drawdown": _drawdown(curve),
        "live_state": "LIVE_FORBIDDEN",
    }
    result.update(_statistics(returns))
    return result


def decide_historical_window(
    *,
    expected: Mapping[str, Any],
    stress_1_5x: Mapping[str, Any],
    stress_2_0x: Mapping[str, Any],
    always_on: Mapping[str, Any],
) -> dict[str, Any]:
    """Apply the unchanged C7A gates to one preregistered historical window."""
    if (
        tuple(value.get("cost_label") for value in (expected, stress_1_5x, stress_2_0x))
        != COST_LABELS
    ):
        raise C7AHistoricalReplayError("historical aggregate cost identity mismatch")
    if always_on.get("comparator_id") != "always_on_funding_rank":
        raise C7AHistoricalReplayError("historical always-on identity mismatch")
    window_ids = {
        value.get("window_id")
        for value in (expected, stress_1_5x, stress_2_0x, always_on)
    }
    if len(window_ids) != 1:
        raise C7AHistoricalReplayError("historical aggregate window mismatch")
    checks = {
        "first_half_return": expected["first_half_net_return"] > 0,
        "second_half_return": expected["second_half_net_return"] > 0,
        "aggregate_expected_return": expected["aggregate_net_return"] > 0,
        "aggregate_1_5x_return": stress_1_5x["aggregate_net_return"] > 0,
        "aggregate_2_0x_return": stress_2_0x["aggregate_net_return"] >= 0,
        "weekly_sharpe": expected["weekly_sharpe_annualized"] >= 1.0,
        "weekly_psr": expected["weekly_psr"] >= 0.95,
        "maximum_drawdown": expected["maximum_drawdown"] <= 0.10,
        "strategy_beta_to_btc": expected["strategy_beta_to_btc"] is not None
        and abs(expected["strategy_beta_to_btc"]) <= 0.15,
        "aggregate_funding_pnl": expected["aggregate_funding_pnl"] > 0,
        "funding_receipts_to_costs": expected["gross_funding_receipts_to_costs"]
        is not None
        and expected["gross_funding_receipts_to_costs"] >= 2.0,
        "carry_only_stress": expected["carry_only_stress_return"] > 0,
        "always_on_return_increment": expected["aggregate_net_return"]
        > always_on["aggregate_net_return"],
        "always_on_sharpe_increment": expected["weekly_sharpe_annualized"]
        >= always_on["weekly_sharpe_annualized"] + 0.10,
        "active_weeks": expected["active_weeks"] >= 13,
        "first_half_active_weeks": expected["first_half_active_weeks"] >= 5,
        "second_half_active_weeks": expected["second_half_active_weeks"] >= 5,
        "orientation_concentration": expected["maximum_orientation_share"] is not None
        and expected["maximum_orientation_share"] <= 0.85,
        "annualized_turnover": expected["annualized_one_way_turnover"] <= 8.0,
        "maximum_positive_week_share": expected["maximum_positive_week_pnl_share"]
        is not None
        and expected["maximum_positive_week_pnl_share"] <= 0.25,
        "top_three_positive_week_share": expected[
            "maximum_top_three_positive_week_pnl_share"
        ]
        is not None
        and expected["maximum_top_three_positive_week_pnl_share"] <= 0.50,
        "complete_evidence": expected["missing_decision_count"] == 0
        and expected["unaccounted_funding_settlement_count"] == 0
        and expected["non_positive_equity_count"] == 0,
    }
    failed = [name for name, passed in checks.items() if not passed]
    return {
        "schema_version": 1,
        "stage": "C7A_HISTORICAL_WINDOW_DECISION",
        "status": "PASS",
        "window_id": window_ids.pop(),
        "decision": "SELECTED" if not failed else "REJECTED",
        "failed_gates": failed,
        "selected_policy": ("C7ABetaNeutralFundingDispersion" if not failed else None),
        "live_state": "LIVE_FORBIDDEN",
    }


def evaluate_historical_window(
    *,
    window_id: str,
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Run all fixed costs/comparators and return one complete producer result."""
    candidate_replays = {
        label: replay_window(
            window_id=window_id,
            mark_rows=mark_rows,
            trade_rows=trade_rows,
            funding_rows=funding_rows,
            policy="candidate",
            cost_label=label,
        )
        for label in COST_LABELS
    }
    comparator_replays = {
        comparator: replay_window(
            window_id=window_id,
            mark_rows=mark_rows,
            trade_rows=trade_rows,
            funding_rows=funding_rows,
            policy=comparator,
            cost_label="1.0x",
        )
        for comparator in POLICIES[1:]
    }
    candidate_aggregates = {
        label: aggregate_candidate_window(
            window_id=window_id,
            rows=candidate_replays[label]["weekly_rows"],
            cost_label=label,
        )
        for label in COST_LABELS
    }
    comparator_aggregates = {
        comparator: aggregate_comparator_window(
            window_id=window_id,
            rows=comparator_replays[comparator]["weekly_rows"],
            comparator_id=comparator,
        )
        for comparator in POLICIES[1:]
    }
    decision = decide_historical_window(
        expected=candidate_aggregates["1.0x"],
        stress_1_5x=candidate_aggregates["1.5x"],
        stress_2_0x=candidate_aggregates["2.0x"],
        always_on=comparator_aggregates["always_on_funding_rank"],
    )
    return {
        "schema_version": 1,
        "stage": "C7A_HISTORICAL_WINDOW_EVIDENCE",
        "window_id": window_id,
        "candidate_replays": candidate_replays,
        "comparator_replays": comparator_replays,
        "candidate_aggregates": candidate_aggregates,
        "comparator_aggregates": comparator_aggregates,
        "decision": decision,
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "paper_side_effect": False,
        "shadow_side_effect": False,
        "live_state": "LIVE_FORBIDDEN",
    }


def _pooled_statistics(values: Sequence[float]) -> dict[str, float]:
    count = len(values)
    if count != 130:
        raise C7AHistoricalReplayError(
            "pooled history requires exactly 130 weekly returns"
        )
    mean = sum(values) / count
    centered = tuple(value - mean for value in values)
    m2 = sum(value * value for value in centered)
    if m2 == 0:
        return {"weekly_sharpe_annualized": 0.0, "weekly_psr": 0.0}
    raw = mean / math.sqrt(m2 / (count - 1))
    variance = m2 / count
    population_skew = (sum(value**3 for value in centered) / count) / variance**1.5
    skewness = math.sqrt(count * (count - 1)) / (count - 2) * population_skew
    population_kurtosis = (sum(value**4 for value in centered) / count) / variance**2
    kurtosis = ((count**2 - 1) * population_kurtosis - 3 * (count - 1) ** 2) / (
        (count - 2) * (count - 3)
    ) + 3.0
    radicand = 1.0 - skewness * raw + ((kurtosis - 1.0) / 4.0) * raw**2
    if not math.isfinite(radicand) or radicand <= 0:
        raise C7AHistoricalReplayError("invalid pooled weekly PSR radicand")
    z_score = raw * math.sqrt(count - 1) / math.sqrt(radicand)
    return {
        "weekly_sharpe_annualized": raw * math.sqrt(52),
        "weekly_psr": 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0))),
    }


def summarize_h1_h5(
    window_evidence: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Produce a non-selective pooled summary and deterministic overall verdict.

    The frozen gates remain per-window. The project-level verdict is an engineering
    convention preregistered before data inspection: all five windows must be
    independently eligible for ``ECONOMIC_PASS``; otherwise the result is
    ``ECONOMIC_FAIL`` without selecting a best window.
    """
    required = tuple(f"H{index}" for index in range(1, 6))
    if tuple(window_evidence) != required:
        raise C7AHistoricalReplayError("pooled window identity or order mismatch")
    expected_weekly: list[float] = []
    pooled_cost_returns = {label: 1.0 for label in COST_LABELS}
    pooled_comparator_returns = {name: 1.0 for name in POLICIES[1:]}
    active_weeks = 0
    funding_pnl = costs = 0.0
    maximum_drawdown = 0.0
    per_window_decisions: dict[str, str] = {}

    for window_id in required:
        evidence = window_evidence[window_id]
        if evidence.get("window_id") != window_id:
            raise C7AHistoricalReplayError("pooled evidence window binding mismatch")
        per_window_decisions[window_id] = str(evidence["decision"]["decision"])
        for label in COST_LABELS:
            aggregate = evidence["candidate_aggregates"][label]
            pooled_cost_returns[label] *= 1.0 + _number(
                aggregate["aggregate_net_return"], "window aggregate return"
            )
        for name in POLICIES[1:]:
            aggregate = evidence["comparator_aggregates"][name]
            pooled_comparator_returns[name] *= 1.0 + _number(
                aggregate["aggregate_net_return"], "comparator aggregate return"
            )
        expected = evidence["candidate_aggregates"]["1.0x"]
        active_weeks += int(expected["active_weeks"])
        funding_pnl += _number(expected["aggregate_funding_pnl"], "funding PnL")
        maximum_drawdown = max(
            maximum_drawdown,
            _number(expected["maximum_drawdown"], "maximum drawdown"),
        )
        for row in evidence["candidate_replays"]["1.0x"]["weekly_rows"]:
            start = _number(
                row["starting_equity"], "pooled weekly start", positive=True
            )
            end = _number(row["ending_equity"], "pooled weekly end", positive=True)
            expected_weekly.append(end / start - 1.0)
            costs += _number(row["trading_cost"], "pooled trading cost")

    selected_count = sum(value == "SELECTED" for value in per_window_decisions.values())
    result = {
        "schema_version": 1,
        "stage": "C7A_H1_H5_POOLED_SUMMARY",
        "status": "PASS",
        "aggregation_rule": "ALL_FIVE_WINDOWS_MUST_PASS_UNCHANGED_GATES",
        "window_count": 5,
        "weekly_return_count": len(expected_weekly),
        "per_window_decisions": per_window_decisions,
        "selected_window_count": selected_count,
        "overall_economic_verdict": (
            "ECONOMIC_PASS" if selected_count == 5 else "ECONOMIC_FAIL"
        ),
        "pooled_cost_net_returns": {
            label: value - 1.0 for label, value in pooled_cost_returns.items()
        },
        "pooled_comparator_net_returns": {
            name: value - 1.0 for name, value in pooled_comparator_returns.items()
        },
        "maximum_window_drawdown": maximum_drawdown,
        "active_weeks": active_weeks,
        "aggregate_funding_pnl_on_window_normalized_equity": funding_pnl,
        "aggregate_trading_cost_on_window_normalized_equity": costs,
        "best_window_selection_performed": False,
        "retuning_authorized": False,
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "paper_side_effect": False,
        "shadow_side_effect": False,
        "live_state": "LIVE_FORBIDDEN",
    }
    result.update(_pooled_statistics(expected_weekly))
    return result
