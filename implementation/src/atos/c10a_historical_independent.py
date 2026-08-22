"""Physically separate C10A signal, ledger, metric, and gate recomputation."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from statistics import mean, stdev
from typing import Any

from atos.c10a_contract import (
    BETA_LOOKBACK_RETURNS,
    BTC_BETA_BENCHMARK,
    CANDIDATE_ID,
    CANDIDATE_POOL,
    COST_RATES,
    EXPECTED_DECISIONS_PER_WINDOW,
    EXPECTED_NONFLAT_DIRECTIONS,
    EXPECTED_TOTAL_DECISIONS,
    FORMATION_END_EXCLUSIVE,
    FORMATION_START,
    GROSS_NOTIONAL,
    HISTORICAL_WINDOWS,
    HOUR,
    MINIMUM_EQUITY_TO_GROSS_NOTIONAL,
    PER_POSITION_ABS_NOTIONAL,
    RECONCILIATION_TOLERANCE,
    RESIDUAL_SCORE_RETURNS,
    STARTING_EQUITY,
    decision_times,
    iso,
    safety_boundary,
    window_by_id,
)

POLICIES = (
    CANDIDATE_ID,
    "RawReturnMomentumComparator",
    "AlwaysLongSelectedUniverseComparator",
    "CashComparator",
)
TRIAL_COUNT = 627
ZERO = Decimal(0)
ONE = Decimal(1)


class C10AHistoricalIndependentError(RuntimeError):
    """Raised when the separate recomputation cannot prove a retained result."""


def review_formation_universe(
    retained: Mapping[str, Any],
    formation_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Recompute the fixed top-eight formation rank without capture imports."""

    if set(formation_rows) != set(CANDIDATE_POOL):
        raise C10AHistoricalIndependentError("independent formation inventory drift")
    scores = []
    reference_clock = None
    for instrument in CANDIDATE_POOL:
        rows = formation_rows[instrument]
        clock = tuple(_time(row.get("timestamp")) for row in rows)
        if (
            not clock
            or len(clock) != len(set(clock))
            or tuple(sorted(clock)) != clock
            or (reference_clock is not None and clock != reference_clock)
            or clock[0] != FORMATION_START
            or clock[-1] != FORMATION_END_EXCLUSIVE - HOUR
            or any(right - left != HOUR for left, right in pairwise(clock))
        ):
            raise C10AHistoricalIndependentError(
                "independent formation clock is invalid"
            )
        reference_clock = clock
        values = sorted(
            _number(row.get("volume_quote"), "formation quote volume") for row in rows
        )
        if any(value < 0 for value in values):
            raise C10AHistoricalIndependentError(
                "independent formation quote volume is negative"
            )
        midpoint = len(values) // 2
        median = (
            values[midpoint]
            if len(values) % 2
            else (values[midpoint - 1] + values[midpoint]) / Decimal(2)
        )
        scores.append((instrument, median))
    scores.sort(key=lambda item: (-item[1], item[0]))
    selected = [instrument for instrument, _ in scores[:8]]
    retained_scores = retained.get("scores", [])
    rank_match = len(retained_scores) == len(scores) and all(
        row.get("rank") == rank
        and row.get("instrument") == instrument
        and _close(row.get("median_quote_volume"), value)
        and row.get("selected") == (rank <= 8)
        for rank, ((instrument, value), row) in enumerate(
            zip(scores, retained_scores, strict=True), start=1
        )
    )
    passed = (
        retained.get("stage") == "C10A_FORMATION_UNIVERSE"
        and retained.get("liquidity_field") == "volCcyQuote"
        and retained.get("selected_universe") == selected
        and rank_match
        and all(retained.get(key) == value for key, value in safety_boundary().items())
    )
    return {
        "schema_version": 1,
        "stage": "C10A_FORMATION_INDEPENDENT_RECOMPUTE",
        "status": "PASS" if passed else "FAIL",
        "selected_universe_recomputed": selected,
        "rank_recompute_match": rank_match,
        "imports_production_capture_or_selector": False,
        **safety_boundary(),
    }


