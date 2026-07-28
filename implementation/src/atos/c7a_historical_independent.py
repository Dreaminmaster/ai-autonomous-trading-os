"""Physically separate aggregate and gate recomputation for C7A history.

This reviewer deliberately imports no C7A producer, replay, contract, or schedule
module. It consumes retained weekly rows and verifies every aggregate and gate.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

COST_LABELS = ("1.0x", "1.5x", "2.0x")
COST_RATES = {"1.0x": 0.0015, "1.5x": 0.00225, "2.0x": 0.003}
COMPARATORS = ("cash", "always_on_funding_rank", "equal_notional_funding_rank")
INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
MAXIMUM_GROSS_NOTIONAL = 0.50
MINIMUM_BETA = 0.50
MAXIMUM_BETA = 2.00
MINIMUM_R_SQUARED = 0.50
MINIMUM_PROJECTED_CARRY = 0.00225
MINIMUM_POSITIVE_DAYS = 19
MARK_CLOSE_COUNT = 673
WEEK_HOURS = 168
HOUR = timedelta(hours=1)
WINDOW_STARTS = {
    "H1": datetime(2024, 1, 1, tzinfo=UTC),
    "H2": datetime(2024, 7, 1, tzinfo=UTC),
    "H3": datetime(2024, 12, 30, tzinfo=UTC),
    "H4": datetime(2025, 6, 30, tzinfo=UTC),
    "H5": datetime(2025, 12, 29, tzinfo=UTC),
}


def _num(value: Any, label: str, *, positive: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or (positive and result <= 0):
        raise ValueError(f"{label} must be finite and valid")
    return result


def _iso(value: Any) -> str:
    stamp = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if stamp.tzinfo is None:
        raise ValueError("review timestamp must be timezone-aware")
    return stamp.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _times(window_id: str) -> tuple[str, ...]:
    try:
        start = WINDOW_STARTS[window_id]
    except KeyError as exc:
        raise ValueError("unknown historical review window") from exc
    return tuple(_iso(start + timedelta(days=7 * index)) for index in range(26))


def _same(left: float, right: float, label: str) -> None:
    if not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError(f"independent reconciliation mismatch: {label}")


def _path(row: Mapping[str, Any], start: float, end: float, label: str) -> list[float]:
    path = row.get("equity_path")
    if (
        not isinstance(path, Sequence)
        or isinstance(path, (str, bytes))
        or len(path) != 169
    ):
        raise ValueError(f"{label} path coverage mismatch")
    values = [_num(value, f"{label} equity", positive=True) for value in path]
    _same(values[0], start, f"{label} path start")
    _same(values[-1], end, f"{label} path end")
    return values


def _drawdown(values: Sequence[float]) -> float:
    peak, result = values[0], 0.0
    for value in values:
        peak = max(peak, value)
        result = max(result, 1.0 - value / peak)
    return result


def _share(values: Sequence[float], count: int) -> float | None:
    positive = sorted((value for value in values if value > 0), reverse=True)
    total = sum(positive)
    return None if total <= 0 else sum(positive[:count]) / total


def _statistics(values: Sequence[float]) -> dict[str, float]:
    if len(values) != 26:
        raise ValueError("independent weekly statistics coverage mismatch")
    mean = sum(values) / 26
    centered = tuple(value - mean for value in values)
    m2 = sum(value * value for value in centered)
    if m2 == 0:
        if mean != 0:
            raise ValueError("independent nonzero mean with zero variance")
        return {"weekly_sharpe_annualized": 0.0, "weekly_psr": 0.0}
    raw = mean / math.sqrt(m2 / 25)
    variance = m2 / 26
    population_skew = (sum(value**3 for value in centered) / 26) / variance**1.5
    skewness = math.sqrt(26 * 25) / 24 * population_skew
    population_kurtosis = (sum(value**4 for value in centered) / 26) / variance**2
    kurtosis = ((26**2 - 1) * population_kurtosis - 3 * 25**2) / (24 * 23) + 3.0
    radicand = 1.0 - skewness * raw + ((kurtosis - 1.0) / 4.0) * raw**2
    if not math.isfinite(radicand) or radicand <= 0:
        raise ValueError("independent PSR radicand invalid")
    z_score = raw * 5.0 / math.sqrt(radicand)
    return {
        "weekly_sharpe_annualized": raw * math.sqrt(52),
        "weekly_psr": 0.5 * (1.0 + math.erf(z_score / math.sqrt(2.0))),
    }


def _beta(strategy: Sequence[float], btc: Sequence[float]) -> float | None:
    mean_x, mean_y = sum(btc) / 26, sum(strategy) / 26
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


def _rebalance(value: Any, *, fee_rate: float, label: str) -> tuple[float, float]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{label} ledger is missing")
    required = {
        "executed",
        "equity_before",
        "equity_after",
        "current_values",
        "target_weights",
        "target_values",
        "trade_deltas",
        "fees",
        "traded_notional",
        "total_fee",
        "gross_notional_after",
        "gross_ratio_after",
        "residual",
        "iterations",
    }
    if set(value) != required or not isinstance(value["executed"], bool):
        raise ValueError(f"{label} ledger schema mismatch")
    before = _num(value["equity_before"], f"{label} equity before", positive=True)
    after = _num(value["equity_after"], f"{label} equity after", positive=True)

    def vector(name: str) -> dict[str, float]:
        raw = value[name]
        if not isinstance(raw, Mapping) or set(raw) != set(INSTRUMENTS):
            raise ValueError(f"{label} {name} set mismatch")
        return {
            instrument: _num(raw[instrument], f"{label} {name}")
            for instrument in INSTRUMENTS
        }

    current = vector("current_values")
    weights = vector("target_weights")
    target = vector("target_values")
    deltas = vector("trade_deltas")
    fees = vector("fees")
    if sum(abs(weight) for weight in weights.values()) > MAXIMUM_GROSS_NOTIONAL + 1e-12:
        raise ValueError(f"{label} target gross cap exceeded")

    if value["executed"]:

        def equation(equity: float) -> float:
            return (
                equity
                + fee_rate
                * sum(
                    abs(weights[instrument] * equity - current[instrument])
                    for instrument in INSTRUMENTS
                )
                - before
            )

        low, high = 0.0, before
        if equation(low) > 1e-12 or equation(high) < -1e-12:
            raise ValueError(f"{label} independent root is not bracketed")
        solved = high
        for _ in range(200):
            solved = (low + high) / 2.0
            residual = equation(solved)
            if abs(residual) <= 1e-12 or high - low <= 1e-12:
                break
            if residual > 0:
                high = solved
            else:
                low = solved
        _same(after, solved, f"{label} post-cost root")
        for instrument in INSTRUMENTS:
            _same(
                target[instrument],
                weights[instrument] * solved,
                f"{label} target {instrument}",
            )
    else:
        _same(after, before, f"{label} skipped equity")
        if int(value["iterations"]) != 0:
            raise ValueError(f"{label} skipped solver iterations mismatch")
        for instrument in INSTRUMENTS:
            _same(
                target[instrument],
                current[instrument],
                f"{label} skipped target {instrument}",
            )

    for instrument in INSTRUMENTS:
        _same(
            deltas[instrument],
            target[instrument] - current[instrument],
            f"{label} delta {instrument}",
        )
        _same(
            fees[instrument],
            fee_rate * abs(deltas[instrument]),
            f"{label} fee {instrument}",
        )
    traded = sum(abs(delta) for delta in deltas.values())
    cost = sum(fees.values())
    gross = sum(abs(item) for item in target.values())
    _same(_num(value["traded_notional"], f"{label} traded"), traded, f"{label} traded")
    _same(_num(value["total_fee"], f"{label} total fee"), cost, f"{label} total fee")
    _same(
        _num(value["gross_notional_after"], f"{label} gross"), gross, f"{label} gross"
    )
    _same(
        _num(value["gross_ratio_after"], f"{label} gross ratio"),
        gross / after,
        f"{label} gross ratio",
    )
    _same(
        _num(value["residual"], f"{label} residual"),
        before - cost - after,
        f"{label} residual",
    )
    if value["executed"] and gross > MAXIMUM_GROSS_NOTIONAL * after + 1e-9:
        raise ValueError(f"{label} post-cost gross cap exceeded")
    return traded, cost


def _source_stamp(value: Any, label: str) -> datetime:
    try:
        stamp = (
            value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(f"independent invalid source timestamp: {label}") from exc
    if stamp.tzinfo is None:
        raise ValueError(f"independent source timestamp is naive: {label}")
    result = stamp.astimezone(UTC)
    if any((result.minute, result.second, result.microsecond)):
        raise ValueError(f"independent source timestamp is off-hour: {label}")
    return result


def _source_index(
    rows: Sequence[Mapping[str, Any]], *, timestamp: str, value: str, label: str
) -> dict[datetime, float]:
    if not rows:
        raise ValueError(f"independent source is empty: {label}")
    output: dict[datetime, float] = {}
    previous: datetime | None = None
    for row in rows:
        stamp = _source_stamp(row.get(timestamp), label)
        if previous is not None and stamp <= previous:
            raise ValueError(f"independent source is unordered: {label}")
        output[stamp] = _num(row.get(value), label, positive=value != "realized_rate")
        previous = stamp
    return output


def _source_exact(
    values: Mapping[datetime, float], start: datetime, end: datetime, label: str
) -> tuple[float, ...]:
    count = int((end - start) / HOUR)
    output: list[float] = []
    for offset in range(count):
        stamp = start + offset * HOUR
        try:
            output.append(values[stamp])
        except KeyError as exc:
            raise ValueError(
                f"independent missing source hour: {label} {_iso(stamp)}"
            ) from exc
    return tuple(output)


def _source_cash_signal(
    decision: datetime,
    reason: str,
    funding_sums: Mapping[str, float],
    *,
    high: str | None = None,
    low: str | None = None,
    beta: float | None = None,
    r_squared: float | None = None,
    projected: float = 0.0,
    positive_days: int = 0,
) -> dict[str, Any]:
    return {
        "decision_time": _iso(decision),
        "eligible": False,
        "reason": reason,
        "high_funding_instrument": high,
        "low_funding_instrument": low,
        "funding_sums_28d": dict(funding_sums),
        "beta": beta,
        "r_squared": r_squared,
        "long_weight": 0.0,
        "short_weight": 0.0,
        "projected_carry_28d": projected,
        "positive_daily_spreads": positive_days,
        "target_weights": {instrument: 0.0 for instrument in INSTRUMENTS},
    }


def _source_signal(
    decision: datetime,
    marks: Mapping[str, Mapping[datetime, float]],
    funding: Mapping[str, Mapping[datetime, float]],
) -> dict[str, Any]:
    returns: dict[str, tuple[float, ...]] = {}
    daily: dict[str, tuple[float, ...]] = {}
    sums: dict[str, float] = {}
    for instrument in INSTRUMENTS:
        closes = _source_exact(
            marks[instrument],
            decision - MARK_CLOSE_COUNT * HOUR,
            decision,
            f"mark {instrument}",
        )
        if len(closes) != MARK_CLOSE_COUNT:
            raise ValueError("independent mark lookback coverage mismatch")
        returns[instrument] = tuple(
            math.log(closes[index] / closes[index - 1])
            for index in range(1, len(closes))
        )
        start = decision - timedelta(days=28)
        day_values: list[float] = []
        for day in range(28):
            left = start + timedelta(days=day)
            right = left + timedelta(days=1)
            rates = [
                rate
                for stamp, rate in funding[instrument].items()
                if left <= stamp < right
            ]
            if not rates:
                raise ValueError(
                    f"independent missing funding day: {instrument} {_iso(left)}"
                )
            day_values.append(sum(rates))
        daily[instrument] = tuple(day_values)
        sums[instrument] = sum(day_values)
    if sums[INSTRUMENTS[0]] == sums[INSTRUMENTS[1]]:
        return _source_cash_signal(decision, "FUNDING_TIE", sums)
    high = max(INSTRUMENTS, key=lambda instrument: sums[instrument])
    low = INSTRUMENTS[0] if high == INSTRUMENTS[1] else INSTRUMENTS[1]
    x, y = returns[high], returns[low]
    mean_x, mean_y = sum(x) / len(x), sum(y) / len(y)
    sxx = sum((value - mean_x) ** 2 for value in x)
    syy = sum((value - mean_y) ** 2 for value in y)
    if sxx <= 0 or syy <= 0:
        raise ValueError("independent OLS variance is not positive")
    sxy = sum(
        (x_value - mean_x) * (y_value - mean_y)
        for x_value, y_value in zip(x, y, strict=True)
    )
    beta = sxy / sxx
    alpha = mean_y - beta * mean_x
    residual = sum(
        (y_value - (alpha + beta * x_value)) ** 2
        for x_value, y_value in zip(x, y, strict=True)
    )
    r_squared = min(1.0, max(0.0, 1.0 - residual / syy))
    if not MINIMUM_BETA <= beta <= MAXIMUM_BETA:
        return _source_cash_signal(
            decision,
            "BETA_OUT_OF_RANGE",
            sums,
            high=high,
            low=low,
            beta=beta,
            r_squared=r_squared,
        )
    if r_squared < MINIMUM_R_SQUARED:
        return _source_cash_signal(
            decision,
            "R_SQUARED_BELOW_MINIMUM",
            sums,
            high=high,
            low=low,
            beta=beta,
            r_squared=r_squared,
        )
    long_weight = MAXIMUM_GROSS_NOTIONAL / (1.0 + beta)
    short_weight = MAXIMUM_GROSS_NOTIONAL - long_weight
    projected = short_weight * sums[high] - long_weight * sums[low]
    positive_days = sum(
        short_weight * high_rate - long_weight * low_rate > 0
        for high_rate, low_rate in zip(daily[high], daily[low], strict=True)
    )
    if sums[high] <= 0:
        reason = "HIGH_FUNDING_NOT_POSITIVE"
    elif projected <= MINIMUM_PROJECTED_CARRY:
        reason = "PROJECTED_CARRY_BELOW_MINIMUM"
    elif positive_days < MINIMUM_POSITIVE_DAYS:
        reason = "POSITIVE_DAILY_SPREAD_COUNT_BELOW_MINIMUM"
    else:
        return {
            "decision_time": _iso(decision),
            "eligible": True,
            "reason": "ELIGIBLE",
            "high_funding_instrument": high,
            "low_funding_instrument": low,
            "funding_sums_28d": sums,
            "beta": beta,
            "r_squared": r_squared,
            "long_weight": long_weight,
            "short_weight": short_weight,
            "projected_carry_28d": projected,
            "positive_daily_spreads": positive_days,
            "target_weights": {low: long_weight, high: -short_weight},
        }
    return _source_cash_signal(
        decision,
        reason,
        sums,
        high=high,
        low=low,
        beta=beta,
        r_squared=r_squared,
        projected=projected,
        positive_days=positive_days,
    )


def _source_target(signal: Mapping[str, Any], policy: str) -> dict[str, float]:
    if policy == "cash":
        return {instrument: 0.0 for instrument in INSTRUMENTS}
    if policy == "candidate":
        return dict(signal["target_weights"])
    if policy == "equal_notional_funding_rank":
        if not signal["eligible"]:
            return {instrument: 0.0 for instrument in INSTRUMENTS}
        return {
            str(signal["low_funding_instrument"]): 0.25,
            str(signal["high_funding_instrument"]): -0.25,
        }
    if policy != "always_on_funding_rank":
        raise ValueError("independent replay policy drift")
    if signal["reason"] in {
        "FUNDING_TIE",
        "BETA_OUT_OF_RANGE",
        "R_SQUARED_BELOW_MINIMUM",
    }:
        return {instrument: 0.0 for instrument in INSTRUMENTS}
    beta = _num(signal["beta"], "independent signal beta")
    long_weight = MAXIMUM_GROSS_NOTIONAL / (1.0 + beta)
    return {
        str(signal["low_funding_instrument"]): long_weight,
        str(signal["high_funding_instrument"]): -(MAXIMUM_GROSS_NOTIONAL - long_weight),
    }


def _source_orientation(values: Mapping[str, float]) -> str:
    btc, eth = (values[instrument] for instrument in INSTRUMENTS)
    if btc > 0 and eth < 0:
        return "LONG_BTC_SHORT_ETH"
    if eth > 0 and btc < 0:
        return "LONG_ETH_SHORT_BTC"
    if btc == 0 and eth == 0:
        return "CASH"
    raise ValueError("independent replay orientation is invalid")


def _source_resize(current: Mapping[str, float], target: Mapping[str, float]) -> bool:
    gross = sum(abs(current[instrument]) for instrument in INSTRUMENTS)
    distance = sum(
        abs(target[instrument] - current[instrument]) for instrument in INSTRUMENTS
    )
    return distance > 0 if gross == 0 else distance >= gross * 0.10


def _source_solve(
    equity: float,
    current: Mapping[str, float],
    target: Mapping[str, float],
    fee_rate: float,
) -> dict[str, Any]:
    def equation(value: float) -> float:
        return (
            value
            + fee_rate
            * sum(
                abs(target[instrument] * value - current[instrument])
                for instrument in INSTRUMENTS
            )
            - equity
        )

    low, high = 0.0, equity
    if equation(low) > 1e-12 or equation(high) < -1e-12:
        raise ValueError("independent replay rebalance root is not bracketed")
    solved = high
    iterations = 0
    for iterations in range(1, 201):
        solved = (low + high) / 2.0
        residual = equation(solved)
        if abs(residual) <= 1e-12 or high - low <= 1e-12:
            break
        if residual > 0:
            high = solved
        else:
            low = solved
    else:
        raise ValueError("independent replay rebalance root did not converge")
    target_values = {
        instrument: target[instrument] * solved for instrument in INSTRUMENTS
    }
    deltas = {
        instrument: target_values[instrument] - current[instrument]
        for instrument in INSTRUMENTS
    }
    fees = {
        instrument: fee_rate * abs(deltas[instrument]) for instrument in INSTRUMENTS
    }
    traded = sum(abs(value) for value in deltas.values())
    total_fee = sum(fees.values())
    gross = sum(abs(value) for value in target_values.values())
    return {
        "executed": True,
        "equity_before": equity,
        "equity_after": solved,
        "current_values": dict(current),
        "target_weights": dict(target),
        "target_values": target_values,
        "trade_deltas": deltas,
        "fees": fees,
        "traded_notional": traded,
        "total_fee": total_fee,
        "gross_notional_after": gross,
        "gross_ratio_after": gross / solved,
        "residual": equity - total_fee - solved,
        "iterations": iterations,
    }


def _source_skip(
    equity: float, current: Mapping[str, float], target: Mapping[str, float]
) -> dict[str, Any]:
    gross = sum(abs(value) for value in current.values())
    return {
        "executed": False,
        "equity_before": equity,
        "equity_after": equity,
        "current_values": dict(current),
        "target_weights": dict(target),
        "target_values": dict(current),
        "trade_deltas": {instrument: 0.0 for instrument in INSTRUMENTS},
        "fees": {instrument: 0.0 for instrument in INSTRUMENTS},
        "traded_notional": 0.0,
        "total_fee": 0.0,
        "gross_notional_after": gross,
        "gross_ratio_after": gross / equity,
        "residual": 0.0,
        "iterations": 0,
    }


def _source_replay(
    *,
    window_id: str,
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    policy: str,
    cost_label: str,
) -> dict[str, Any]:
    if (
        set(mark_rows) != set(INSTRUMENTS)
        or set(trade_rows) != set(INSTRUMENTS)
        or set(funding_rows) != set(INSTRUMENTS)
    ):
        raise ValueError("independent primitive source instrument set mismatch")
    decisions = tuple(datetime.fromisoformat(value) for value in _times(window_id))
    window_end = decisions[0] + timedelta(weeks=26)
    marks = {
        instrument: _source_index(
            mark_rows[instrument],
            timestamp="timestamp",
            value="close",
            label=f"mark {instrument}",
        )
        for instrument in INSTRUMENTS
    }
    trades = {
        instrument: _source_index(
            trade_rows[instrument],
            timestamp="timestamp",
            value="open",
            label=f"trade {instrument}",
        )
        for instrument in INSTRUMENTS
    }
    funding = {
        instrument: _source_index(
            funding_rows[instrument],
            timestamp="funding_time",
            value="realized_rate",
            label=f"funding {instrument}",
        )
        for instrument in INSTRUMENTS
    }
    for instrument in INSTRUMENTS:
        _source_exact(
            marks[instrument],
            decisions[0] - MARK_CLOSE_COUNT * HOUR,
            window_end,
            f"mark {instrument}",
        )
        _source_exact(
            trades[instrument],
            decisions[0],
            window_end + HOUR,
            f"trade {instrument}",
        )
    fee_rate = COST_RATES[cost_label]
    equity = 1.0
    units = {instrument: 0.0 for instrument in INSTRUMENTS}
    processed = {instrument: set() for instrument in INSTRUMENTS}
    signals: list[dict[str, Any]] = []
    weekly_rows: list[dict[str, Any]] = []
    for week_index, decision in enumerate(decisions):
        starting = equity
        path = [equity]
        funding_pnl = receipts = payments = relative = costs = traded = 0.0
        signal = _source_signal(decision, marks, funding)
        signals.append(signal)
        target = _source_target(signal, policy)
        active = any(target.values())
        orientation = _source_orientation(target)
        decision_ledger: dict[str, Any] | None = None
        liquidation_ledger: dict[str, Any] | None = None
        for hour_index in range(WEEK_HOURS):
            current_time = decision + hour_index * HOUR
            next_time = current_time + HOUR
            previous_marks = {
                instrument: marks[instrument][current_time - HOUR]
                for instrument in INSTRUMENTS
            }
            for instrument in INSTRUMENTS:
                rate = funding[instrument].get(current_time)
                if rate is None:
                    continue
                pnl = -units[instrument] * previous_marks[instrument] * rate
                equity += pnl
                funding_pnl += pnl
                if pnl >= 0:
                    receipts += pnl
                else:
                    payments -= pnl
                processed[instrument].add(current_time)
            hour_start_prices = previous_marks
            if hour_index == 0:
                opens = {
                    instrument: trades[instrument][current_time]
                    for instrument in INSTRUMENTS
                }
                execution_basis_pnl = sum(
                    units[instrument] * (opens[instrument] - previous_marks[instrument])
                    for instrument in INSTRUMENTS
                )
                equity += execution_basis_pnl
                relative += execution_basis_pnl
                current_values = {
                    instrument: units[instrument] * opens[instrument]
                    for instrument in INSTRUMENTS
                }
                current_weights = {
                    instrument: current_values[instrument] / equity
                    for instrument in INSTRUMENTS
                }
                execute = _source_orientation(
                    current_weights
                ) != orientation or _source_resize(current_weights, target)
                if execute:
                    decision_ledger = _source_solve(
                        equity, current_values, target, fee_rate
                    )
                    equity = decision_ledger["equity_after"]
                    traded += decision_ledger["traded_notional"]
                    costs += decision_ledger["total_fee"]
                    units = {
                        instrument: decision_ledger["target_values"][instrument]
                        / opens[instrument]
                        for instrument in INSTRUMENTS
                    }
                else:
                    decision_ledger = _source_skip(equity, current_values, target)
                hour_start_prices = opens
            current_marks = {
                instrument: marks[instrument][current_time]
                for instrument in INSTRUMENTS
            }
            price_pnl = sum(
                units[instrument]
                * (current_marks[instrument] - hour_start_prices[instrument])
                for instrument in INSTRUMENTS
            )
            equity += price_pnl
            relative += price_pnl
            if week_index == 25 and hour_index == WEEK_HOURS - 1:
                liquidation_opens = {
                    instrument: trades[instrument][next_time]
                    for instrument in INSTRUMENTS
                }
                execution_basis_pnl = sum(
                    units[instrument]
                    * (liquidation_opens[instrument] - current_marks[instrument])
                    for instrument in INSTRUMENTS
                )
                equity += execution_basis_pnl
                relative += execution_basis_pnl
                current_values = {
                    instrument: units[instrument] * liquidation_opens[instrument]
                    for instrument in INSTRUMENTS
                }
                zero = {instrument: 0.0 for instrument in INSTRUMENTS}
                if any(current_values.values()):
                    liquidation_ledger = _source_solve(
                        equity, current_values, zero, fee_rate
                    )
                    equity = liquidation_ledger["equity_after"]
                    traded += liquidation_ledger["traded_notional"]
                    costs += liquidation_ledger["total_fee"]
                else:
                    liquidation_ledger = _source_skip(equity, current_values, zero)
                units = {instrument: 0.0 for instrument in INSTRUMENTS}
            if not math.isfinite(equity) or equity <= 0:
                raise ValueError("independent primitive replay equity is invalid")
            path.append(equity)
        weekly_rows.append(
            {
                "decision_time": _iso(decision),
                "cost_label": cost_label,
                "starting_equity": starting,
                "ending_equity": equity,
                "funding_pnl": funding_pnl,
                "gross_funding_receipts": receipts,
                "gross_funding_payments": payments,
                "relative_price_pnl": relative,
                "negative_relative_price_pnl": min(relative, 0.0),
                "traded_notional": traded,
                "trading_cost": costs,
                "turnover": traded / starting,
                "btc_mark_return": marks[INSTRUMENTS[0]][
                    decision + (WEEK_HOURS - 1) * HOUR
                ]
                / marks[INSTRUMENTS[0]][decision - HOUR]
                - 1.0,
                "active": active,
                "orientation": orientation,
                "missing_decision": False,
                "unaccounted_funding_settlements": 0,
                "equity_path": path,
                "decision_rebalance": decision_ledger,
                "terminal_liquidation": liquidation_ledger,
            }
        )
    for instrument in INSTRUMENTS:
        expected = {
            stamp for stamp in funding[instrument] if decisions[0] <= stamp < window_end
        }
        if processed[instrument] != expected:
            raise ValueError(f"independent unaccounted funding: {instrument}")
    return {"signals": signals, "weekly_rows": weekly_rows}


def _candidate(
    rows: Sequence[Mapping[str, Any]], *, label: str, window_id: str
) -> dict[str, Any]:
    if label not in COST_LABELS or len(rows) != 26:
        raise ValueError("independent candidate identity mismatch")
    curve: list[float] = []
    starts: list[float] = []
    ends: list[float] = []
    returns: list[float] = []
    pnl: list[float] = []
    btc: list[float] = []
    active: list[bool] = []
    orientations: list[str] = []
    funding_total = receipts_total = costs_total = turnover_total = 0.0
    carry: float | None = None
    previous: float | None = None
    expected_times = _times(window_id)

    for index, (row, expected) in enumerate(zip(rows, expected_times, strict=True)):
        if _iso(row.get("decision_time")) != expected or row.get("cost_label") != label:
            raise ValueError("independent candidate row identity mismatch")
        start = _num(row.get("starting_equity"), "starting equity", positive=True)
        end = _num(row.get("ending_equity"), "ending equity", positive=True)
        funding = _num(row.get("funding_pnl"), "funding PnL")
        receipts = _num(row.get("gross_funding_receipts"), "funding receipts")
        payments = _num(row.get("gross_funding_payments"), "funding payments")
        relative = _num(row.get("relative_price_pnl"), "relative PnL")
        negative = _num(row.get("negative_relative_price_pnl"), "negative relative PnL")
        traded = _num(row.get("traded_notional"), "traded notional")
        cost = _num(row.get("trading_cost"), "trading cost")
        turnover = _num(row.get("turnover"), "turnover")
        btc_return = _num(row.get("btc_mark_return"), "BTC return")
        if min(receipts, payments, traded, cost, turnover) < 0:
            raise ValueError("independent candidate magnitude is negative")
        if previous is not None:
            _same(start, previous, f"candidate equity chain {index}")
        _same(funding, receipts - payments, f"candidate funding {index}")
        _same(turnover, traded / start, f"candidate turnover {index}")
        _same(cost, traded * COST_RATES[label], f"candidate cost {index}")
        _same(end, start + funding + relative - cost, f"candidate accounting {index}")
        decision_traded, decision_cost = _rebalance(
            row.get("decision_rebalance"),
            fee_rate=COST_RATES[label],
            label=f"candidate decision {index}",
        )
        liquidation = row.get("terminal_liquidation")
        if index == 25:
            liquidation_traded, liquidation_cost = _rebalance(
                liquidation,
                fee_rate=COST_RATES[label],
                label="candidate terminal liquidation",
            )
        elif liquidation is not None:
            raise ValueError("candidate premature terminal liquidation")
        else:
            liquidation_traded = liquidation_cost = 0.0
        _same(
            traded,
            decision_traded + liquidation_traded,
            f"candidate ledger traded {index}",
        )
        _same(cost, decision_cost + liquidation_cost, f"candidate ledger cost {index}")
        if negative > 0 or negative > min(relative, 0.0) + 1e-9:
            raise ValueError("independent negative relative decomposition mismatch")
        is_active, orientation = row.get("active"), row.get("orientation")
        if (
            not isinstance(is_active, bool)
            or (
                is_active
                and orientation not in {"LONG_BTC_SHORT_ETH", "LONG_ETH_SHORT_BTC"}
            )
            or (not is_active and orientation != "CASH")
        ):
            raise ValueError("independent active/orientation mismatch")
        if (
            row.get("missing_decision") is not False
            or row.get("unaccounted_funding_settlements") != 0
        ):
            raise ValueError("independent completeness mismatch")
        week_path = _path(row, start, end, f"candidate week {index}")
        if curve:
            _same(curve[-1], week_path[0], f"candidate path chain {index}")
            curve.extend(week_path[1:])
        else:
            curve.extend(week_path)
            carry = start
        starts.append(start)
        ends.append(end)
        returns.append(end / start - 1.0)
        pnl.append(end - start)
        btc.append(btc_return)
        active.append(is_active)
        orientations.append(str(orientation))
        funding_total += funding
        receipts_total += receipts
        costs_total += cost
        turnover_total += turnover
        assert carry is not None
        carry *= 1.0 + (funding + negative - cost) / start
        if carry <= 0 or not math.isfinite(carry):
            raise ValueError("independent carry-only equity invalid")
        previous = end

    active_count = sum(active)
    active_orientations = [value for value in orientations if value != "CASH"]
    orientation_share = (
        max(active_orientations.count(value) for value in set(active_orientations))
        / active_count
        if active_count
        else None
    )
    assert carry is not None
    result = {
        "schema_version": 1,
        "stage": "C7A_HISTORICAL_WINDOW_AGGREGATE",
        "status": "PASS",
        "window_id": window_id,
        "cost_label": label,
        "decision_times": list(expected_times),
        "first_half_net_return": ends[12] / starts[0] - 1.0,
        "second_half_net_return": ends[-1] / starts[13] - 1.0,
        "aggregate_net_return": ends[-1] / starts[0] - 1.0,
        "maximum_drawdown": _drawdown(curve),
        "strategy_beta_to_btc": _beta(returns, btc),
        "aggregate_funding_pnl": funding_total,
        "gross_funding_receipts_to_costs": (
            receipts_total / costs_total if costs_total > 0 else None
        ),
        "carry_only_stress_return": carry / starts[0] - 1.0,
        "active_weeks": active_count,
        "first_half_active_weeks": sum(active[:13]),
        "second_half_active_weeks": sum(active[13:]),
        "maximum_orientation_share": orientation_share,
        "annualized_one_way_turnover": turnover_total * 2.0,
        "maximum_positive_week_pnl_share": _share(pnl, 1),
        "maximum_top_three_positive_week_pnl_share": _share(pnl, 3),
        "missing_decision_count": 0,
        "unaccounted_funding_settlement_count": 0,
        "non_positive_equity_count": 0,
        "live_state": "LIVE_FORBIDDEN",
    }
    result.update(_statistics(returns))
    return result


def _comparator(
    rows: Sequence[Mapping[str, Any]], *, name: str, window_id: str
) -> dict[str, Any]:
    if name not in COMPARATORS or len(rows) != 26:
        raise ValueError("independent comparator identity mismatch")
    curve: list[float] = []
    returns: list[float] = []
    previous: float | None = None
    expected_times = _times(window_id)
    for index, (row, expected) in enumerate(zip(rows, expected_times, strict=True)):
        if (
            _iso(row.get("decision_time")) != expected
            or row.get("cost_label") != "1.0x"
        ):
            raise ValueError("independent comparator decision-grid mismatch")
        start = _num(row.get("starting_equity"), "comparator start", positive=True)
        end = _num(row.get("ending_equity"), "comparator end", positive=True)
        if previous is not None:
            _same(start, previous, f"comparator chain {index}")
        decision_traded, decision_cost = _rebalance(
            row.get("decision_rebalance"),
            fee_rate=COST_RATES["1.0x"],
            label=f"comparator decision {index}",
        )
        liquidation = row.get("terminal_liquidation")
        if index == 25:
            liquidation_traded, liquidation_cost = _rebalance(
                liquidation,
                fee_rate=COST_RATES["1.0x"],
                label="comparator terminal liquidation",
            )
        elif liquidation is not None:
            raise ValueError("comparator premature terminal liquidation")
        else:
            liquidation_traded = liquidation_cost = 0.0
        _same(
            _num(row.get("traded_notional"), "comparator traded"),
            decision_traded + liquidation_traded,
            f"comparator ledger traded {index}",
        )
        _same(
            _num(row.get("trading_cost"), "comparator cost"),
            decision_cost + liquidation_cost,
            f"comparator ledger cost {index}",
        )
        week_path = _path(row, start, end, f"comparator week {index}")
        if curve:
            _same(curve[-1], week_path[0], f"comparator path chain {index}")
            curve.extend(week_path[1:])
        else:
            curve.extend(week_path)
        returns.append(end / start - 1.0)
        previous = end
    result = {
        "schema_version": 1,
        "stage": "C7A_HISTORICAL_COMPARATOR_AGGREGATE",
        "status": "PASS",
        "window_id": window_id,
        "comparator_id": name,
        "decision_times": list(expected_times),
        "aggregate_net_return": curve[-1] / curve[0] - 1.0,
        "maximum_drawdown": _drawdown(curve),
        "live_state": "LIVE_FORBIDDEN",
    }
    result.update(_statistics(returns))
    return result


def _decision(
    candidates: Mapping[str, Mapping[str, Any]],
    always: Mapping[str, Any],
    window_id: str,
) -> dict[str, Any]:
    expected, one_five, two = (candidates[label] for label in COST_LABELS)
    checks = {
        "first_half_return": expected["first_half_net_return"] > 0,
        "second_half_return": expected["second_half_net_return"] > 0,
        "aggregate_expected_return": expected["aggregate_net_return"] > 0,
        "aggregate_1_5x_return": one_five["aggregate_net_return"] > 0,
        "aggregate_2_0x_return": two["aggregate_net_return"] >= 0,
        "weekly_sharpe": expected["weekly_sharpe_annualized"] >= 1,
        "weekly_psr": expected["weekly_psr"] >= 0.95,
        "maximum_drawdown": expected["maximum_drawdown"] <= 0.10,
        "strategy_beta_to_btc": expected["strategy_beta_to_btc"] is not None
        and abs(expected["strategy_beta_to_btc"]) <= 0.15,
        "aggregate_funding_pnl": expected["aggregate_funding_pnl"] > 0,
        "funding_receipts_to_costs": expected["gross_funding_receipts_to_costs"]
        is not None
        and expected["gross_funding_receipts_to_costs"] >= 2,
        "carry_only_stress": expected["carry_only_stress_return"] > 0,
        "always_on_return_increment": expected["aggregate_net_return"]
        > always["aggregate_net_return"],
        "always_on_sharpe_increment": expected["weekly_sharpe_annualized"]
        >= always["weekly_sharpe_annualized"] + 0.10,
        "active_weeks": expected["active_weeks"] >= 13,
        "first_half_active_weeks": expected["first_half_active_weeks"] >= 5,
        "second_half_active_weeks": expected["second_half_active_weeks"] >= 5,
        "orientation_concentration": expected["maximum_orientation_share"] is not None
        and expected["maximum_orientation_share"] <= 0.85,
        "annualized_turnover": expected["annualized_one_way_turnover"] <= 8,
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
        "window_id": window_id,
        "decision": "SELECTED" if not failed else "REJECTED",
        "failed_gates": failed,
        "selected_policy": ("C7ABetaNeutralFundingDispersion" if not failed else None),
        "live_state": "LIVE_FORBIDDEN",
    }


def _compare(expected: Any, observed: Any, path: str, errors: list[str]) -> None:
    if isinstance(expected, Mapping):
        if not isinstance(observed, Mapping) or set(expected) != set(observed):
            errors.append(f"{path} key set mismatch")
            return
        for key in expected:
            _compare(expected[key], observed[key], f"{path}.{key}", errors)
    elif isinstance(expected, Sequence) and not isinstance(expected, (str, bytes)):
        if (
            not isinstance(observed, Sequence)
            or isinstance(observed, (str, bytes))
            or len(expected) != len(observed)
        ):
            errors.append(f"{path} sequence mismatch")
            return
        for index, (left, right) in enumerate(zip(expected, observed, strict=True)):
            _compare(left, right, f"{path}[{index}]", errors)
    elif isinstance(expected, float):
        try:
            matches = math.isclose(
                expected, float(observed), rel_tol=1e-12, abs_tol=1e-9
            )
        except (TypeError, ValueError):
            matches = False
        if not matches:
            errors.append(f"{path} value mismatch")
    elif expected != observed:
        errors.append(f"{path} value mismatch")


def review_historical_window(
    evidence: Mapping[str, Any],
    *,
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Recompute primitive replays, aggregates, and the decision independently."""
    errors: list[str] = []
    candidates: dict[str, Any] = {}
    comparators: dict[str, Any] = {}
    decision: dict[str, Any] | None = None
    source_recompute_performed = False
    try:
        window_id = str(evidence.get("window_id"))
        if window_id not in WINDOW_STARTS:
            raise ValueError("historical evidence window identity mismatch")
        candidate_replays = evidence.get("candidate_replays")
        comparator_replays = evidence.get("comparator_replays")
        if not isinstance(candidate_replays, Mapping) or set(candidate_replays) != set(
            COST_LABELS
        ):
            raise ValueError("historical candidate replay set mismatch")
        if not isinstance(comparator_replays, Mapping) or set(
            comparator_replays
        ) != set(COMPARATORS):
            raise ValueError("historical comparator replay set mismatch")
        source_inputs = (mark_rows, trade_rows, funding_rows)
        if any(value is not None for value in source_inputs) and not all(
            value is not None for value in source_inputs
        ):
            raise ValueError("independent primitive source set is incomplete")
        if all(value is not None for value in source_inputs):
            assert mark_rows is not None
            assert trade_rows is not None
            assert funding_rows is not None
            source_recompute_performed = True
            for label in COST_LABELS:
                replay = _source_replay(
                    window_id=window_id,
                    mark_rows=mark_rows,
                    trade_rows=trade_rows,
                    funding_rows=funding_rows,
                    policy="candidate",
                    cost_label=label,
                )
                _compare(
                    replay["signals"],
                    candidate_replays[label].get("signals"),
                    f"source.candidate.{label}.signals",
                    errors,
                )
                _compare(
                    replay["weekly_rows"],
                    candidate_replays[label].get("weekly_rows"),
                    f"source.candidate.{label}.weekly_rows",
                    errors,
                )
            for name in COMPARATORS:
                replay = _source_replay(
                    window_id=window_id,
                    mark_rows=mark_rows,
                    trade_rows=trade_rows,
                    funding_rows=funding_rows,
                    policy=name,
                    cost_label="1.0x",
                )
                _compare(
                    replay["signals"],
                    comparator_replays[name].get("signals"),
                    f"source.comparator.{name}.signals",
                    errors,
                )
                _compare(
                    replay["weekly_rows"],
                    comparator_replays[name].get("weekly_rows"),
                    f"source.comparator.{name}.weekly_rows",
                    errors,
                )
        candidates = {
            label: _candidate(
                candidate_replays[label]["weekly_rows"],
                label=label,
                window_id=window_id,
            )
            for label in COST_LABELS
        }
        comparators = {
            name: _comparator(
                comparator_replays[name]["weekly_rows"],
                name=name,
                window_id=window_id,
            )
            for name in COMPARATORS
        }
        decision = _decision(
            candidates, comparators["always_on_funding_rank"], window_id
        )
        _compare(candidates, evidence.get("candidate_aggregates"), "candidate", errors)
        _compare(
            comparators, evidence.get("comparator_aggregates"), "comparator", errors
        )
        _compare(decision, evidence.get("decision"), "decision", errors)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(str(exc))
    return {
        "schema_version": 1,
        "stage": "C7A_HISTORICAL_INDEPENDENT_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "errors": errors,
        "primitive_source_recompute_performed": source_recompute_performed,
        "primitive_source_recompute_passed": (
            not errors if source_recompute_performed else None
        ),
        "candidate_aggregates_recomputed": candidates,
        "comparator_aggregates_recomputed": comparators,
        "decision_recomputed": decision,
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "paper_side_effect": False,
        "shadow_side_effect": False,
        "live_state": "LIVE_FORBIDDEN",
    }