def _time(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise C10AHistoricalIndependentError(f"invalid timestamp: {value!r}") from exc
    if result.tzinfo is None:
        raise C10AHistoricalIndependentError("timestamp must be timezone-aware")
    return result.astimezone(UTC)


def _number(value: Any, label: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise C10AHistoricalIndependentError(f"{label} must be decimal")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise C10AHistoricalIndependentError(f"{label} must be decimal") from exc
    if not result.is_finite() or (positive and result <= 0):
        raise C10AHistoricalIndependentError(f"{label} is non-finite or non-positive")
    return result


def _series(
    rows: Sequence[Mapping[str, Any]], field: str, label: str
) -> dict[datetime, Decimal]:
    output: dict[datetime, Decimal] = {}
    last = None
    for row in rows:
        stamp = _time(row.get("timestamp"))
        if stamp.minute or stamp.second or stamp.microsecond:
            raise C10AHistoricalIndependentError(f"{label} is off-grid")
        if last is not None and stamp <= last:
            raise C10AHistoricalIndependentError(f"{label} is duplicate or unordered")
        last = stamp
        output[stamp] = _number(row.get(field), f"{label} {field}", positive=True)
    if not output:
        raise C10AHistoricalIndependentError(f"{label} is empty")
    return output


def _funding(
    rows: Sequence[Mapping[str, Any]], label: str
) -> tuple[tuple[datetime, Decimal], ...]:
    output = []
    last = None
    for row in rows:
        stamp = _time(row.get("funding_time"))
        if stamp.minute or stamp.second or stamp.microsecond:
            raise C10AHistoricalIndependentError(f"{label} funding is off-grid")
        if last is not None and stamp <= last:
            raise C10AHistoricalIndependentError(
                f"{label} funding is duplicate or unordered"
            )
        last = stamp
        output.append((stamp, _number(row.get("realized_rate"), "funding rate")))
    if not output:
        raise C10AHistoricalIndependentError(f"{label} funding is empty")
    return tuple(output)


def _require_complete_clock(
    values: Mapping[datetime, Decimal],
    *,
    start: datetime,
    end_inclusive: datetime,
    label: str,
) -> None:
    current = start
    while current <= end_inclusive:
        if current not in values:
            raise C10AHistoricalIndependentError(
                f"{label} complete clock drift: {iso(current)}"
            )
        current += HOUR


def _require_funding_coverage(
    values: Sequence[tuple[datetime, Decimal]],
    *,
    start: datetime,
    end_exclusive: datetime,
    label: str,
) -> None:
    maximum_gap = 8 * HOUR + timedelta(minutes=1)
    stamps = [stamp for stamp, _ in values if start <= stamp < end_exclusive]
    if not stamps:
        raise C10AHistoricalIndependentError(f"{label} funding coverage is empty")
    gaps = (
        stamps[0] - start,
        *(right - left for left, right in pairwise(stamps)),
        end_exclusive - stamps[-1],
    )
    if any(gap < timedelta(0) or gap > maximum_gap for gap in gaps):
        raise C10AHistoricalIndependentError(f"{label} funding coverage drift")


def _close(left: Any, right: Any, tolerance: Decimal = RECONCILIATION_TOLERANCE) -> bool:
    try:
        left_value = Decimal(str(left))
        right_value = Decimal(str(right))
    except (InvalidOperation, ValueError, TypeError):
        return False
    scale = max(ONE, abs(left_value), abs(right_value))
    return abs(left_value - right_value) <= tolerance * scale


def _signal(
    stamp: datetime,
    *,
    selected: tuple[str, ...],
    marks: Mapping[str, Mapping[datetime, Decimal]],
    policy: str,
) -> dict[str, Any]:
    last = stamp - 2 * HOUR
    first = last - BETA_LOOKBACK_RETURNS * HOUR
    clock = [first + offset * HOUR for offset in range(BETA_LOOKBACK_RETURNS + 1)]
    returns: dict[str, list[float]] = {}
    for instrument in selected:
        try:
            points = [marks[instrument][when] for when in clock]
        except KeyError as exc:
            raise C10AHistoricalIndependentError(
                f"independent signal hour missing: {instrument} {iso(exc.args[0])}"
            ) from exc
        values = [
            math.log(float(points[index + 1] / points[index]))
            for index in range(BETA_LOOKBACK_RETURNS)
        ]
        if not all(math.isfinite(value) for value in values):
            raise C10AHistoricalIndependentError("independent log return is invalid")
        returns[instrument] = values
    rows = []
    for instrument in selected:
        dependent = returns[instrument]
        factor = [
            sum(
                returns[other][index]
                for other in selected
                if other != instrument
            )
            / (len(selected) - 1)
            for index in range(BETA_LOOKBACK_RETURNS)
        ]
        mean_x = sum(factor) / len(factor)
        mean_y = sum(dependent) / len(dependent)
        centered_x = [value - mean_x for value in factor]
        denominator = sum(value * value for value in centered_x)
        if not math.isfinite(denominator) or denominator <= 0:
            raise C10AHistoricalIndependentError("independent OLS variance is invalid")
        beta = sum(
            centered_x[index] * (dependent[index] - mean_y)
            for index in range(BETA_LOOKBACK_RETURNS)
        ) / denominator
        alpha = mean_y - beta * mean_x
        raw = sum(dependent[-RESIDUAL_SCORE_RETURNS:])
        residual = sum(
            dependent[index] - alpha - beta * factor[index]
            for index in range(
                BETA_LOOKBACK_RETURNS - RESIDUAL_SCORE_RETURNS,
                BETA_LOOKBACK_RETURNS,
            )
        )
        score = residual if policy == CANDIDATE_ID else raw
        if not all(math.isfinite(value) for value in (alpha, beta, raw, residual, score)):
            raise C10AHistoricalIndependentError("independent signal is non-finite")
        rows.append(
            {
                "instrument": instrument,
                "alpha": alpha,
                "beta": beta,
                "raw_score": raw,
                "residual_score": residual,
                "ranking_score": score,
            }
        )
    rows.sort(key=lambda row: (-float(row["ranking_score"]), str(row["instrument"])))
    longs = [str(row["instrument"]) for row in rows[:2]]
    shorts = [str(row["instrument"]) for row in rows[-2:]]
    return {
        "rows": rows,
        "longs": longs,
        "shorts": shorts,
        "directions": {
            instrument: 1 if instrument in longs else -1 if instrument in shorts else 0
            for instrument in selected
        },
    }


def _drawdown(path: Sequence[Decimal]) -> Decimal:
    peak = path[0]
    result = ZERO
    for value in path:
        peak = max(peak, value)
        result = max(result, ONE - value / peak)
    return result


def _simulate(
    *,
    window_id: str,
    selected: tuple[str, ...],
    trade: Mapping[str, Mapping[datetime, Decimal]],
    marks: Mapping[str, Mapping[datetime, Decimal]],
    funding: Mapping[str, tuple[tuple[datetime, Decimal], ...]],
    policy: str,
    cost_label: str,
) -> dict[str, Any]:
    window = window_by_id(window_id)
    if policy == "CashComparator":
        return {
            "final_equity": STARTING_EQUITY,
            "net_return": ZERO,
            "weekly_returns": [ZERO] * EXPECTED_DECISIONS_PER_WINDOW,
            "weekly_pnl": [ZERO] * EXPECTED_DECISIONS_PER_WINDOW,
            "maximum_drawdown": ZERO,
            "turnover_sum": ZERO,
            "decision_count": EXPECTED_DECISIONS_PER_WINDOW,
            "signal_count": 0,
            "nonflat_direction_count": 0,
            "funding_settlement_count": 0,
            "equity_buffer_breach_count": 0,
            "forced_close_count": 0,
            "components": {"price_pnl": ZERO, "funding_pnl": ZERO, "costs": ZERO},
            "contributions": {},
            "path": [STARTING_EQUITY, STARTING_EQUITY],
            "signals": [],
        }
    rate = COST_RATES[cost_label]
    quantities = {instrument: ZERO for instrument in selected}
    references: dict[str, Decimal | None] = {instrument: None for instrument in selected}
    price_pnl = {instrument: ZERO for instrument in selected}
    funding_pnl = {instrument: ZERO for instrument in selected}
    costs = {instrument: ZERO for instrument in selected}
    equity = STARTING_EQUITY
    path = [equity]
    turnover = ZERO
    buffer_breaches = 0
    forced_closes = 0
    pending_close = False
    suppressed = 0
    signal_rows = []
    nonflat = 0
    weekly_starts: list[Decimal] = []
    weekly_ends: list[Decimal] = []
    source_funding = {
        when: {instrument: value for instrument, value in values}
        for when, values in _group_funding(funding).items()
    }
    funding_count = 0

    def mark_to(instrument: str, price: Decimal) -> None:
        nonlocal equity
        previous = references[instrument]
        if previous is not None:
            movement = quantities[instrument] * (price - previous)
            price_pnl[instrument] += movement
            equity += movement
        references[instrument] = price

    def charge(instrument: str, delta: Decimal, price: Decimal) -> None:
        nonlocal equity
        value = abs(delta) * price * rate
        costs[instrument] += value
        equity -= value

    def check_buffer() -> None:
        nonlocal pending_close, buffer_breaches
        gross = sum(
            (
                abs(quantities[instrument]) * (references[instrument] or ZERO)
                for instrument in selected
            ),
            ZERO,
        )
        if gross > 0 and equity / gross < MINIMUM_EQUITY_TO_GROSS_NOTIONAL:
            if not pending_close:
                buffer_breaches += 1
            pending_close = True

    decisions = set(decision_times(window))
    current = window.start
    while current < window.end_exclusive:
        scheduled = current in decisions
        if scheduled:
            if weekly_starts:
                weekly_ends.append(equity)
            weekly_starts.append(equity)
        funding_at_time = source_funding.get(current, {})
        for instrument, funding_rate in funding_at_time.items():
            reference = references[instrument]
            if quantities[instrument] != 0:
                if reference is None:
                    raise C10AHistoricalIndependentError(
                        "independent active funding lacks prior mark"
                    )
                movement = -quantities[instrument] * reference * funding_rate
                funding_pnl[instrument] += movement
                equity += movement
            funding_count += 1
        if funding_at_time:
            path.append(equity)
        check_buffer()
        suppress = False
        if pending_close:
            for instrument in selected:
                mark_to(instrument, trade[instrument][current])
            path.append(equity)
            before = equity
            changed = ZERO
            for instrument in selected:
                delta = -quantities[instrument]
                changed += abs(delta) * trade[instrument][current]
                charge(instrument, delta, trade[instrument][current])
                quantities[instrument] = ZERO
            turnover += changed / before
            pending_close = False
            forced_closes += 1
            path.append(equity)
            suppress = scheduled
            suppressed += int(suppress)
        if scheduled and not suppress:
            for instrument in selected:
                mark_to(instrument, trade[instrument][current])
            path.append(equity)
            before = equity
            if before <= 0:
                raise C10AHistoricalIndependentError(
                    "independent pretrade equity is non-positive"
                )
            if policy == "AlwaysLongSelectedUniverseComparator":
                directions = {instrument: 1 for instrument in selected}
                fraction = GROSS_NOTIONAL / Decimal(len(selected))
                signal = {"directions": directions}
            else:
                signal = _signal(
                    current, selected=selected, marks=marks, policy=policy
                )
                directions = signal["directions"]
                fraction = PER_POSITION_ABS_NOTIONAL
                nonflat += sum(value != 0 for value in directions.values())
            changed = ZERO
            for instrument in selected:
                price = trade[instrument][current]
                target = Decimal(int(directions[instrument])) * fraction * before / price
                delta = target - quantities[instrument]
                changed += abs(delta) * price
                charge(instrument, delta, price)
                quantities[instrument] = target
            turnover += changed / before
            signal_rows.append(signal)
            path.append(equity)
        for instrument in selected:
            mark_to(instrument, marks[instrument][current])
        if not equity.is_finite() or equity <= 0:
            raise C10AHistoricalIndependentError("independent equity is invalid")
        check_buffer()
        path.append(equity)
        current += HOUR
    for instrument in selected:
        mark_to(instrument, trade[instrument][window.end_exclusive])
    path.append(equity)
    before = equity
    changed = ZERO
    for instrument in selected:
        price = trade[instrument][window.end_exclusive]
        delta = -quantities[instrument]
        changed += abs(delta) * price
        charge(instrument, delta, price)
        quantities[instrument] = ZERO
    turnover += changed / before
    weekly_ends.append(equity)
    path.append(equity)
    if (
        len(weekly_starts) != EXPECTED_DECISIONS_PER_WINDOW
        or len(weekly_ends) != EXPECTED_DECISIONS_PER_WINDOW
    ):
        raise C10AHistoricalIndependentError("independent weekly coverage drift")
    weekly_pnl = [
        end - start for start, end in zip(weekly_starts, weekly_ends, strict=True)
    ]
    weekly_returns = [
        (end - start) / start
        for start, end in zip(weekly_starts, weekly_ends, strict=True)
    ]
    contributions = {
        instrument: price_pnl[instrument] + funding_pnl[instrument] - costs[instrument]
        for instrument in selected
    }
    return {
        "final_equity": equity,
        "net_return": equity / STARTING_EQUITY - ONE,
        "weekly_returns": weekly_returns,
        "weekly_pnl": weekly_pnl,
        "maximum_drawdown": _drawdown(path),
        "turnover_sum": turnover,
        "decision_count": EXPECTED_DECISIONS_PER_WINDOW,
        "signal_count": EXPECTED_DECISIONS_PER_WINDOW - suppressed,
        "nonflat_direction_count": nonflat,
        "funding_settlement_count": funding_count,
        "equity_buffer_breach_count": buffer_breaches,
        "forced_close_count": forced_closes,
        "components": {
            "price_pnl": sum(price_pnl.values(), ZERO),
            "funding_pnl": sum(funding_pnl.values(), ZERO),
            "costs": sum(costs.values(), ZERO),
        },
        "contributions": contributions,
        "path": path,
        "signals": signal_rows,
    }


def _group_funding(
    values: Mapping[str, tuple[tuple[datetime, Decimal], ...]],
) -> dict[datetime, list[tuple[str, Decimal]]]:
    output: dict[datetime, list[tuple[str, Decimal]]] = {}
    for instrument, rows in values.items():
        for stamp, rate in rows:
            output.setdefault(stamp, []).append((instrument, rate))
    return output


def _signal_match(expected: Mapping[str, Any], observed: Mapping[str, Any]) -> bool:
    if (
        observed.get("directions") != expected.get("directions")
        or observed.get("longs") != expected.get("longs")
        or observed.get("shorts") != expected.get("shorts")
    ):
        return False
    left = expected.get("rows", [])
    right = observed.get("rows", [])
    return len(left) == len(right) and all(
        expected_row.get("instrument") == observed_row.get("instrument")
        and all(
            _close(expected_row.get(field), observed_row.get(field))
            for field in (
                "alpha",
                "beta",
                "raw_score",
                "residual_score",
                "ranking_score",
            )
        )
        for expected_row, observed_row in zip(left, right, strict=True)
    )


def _review_replay(expected: Mapping[str, Any], retained: Mapping[str, Any]) -> dict[str, Any]:
    scalar_fields = (
        "final_equity",
        "net_return",
        "maximum_drawdown",
        "turnover_sum",
    )
    count_fields = (
        "decision_count",
        "signal_count",
        "nonflat_direction_count",
        "funding_settlement_count",
        "equity_buffer_breach_count",
        "forced_close_count",
    )
    retained_weekly = retained.get("weekly_returns", [])
    retained_buckets = retained.get("weekly_buckets", [])
    retained_path = retained.get("complete_hourly_equity_path", [])
    checks = {
        "scalar_recompute": all(
            _close(expected[field], retained.get(field)) for field in scalar_fields
        ),
        "counter_recompute": all(
            int(retained.get(field, -1)) == int(expected[field]) for field in count_fields
        ),
        "weekly_return_recompute": len(retained_weekly)
        == len(expected["weekly_returns"])
        and all(
            _close(left, right)
            for left, right in zip(expected["weekly_returns"], retained_weekly, strict=True)
        ),
        "weekly_pnl_recompute": len(retained_buckets) == len(expected["weekly_pnl"])
        and all(
            _close(left, right.get("weekly_pnl"))
            for left, right in zip(expected["weekly_pnl"], retained_buckets, strict=True)
        ),
        "complete_path_recompute": len(retained_path) == len(expected["path"])
        and all(
            _close(left, right.get("equity"))
            for left, right in zip(expected["path"], retained_path, strict=True)
        ),
        "component_recompute": all(
            _close(value, retained.get("component_totals", {}).get(key))
            for key, value in expected["components"].items()
        ),
        "contribution_recompute": set(retained.get("contributions", {}))
        == set(expected["contributions"])
        and all(
            _close(value, retained["contributions"][instrument].get("net"))
            for instrument, value in expected["contributions"].items()
        ),
        "signal_inventory_recompute": len(retained.get("signals", []))
        == len(expected["signals"]),
        "safety_boundary": all(
            retained.get(key) == value for key, value in safety_boundary().items()
        ),
    }
    if expected["signals"] and "rows" in expected["signals"][0]:
        checks["signal_value_recompute"] = all(
            _signal_match(left, right)
            for left, right in zip(
                expected["signals"], retained.get("signals", []), strict=True
            )
        )
    else:
        checks["signal_value_recompute"] = all(
            left.get("directions") == right.get("directions")
            for left, right in zip(
                expected["signals"], retained.get("signals", []), strict=True
            )
        )
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def _benchmark_returns(
    window_id: str, rows: Sequence[Mapping[str, Any]]
) -> list[Decimal]:
    window = window_by_id(window_id)
    marks = _series(rows, "close", "independent BTC benchmark")
    output = []
    for start in decision_times(window):
        end = start + 7 * 24 * HOUR
        try:
            output.append(marks[end - HOUR] / marks[start - HOUR] - ONE)
        except KeyError as exc:
            raise C10AHistoricalIndependentError(
                f"independent BTC benchmark hour missing: {iso(exc.args[0])}"
            ) from exc
    return output


def review_historical_window(
    producer: Mapping[str, Any],
    *,
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    selected = tuple(str(value) for value in producer.get("selected_universe", ()))
    window_id = str(producer.get("window", {}).get("window_id"))
    window = window_by_id(window_id)
    if (
        len(selected) != 8
        or set(trade_rows) != set(selected)
        or set(funding_rows) != set(selected)
        or set(mark_rows) != {*selected, BTC_BETA_BENCHMARK}
        or set(producer.get("replays", {})) != set(POLICIES)
    ):
        raise C10AHistoricalIndependentError("independent window inventory drift")
    trade = {
        instrument: _series(trade_rows[instrument], "open", f"{instrument} trade")
        for instrument in selected
    }
    marks = {
        instrument: _series(mark_rows[instrument], "close", f"{instrument} mark")
        for instrument in selected
    }
    funding = {
        instrument: _funding(funding_rows[instrument], instrument)
        for instrument in selected
    }
    for instrument in selected:
        _require_complete_clock(
            trade[instrument],
            start=window.start,
            end_inclusive=window.end_exclusive,
            label=f"{instrument} trade",
        )
        _require_complete_clock(
            marks[instrument],
            start=window.start - (BETA_LOOKBACK_RETURNS + 2) * HOUR,
            end_inclusive=window.end_exclusive - HOUR,
            label=f"{instrument} mark",
        )
        _require_funding_coverage(
            funding[instrument],
            start=window.start,
            end_exclusive=window.end_exclusive,
            label=instrument,
        )
    benchmark_marks = _series(
        mark_rows[BTC_BETA_BENCHMARK],
        "close",
        "independent BTC benchmark",
    )
    _require_complete_clock(
        benchmark_marks,
        start=window.start - HOUR,
        end_inclusive=window.end_exclusive - HOUR,
        label="BTC benchmark mark",
    )
    reviews = {}
    for policy in POLICIES:
        if set(producer["replays"][policy]) != set(COST_RATES):
            raise C10AHistoricalIndependentError("independent cost inventory drift")
        for cost_label in COST_RATES:
            expected = _simulate(
                window_id=window_id,
                selected=selected,
                trade=trade,
                marks=marks,
                funding=funding,
                policy=policy,
                cost_label=cost_label,
            )
            reviews[f"{policy}:{cost_label}"] = _review_replay(
                expected, producer["replays"][policy][cost_label]
            )
    benchmark = _benchmark_returns(window_id, mark_rows[BTC_BETA_BENCHMARK])
    retained_benchmark = producer.get("btc_weekly_mark_returns", [])
    benchmark_match = len(benchmark) == len(retained_benchmark) and all(
        _close(left, right)
        for left, right in zip(benchmark, retained_benchmark, strict=True)
    )
    passed = benchmark_match and all(
        review["status"] == "PASS" for review in reviews.values()
    )
    return {
        "schema_version": 1,
        "stage": "C10A_WINDOW_INDEPENDENT_RECOMPUTE",
        "window_id": window_id,
        "status": "PASS" if passed else "FAIL",
        "replay_reviews": reviews,
        "btc_benchmark_recompute": benchmark_match,
        "imports_production_replay": False,
        "imports_production_signal": False,
        "imports_production_ledger": False,
        "imports_production_gate_or_finalizer": False,
        **safety_boundary(),
    }


def _stats(values: Sequence[Decimal]) -> dict[str, float | int | bool]:
    raw = [float(value) for value in values]
    if len(raw) != EXPECTED_TOTAL_DECISIONS or not all(
        math.isfinite(value) for value in raw
    ):
        raise C10AHistoricalIndependentError(
            "independent pooled weekly coverage is invalid"
        )
    deviation = stdev(raw)
    if deviation <= 0 or not math.isfinite(deviation):
        return {
            "n": len(raw),
            "annualized_weekly_sharpe": 0.0,
            "psr_probability": 0.0,
            "valid": False,
        }
    weekly_sharpe = mean(raw) / deviation
    n = len(raw)
    average = sum(raw) / n
    centered = [value - average for value in raw]
    moment_two = sum(value**2 for value in centered) / n
    moment_three = sum(value**3 for value in centered) / n
    moment_four = sum(value**4 for value in centered) / n
    if moment_two <= 0:
        raise C10AHistoricalIndependentError(
            "independent weekly central variance is invalid"
        )
    raw_skew = moment_three / moment_two**1.5
    asymmetry = math.sqrt(n * (n - 1)) / (n - 2) * raw_skew
    raw_fisher_kurtosis = moment_four / moment_two**2 - 3
    unbiased_fisher_kurtosis = (n - 1) / ((n - 2) * (n - 3)) * (
        (n + 1) * raw_fisher_kurtosis + 6
    )
    ordinary = unbiased_fisher_kurtosis + 3
    radicand = 1 - asymmetry * weekly_sharpe + ((ordinary - 1) / 4) * weekly_sharpe**2
    probability = (
        0.5
        * (
            1
            + math.erf(
                weekly_sharpe
                * math.sqrt(len(raw) - 1)
                / math.sqrt(radicand)
                / math.sqrt(2)
            )
        )
        if math.isfinite(radicand) and radicand > 0
        else 0.0
    )
    return {
        "n": len(raw),
        "annualized_weekly_sharpe": weekly_sharpe * math.sqrt(52),
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
    """Recompute every pooled metric and gate without production metric imports."""

    expected_ids = {window.window_id for window in HISTORICAL_WINDOWS}
    if set(windows) != expected_ids:
        raise C10AHistoricalIndependentError("independent pooled inventory drift")
    reference: dict[str, dict[str, dict[str, Any]]] = {}
    for policy in POLICIES:
        reference[policy] = {}
        for cost_label in COST_RATES:
            rows = [
                windows[window.window_id]["replays"][policy][cost_label]
                for window in HISTORICAL_WINDOWS
            ]
            finals = [Decimal(str(row["final_equity"])) for row in rows]
            weekly = [
                Decimal(str(value)) for row in rows for value in row["weekly_returns"]
            ]
            instrument_pnl: dict[str, Decimal] = {}
            for row in rows:
                for instrument, parts in row["contributions"].items():
                    instrument_pnl[instrument] = instrument_pnl.get(
                        instrument, ZERO
                    ) + Decimal(str(parts["net"]))
            reference[policy][cost_label] = {
                "aggregate_return": sum(finals, ZERO) / Decimal(5000) - ONE,
                "window_returns": [Decimal(str(row["net_return"])) for row in rows],
                "window_pnl": [value - STARTING_EQUITY for value in finals],
                "weekly": weekly,
                "weekly_pnl": [
                    Decimal(str(bucket["weekly_pnl"]))
                    for row in rows
                    for bucket in row["weekly_buckets"]
                ],
                "statistics": _stats(weekly),
                "adjusted_psr": max(
                    ZERO,
                    ONE
                    - Decimal(TRIAL_COUNT)
                    * (ONE - Decimal(str(_stats(weekly)["psr_probability"]))),
                ),
                "drawdown": max(Decimal(str(row["maximum_drawdown"])) for row in rows),
                "turnover": sum(
                    (Decimal(str(row["turnover_sum"])) for row in rows), ZERO
                )
                / Decimal("2.5"),
                "decisions": sum(int(row["decision_count"]) for row in rows),
                "nonflat": sum(int(row["nonflat_direction_count"]) for row in rows),
                "buffer_breaches": sum(
                    int(row["equity_buffer_breach_count"]) for row in rows
                ),
                "instrument_pnl": instrument_pnl,
            }
    candidate = reference[CANDIDATE_ID]["1.0x"]
    raw = reference["RawReturnMomentumComparator"]["1.0x"]
    btc = [
        Decimal(str(value))
        for window in HISTORICAL_WINDOWS
        for value in windows[window.window_id]["btc_weekly_mark_returns"]
    ]
    if len(btc) != EXPECTED_TOTAL_DECISIONS:
        raise C10AHistoricalIndependentError(
            "independent BTC weekly coverage is invalid"
        )
    candidate_mean = sum(candidate["weekly"], ZERO) / Decimal(len(candidate["weekly"]))
    btc_mean = sum(btc, ZERO) / Decimal(len(btc))
    btc_variance = sum(((value - btc_mean) ** 2 for value in btc), ZERO)
    if btc_variance <= 0:
        raise C10AHistoricalIndependentError("independent pooled BTC variance is zero")
    beta = sum(
        (
            (left - candidate_mean) * (right - btc_mean)
            for left, right in zip(candidate["weekly"], btc, strict=True)
        ),
        ZERO,
    ) / btc_variance
    instrument_values = list(candidate["instrument_pnl"].values())
    instrument_share = _share(instrument_values)
    window_share = _share(candidate["window_pnl"])
    week_share = _share(candidate["weekly_pnl"])
    top_three = _share(candidate["weekly_pnl"], 3)
    candidate_sharpe = Decimal(
        str(candidate["statistics"]["annualized_weekly_sharpe"])
    )
    raw_sharpe = Decimal(str(raw["statistics"]["annualized_weekly_sharpe"]))
    gates = {
        "all_five_windows_positive": all(value > 0 for value in candidate["window_returns"]),
        "aggregate_1_0x_return_positive": candidate["aggregate_return"] > 0,
        "aggregate_1_5x_return_positive": reference[CANDIDATE_ID]["1.5x"][
            "aggregate_return"
        ]
        > 0,
        "aggregate_2_0x_return_nonnegative": reference[CANDIDATE_ID]["2.0x"][
            "aggregate_return"
        ]
        >= 0,
        "annualized_weekly_sharpe": candidate_sharpe >= Decimal("1.00"),
        "weekly_psr": Decimal(str(candidate["statistics"]["psr_probability"]))
        >= Decimal("0.95"),
        "bonferroni_adjusted_psr": candidate["adjusted_psr"] >= Decimal("0.95"),
        "maximum_window_drawdown": candidate["drawdown"] <= Decimal("0.15"),
        "absolute_btc_beta": abs(beta) <= Decimal("0.20"),
        "zero_equity_buffer_breaches": candidate["buffer_breaches"] == 0,
        "required_decisions": candidate["decisions"] == EXPECTED_TOTAL_DECISIONS,
        "required_nonflat_instrument_directions": candidate["nonflat"]
        == EXPECTED_NONFLAT_DIRECTIONS,
        "annualized_one_way_turnover": candidate["turnover"] <= Decimal("18.0"),
        "positive_instrument_breadth": sum(value > 0 for value in instrument_values)
        >= 6,
        "instrument_concentration": instrument_share is not None
        and instrument_share <= Decimal("0.35"),
        "window_concentration": window_share is not None
        and window_share <= Decimal("0.40"),
        "week_concentration": week_share is not None
        and week_share <= Decimal("0.15"),
        "top_three_week_concentration": top_three is not None
        and top_three <= Decimal("0.35"),
        "return_delta_vs_raw_momentum": candidate["aggregate_return"]
        - raw["aggregate_return"]
        > 0,
        "sharpe_delta_vs_raw_momentum": candidate_sharpe - raw_sharpe
        >= Decimal("0.10"),
        "drawdown_no_worse_than_raw_momentum": candidate["drawdown"]
        <= raw["drawdown"],
        "turnover_no_greater_than_raw_momentum": candidate["turnover"]
        <= raw["turnover"],
    }
    pooled_match = True
    for policy, by_cost in reference.items():
        for cost_label, expected in by_cost.items():
            observed = producer.get("pooled", {}).get(policy, {}).get(cost_label, {})
            pooled_match &= all(
                (
                    _close(observed.get("aggregate_return"), expected["aggregate_return"]),
                    _close(observed.get("maximum_drawdown"), expected["drawdown"]),
                    _close(
                        observed.get("annualized_one_way_turnover"),
                        expected["turnover"],
                    ),
                    _close(
                        observed.get("statistics", {}).get(
                            "annualized_weekly_sharpe"
                        ),
                        expected["statistics"]["annualized_weekly_sharpe"],
                    ),
                    _close(
                        observed.get("statistics", {}).get("psr_probability"),
                        expected["statistics"]["psr_probability"],
                    ),
                    _close(observed.get("bonferroni_adjusted_psr"), expected["adjusted_psr"]),
                )
            )
    verdict = "ECONOMIC_PASS" if all(gates.values()) else "ECONOMIC_FAIL"
    passed = (
        pooled_match
        and _close(producer.get("candidate_btc_beta"), beta)
        and producer.get("eligibility_gates") == gates
        and producer.get("overall_economic_verdict") == verdict
    )
    return {
        "schema_version": 1,
        "stage": "C10A_POOLED_INDEPENDENT_RECOMPUTE",
        "status": "PASS" if passed else "FAIL",
        "pooled_metrics_match": pooled_match,
        "btc_beta_match": _close(producer.get("candidate_btc_beta"), beta),
        "gate_recompute_match": producer.get("eligibility_gates") == gates,
        "reference_gates": gates,
        "reference_final_verdict": verdict,
        "imports_production_replay": False,
        "imports_production_signal": False,
        "imports_production_ledger": False,
        "imports_production_gate_or_finalizer": False,
        **safety_boundary(),
    }


__all__ = [
    "C10AHistoricalIndependentError",
    "review_formation_universe",
    "review_historical_window",
    "review_pooled_summary",
]
