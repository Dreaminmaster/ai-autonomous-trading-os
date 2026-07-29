"""Physically separate reference review for C8A historical evidence.

This module deliberately does not import the production signal or replay
module.  It derives signal endpoints from source rows and recomputes every
retained price, funding, fee, target, weekly-return, drawdown and attribution
identity before accepting a producer result.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
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
    MINIMUM_WORST_WINDOW_RETURN,
    SIGNAL_CLOSE_COUNT,
    TARGET_ABS_WEIGHT,
)
from atos.c8a_historical_schedule import HOUR, decision_times, window_by_id


class C8AHistoricalIndependentError(RuntimeError):
    """Raised when source-derived reference review cannot be completed."""


def _time(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise C8AHistoricalIndependentError(
            f"invalid retained timestamp: {value!r}"
        ) from exc
    if result.tzinfo is None:
        raise C8AHistoricalIndependentError("retained timestamp must be timezone-aware")
    return result.astimezone(UTC)


def _number(value: Any, *, positive: bool = False) -> float:
    if value is None or isinstance(value, bool):
        raise C8AHistoricalIndependentError("retained number is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C8AHistoricalIndependentError("retained number is invalid") from exc
    if not math.isfinite(result) or (positive and result <= 0):
        raise C8AHistoricalIndependentError(
            "retained number is non-finite or non-positive"
        )
    return result


def _close(left: Any, right: Any, tolerance: float = 1e-9) -> bool:
    return math.isclose(
        _number(left), _number(right), rel_tol=tolerance, abs_tol=tolerance
    )


def _prices(rows: Sequence[Mapping[str, Any]], field: str) -> dict[datetime, float]:
    output: dict[datetime, float] = {}
    prior = None
    for row in rows:
        stamp = _time(row.get("timestamp"))
        if prior is not None and stamp <= prior:
            raise C8AHistoricalIndependentError(
                "source price rows are duplicate or unordered"
            )
        output[stamp] = _number(row.get(field), positive=True)
        prior = stamp
    return output


def _funding(rows: Sequence[Mapping[str, Any]]) -> dict[datetime, float]:
    output: dict[datetime, float] = {}
    prior = None
    for row in rows:
        stamp = _time(row.get("funding_time"))
        if prior is not None and stamp <= prior:
            raise C8AHistoricalIndependentError(
                "source funding rows are duplicate or unordered"
            )
        output[stamp] = _number(row.get("realized_rate"))
        prior = stamp
    return output


def _source_signals(
    window_id: str, marks: Mapping[str, Mapping[datetime, float]]
) -> list[dict[str, Any]]:
    output = []
    for decision in decision_times(window_id):
        oldest = decision - timedelta(hours=SIGNAL_CLOSE_COUNT + 1)
        latest = decision - 2 * HOUR
        endpoints: dict[str, dict[str, Any]] = {}
        momentum: dict[str, float] = {}
        directions: dict[str, int] = {}
        for instrument in INSTRUMENTS:
            required = [oldest + index * HOUR for index in range(SIGNAL_CLOSE_COUNT)]
            if any(stamp not in marks[instrument] for stamp in required):
                raise C8AHistoricalIndependentError(
                    "reference signal has a missing mark hour"
                )
            value = marks[instrument][latest] / marks[instrument][oldest] - 1.0
            endpoints[instrument] = {
                "oldest_timestamp": oldest.isoformat().replace("+00:00", "Z"),
                "oldest_close_time": (oldest + HOUR).isoformat().replace("+00:00", "Z"),
                "oldest_close": marks[instrument][oldest],
                "latest_timestamp": latest.isoformat().replace("+00:00", "Z"),
                "latest_close_time": (latest + HOUR).isoformat().replace("+00:00", "Z"),
                "latest_close": marks[instrument][latest],
                "close_count": SIGNAL_CLOSE_COUNT,
            }
            momentum[instrument] = value
            directions[instrument] = 1 if value > 0 else -1 if value < 0 else 0
        output.append(
            {
                "decision_time": decision.isoformat().replace("+00:00", "Z"),
                "endpoints": endpoints,
                "momentum_7d": momentum,
                "directions": directions,
            }
        )
    return output


def _signals_match(reference: Sequence[Mapping[str, Any]], observed: Any) -> bool:
    if not isinstance(observed, list) or len(reference) != len(observed):
        return False
    for expected, actual in zip(reference, observed, strict=True):
        if (
            actual.get("decision_time") != expected["decision_time"]
            or actual.get("directions") != expected["directions"]
        ):
            return False
        for instrument in INSTRUMENTS:
            if (
                actual.get("endpoints", {}).get(instrument)
                != expected["endpoints"][instrument]
            ):
                return False
            if not _close(
                actual.get("momentum_7d", {}).get(instrument),
                expected["momentum_7d"][instrument],
            ):
                return False
    return True


def _drawdown(path: Sequence[Any]) -> float:
    if not path:
        raise C8AHistoricalIndependentError("complete equity path is empty")
    peak = _number(path[0], positive=True)
    maximum = 0.0
    for item in path:
        equity = _number(item, positive=True)
        peak = max(peak, equity)
        maximum = max(maximum, (peak - equity) / peak)
    return maximum


def _review_replay(
    replay: Mapping[str, Any],
    *,
    policy: str,
    signals: Sequence[Mapping[str, Any]],
    marks: Mapping[str, Mapping[datetime, float]],
    trades: Mapping[str, Mapping[datetime, float]],
    funding: Mapping[str, Mapping[datetime, float]],
    window_id: str,
) -> dict[str, Any]:
    checks: dict[str, bool] = {}
    label = replay.get("cost_label")
    checks["identity"] = (
        replay.get("policy") == policy
        and label in COST_RATES
        and _close(replay.get("cost_rate"), COST_RATES.get(label, -1.0))
    )
    fee_rate = COST_RATES[str(label)] if label in COST_RATES else -1.0

    price_sum = 0.0
    price_by_instrument = defaultdict(float)
    price_events = replay.get("price_events")
    checks["price_event_schema"] = isinstance(price_events, list)
    if isinstance(price_events, list):
        valid = True
        for event in price_events:
            try:
                instrument = event["instrument"]
                stamp = _time(event["timestamp"])
                quantity = _number(event["quantity"])
                start = _number(event["from_price"], positive=True)
                end = _number(event["to_price"], positive=True)
                pnl = quantity * (end - start)
                source_stamp = (
                    _time(event.get("source_timestamp"))
                    if event["destination_kind"] == "MARK_CLOSE"
                    else stamp
                )
                source = (
                    marks[instrument].get(source_stamp)
                    if event["destination_kind"] == "MARK_CLOSE"
                    else trades[instrument].get(stamp)
                )
                valid &= (
                    instrument in INSTRUMENTS
                    and source is not None
                    and _close(end, source)
                    and _close(pnl, event["price_pnl"])
                )
                price_sum += pnl
                price_by_instrument[instrument] += pnl
            except (KeyError, TypeError, C8AHistoricalIndependentError):
                valid = False
        checks["price_events_source_recompute"] = valid and _close(
            price_sum, replay.get("gross_price_pnl")
        )
    else:
        checks["price_events_source_recompute"] = False

    window = window_by_id(window_id)
    expected_funding = {
        (instrument, stamp)
        for instrument in INSTRUMENTS
        for stamp in funding[instrument]
        if window.first_scored_decision <= stamp <= window.end_exclusive
    }
    observed_funding: set[tuple[str, datetime]] = set()
    funding_sum = 0.0
    funding_by_instrument = defaultdict(float)
    valid_funding = isinstance(replay.get("funding_events"), list)
    if valid_funding:
        for event in replay["funding_events"]:
            try:
                instrument = event["instrument"]
                stamp = _time(event["timestamp"])
                predecessor_stamp = _time(event["predecessor_mark_timestamp"])
                predecessor_close = _time(event["predecessor_mark_close_time"])
                rate = funding[instrument][stamp]
                predecessor = marks[instrument][predecessor_stamp]
                quantity = _number(event["quantity"])
                signed = quantity * predecessor
                pnl = -signed * rate
                valid_funding &= predecessor_close == predecessor_stamp + HOUR
                valid_funding &= predecessor_stamp == (stamp - HOUR).replace(
                    minute=0, second=0, microsecond=0
                )
                valid_funding &= (
                    predecessor_close <= stamp and stamp - predecessor_close <= HOUR
                )
                valid_funding &= _close(rate, event["rate"]) and _close(
                    predecessor, event["predecessor_mark"]
                )
                valid_funding &= _close(
                    signed, event["signed_mark_notional"]
                ) and _close(pnl, event["funding_pnl"])
                observed_funding.add((instrument, stamp))
                funding_sum += pnl
                funding_by_instrument[instrument] += pnl
            except (KeyError, TypeError, C8AHistoricalIndependentError):
                valid_funding = False
    checks["funding_events_source_recompute"] = (
        valid_funding
        and observed_funding == expected_funding
        and _close(funding_sum, replay.get("funding_pnl"))
    )

    trade_events = replay.get("trade_events")
    trade_cost = 0.0
    trade_by_instrument = defaultdict(float)
    valid_trades = isinstance(trade_events, list)
    scheduled: dict[datetime, list[Mapping[str, Any]]] = defaultdict(list)
    turnover = 0.0
    if valid_trades:
        for event in trade_events:
            try:
                instrument = event["instrument"]
                stamp = _time(event["timestamp"])
                opening = trades[instrument][stamp]
                old_quantity = _number(event["old_quantity"])
                target_quantity = _number(event["target_quantity"])
                old_value = old_quantity * opening
                target_value = target_quantity * opening
                one_way = abs(target_value - old_value)
                cost = fee_rate * one_way
                equity_before = _number(event["equity_before"], positive=True)
                valid_trades &= _close(opening, event["execution_price"])
                valid_trades &= _close(
                    old_value, event["old_signed_notional"]
                ) and _close(target_value, event["target_signed_notional"])
                valid_trades &= _close(one_way, event["one_way_notional"]) and _close(
                    cost, event["cost"]
                )
                if event["kind"] in {"RISK_CLOSE", "TERMINAL_CLOSE"}:
                    valid_trades &= _close(target_value, 0.0)
                if event["kind"] == "SCHEDULED_REBALANCE":
                    scheduled[stamp].append(event)
                trade_cost += cost
                trade_by_instrument[instrument] += cost
                turnover += one_way / equity_before
            except (KeyError, TypeError, C8AHistoricalIndependentError):
                valid_trades = False
    reference_by_time = {_time(signal["decision_time"]): signal for signal in signals}
    valid_targets = set(scheduled) == set(reference_by_time)
    for stamp, events in scheduled.items():
        if len(events) != len(INSTRUMENTS) or {
            event.get("instrument") for event in events
        } != set(INSTRUMENTS):
            valid_targets = False
            continue
        directions = reference_by_time[stamp]["directions"]
        if policy == "cash":
            directions = {instrument: 0 for instrument in INSTRUMENTS}
        elif policy == "always_long_perpetual":
            directions = {instrument: 1 for instrument in INSTRUMENTS}
        equity_before_values = {
            _number(event["equity_before"], positive=True) for event in events
        }
        if len(equity_before_values) != 1:
            valid_targets = False
            continue
        equity_before = next(iter(equity_before_values))
        after = equity_before - sum(_number(event["cost"]) for event in events)
        for event in events:
            instrument = event["instrument"]
            requested = int(event["requested_direction"])
            executed = int(event["executed_direction"])
            valid_targets &= requested == directions[instrument]
            valid_targets &= executed in {requested, 0}
            valid_targets &= _close(
                event["target_signed_notional"], executed * TARGET_ABS_WEIGHT * after
            )
    checks["trade_events_source_recompute"] = (
        valid_trades
        and _close(trade_cost, replay.get("costs"))
        and _close(turnover, replay.get("one_way_turnover_ratio"))
    )
    checks["scheduled_targets_recompute"] = valid_targets

    weekly_equity = replay.get("weekly_equity")
    weekly = replay.get("weekly_returns")
    valid_weekly = (
        isinstance(weekly_equity, list)
        and isinstance(weekly, list)
        and len(weekly_equity) == len(weekly) == 26
    )
    if valid_weekly:
        for item, reported in zip(weekly_equity, weekly, strict=True):
            start = _number(item.get("start_equity"), positive=True)
            end = _number(item.get("end_equity"), positive=True)
            recomputed = end / start - 1.0
            valid_weekly &= _close(recomputed, item.get("weekly_return")) and _close(
                recomputed, reported
            )
        valid_weekly &= _close(
            math.prod(1.0 + _number(value) for value in weekly),
            replay.get("final_equity"),
        )
    checks["weekly_returns_recompute"] = valid_weekly
    checks["drawdown_recompute"] = _close(
        _drawdown(replay.get("complete_equity_path", [])),
        replay.get("maximum_drawdown"),
    )
    final_equity = 1.0 + price_sum + funding_sum - trade_cost
    checks["final_equity_recompute"] = _close(
        final_equity, replay.get("final_equity")
    ) and _close(final_equity - 1.0, replay.get("net_return"))
    contributions = replay.get("instrument_contributions", {})
    checks["attribution_recompute"] = all(
        _close(
            price_by_instrument[instrument]
            + funding_by_instrument[instrument]
            - trade_by_instrument[instrument],
            contributions.get(instrument),
        )
        for instrument in INSTRUMENTS
    )
    return {"status": "PASS" if all(checks.values()) else "FAIL", "checks": checks}


def review_historical_window(
    producer: Mapping[str, Any],
    *,
    mark_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    trade_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    funding_rows: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    window = producer.get("window")
    if not isinstance(window, Mapping):
        raise C8AHistoricalIndependentError("producer window metadata is absent")
    window_id = str(window.get("window_id"))
    marks = {
        instrument: _prices(mark_rows[instrument], "close")
        for instrument in INSTRUMENTS
    }
    trades = {
        instrument: _prices(trade_rows[instrument], "open")
        for instrument in INSTRUMENTS
    }
    funding = {
        instrument: _funding(funding_rows[instrument]) for instrument in INSTRUMENTS
    }
    reference_signals = _source_signals(window_id, marks)
    signal_pass = _signals_match(reference_signals, producer.get("signals"))
    reviews: dict[str, Any] = {}
    for policy in ("candidate", "cash", "always_long_perpetual"):
        for cost_label in COST_RATES:
            key = f"{policy}:{cost_label}"
            replay = producer.get("replays", {}).get(policy, {}).get(cost_label)
            reviews[key] = (
                _review_replay(
                    replay,
                    policy=policy,
                    signals=reference_signals,
                    marks=marks,
                    trades=trades,
                    funding=funding,
                    window_id=window_id,
                )
                if isinstance(replay, Mapping)
                else {"status": "FAIL", "checks": {"replay_present": False}}
            )
    status = (
        "PASS"
        if signal_pass and all(value["status"] == "PASS" for value in reviews.values())
        else "FAIL"
    )
    return {
        "schema_version": 1,
        "stage": "C8A_HISTORICAL_INDEPENDENT_RECOMPUTE",
        "window_id": window_id,
        "status": status,
        "source_signal_recompute_passed": signal_pass,
        "replay_reviews": reviews,
        "imports_production_replay": False,
        "live_state": "LIVE_FORBIDDEN",
    }


def _reference_statistics(values: Sequence[float]) -> dict[str, float]:
    count = len(values)
    if count < 2:
        return {"annualized_sharpe": 0.0, "psr": 0.0}
    average = sum(values) / count
    variance = sum((value - average) ** 2 for value in values) / (count - 1)
    if variance <= 0 or not math.isfinite(variance):
        return {"annualized_sharpe": 0.0, "psr": 0.0}
    deviation = math.sqrt(variance)
    raw = average / deviation
    second = sum((value - average) ** 2 for value in values) / count
    third = sum((value - average) ** 3 for value in values) / count
    fourth = sum((value - average) ** 4 for value in values) / count
    skew = (
        math.sqrt(count * (count - 1)) / (count - 2) * third / second**1.5
        if count > 2 and second > 0
        else 0.0
    )
    kurtosis = fourth / second**2 if second > 0 else 3.0
    variance_of_sharpe = (1.0 - skew * raw + (kurtosis - 1.0) * raw**2 / 4.0) / (
        count - 1
    )
    probability = (
        0.0
        if variance_of_sharpe <= 0 or not math.isfinite(variance_of_sharpe)
        else 0.5
        * (1.0 + math.erf(raw / math.sqrt(variance_of_sharpe) / math.sqrt(2.0)))
    )
    return {
        "weekly_mean": average,
        "weekly_sample_std": deviation,
        "weekly_sharpe_raw": raw,
        "annualized_sharpe": raw * math.sqrt(52.0),
        "sample_skewness": skew,
        "ordinary_kurtosis": kurtosis,
        "psr": probability,
    }


def _reference_pool(
    windows: Mapping[str, Any], policy: str, cost_label: str
) -> dict[str, Any]:
    results = [
        windows[f"H{index}"]["replays"][policy][cost_label] for index in range(1, 6)
    ]
    weekly = [value for result in results for value in result["weekly_returns"]]
    return {
        "window_net_returns": [result["net_return"] for result in results],
        "pooled_net_return": math.prod(1.0 + result["net_return"] for result in results)
        - 1.0,
        "weekly_returns": weekly,
        "statistics": _reference_statistics(weekly),
        "maximum_window_drawdown": max(
            result["maximum_drawdown"] for result in results
        ),
        "margin_buffer_breach_count": sum(
            result["margin_buffer_breach_count"] for result in results
        ),
        "annualized_one_way_turnover": sum(
            result["one_way_turnover_ratio"] for result in results
        )
        / 2.5,
        "instrument_contributions": {
            instrument: sum(
                result["instrument_contributions"][instrument] for result in results
            )
            for instrument in INSTRUMENTS
        },
        "weekly_contributions": [
            value for result in results for value in result["weekly_contributions"]
        ],
        "flat_direction_count": sum(
            result["flat_direction_count"] for result in results
        ),
        "missing_decision_count": sum(
            result["missing_decision_count"] for result in results
        ),
        "unaccounted_funding_settlement_count": sum(
            result["unaccounted_funding_settlement_count"] for result in results
        ),
    }


def _reference_concentration(values: Sequence[float], count: int = 1) -> float:
    positive = sorted((value for value in values if value > 0), reverse=True)
    total = sum(positive)
    return math.inf if total <= 0 else sum(positive[:count]) / total


def _reference_beta(candidate: Sequence[float], benchmark: Sequence[float]) -> float:
    average_x = sum(benchmark) / len(benchmark)
    average_y = sum(candidate) / len(candidate)
    denominator = sum((value - average_x) ** 2 for value in benchmark)
    if denominator <= 0 or not math.isfinite(denominator):
        raise C8AHistoricalIndependentError("reference BTC variance is invalid")
    return (
        sum(
            (x - average_x) * (y - average_y)
            for x, y in zip(benchmark, candidate, strict=True)
        )
        / denominator
    )


def review_pooled_summary(
    producer: Mapping[str, Any], windows: Mapping[str, Any]
) -> dict[str, Any]:
    """Recompute the complete pooled final decision without production imports."""
    candidates = {
        label: _reference_pool(windows, "candidate", label) for label in COST_RATES
    }
    comparators = {
        label: _reference_pool(windows, "always_long_perpetual", label)
        for label in COST_RATES
    }
    expected = candidates["1.0x"]
    comparator = comparators["1.0x"]
    benchmark = [
        value
        for index in range(1, 6)
        for value in windows[f"H{index}"]["btc_weekly_mark_returns"]
    ]
    beta = _reference_beta(expected["weekly_returns"], benchmark)
    returns = expected["window_net_returns"]
    instrument_concentration = _reference_concentration(
        list(expected["instrument_contributions"].values())
    )
    window_concentration = _reference_concentration(returns)
    week_concentration = _reference_concentration(expected["weekly_contributions"])
    top_three = _reference_concentration(expected["weekly_contributions"], 3)
    nonflat = EXPECTED_INSTRUMENT_DIRECTIONS - expected["flat_direction_count"]
    gates = {
        "positive_windows": sum(value > 0 for value in returns)
        >= MINIMUM_POSITIVE_WINDOWS,
        "median_window_positive": median(returns) > 0,
        "worst_window": min(returns) > MINIMUM_WORST_WINDOW_RETURN,
        "pooled_expected_positive": expected["pooled_net_return"] > 0,
        "pooled_1_5x_positive": candidates["1.5x"]["pooled_net_return"] > 0,
        "pooled_2x_nonnegative": candidates["2.0x"]["pooled_net_return"] >= 0,
        "annualized_sharpe": expected["statistics"]["annualized_sharpe"]
        >= MINIMUM_ANNUALIZED_SHARPE,
        "psr": expected["statistics"]["psr"] >= MINIMUM_PSR,
        "maximum_drawdown": expected["maximum_window_drawdown"]
        <= MAXIMUM_WINDOW_DRAWDOWN,
        "absolute_beta": abs(beta) <= MAXIMUM_ABS_BETA,
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
        "top_three_week_concentration": top_three
        <= MAXIMUM_TOP_THREE_WEEK_CONCENTRATION,
        "beats_always_long_return": expected["pooled_net_return"]
        > comparator["pooled_net_return"],
        "beats_always_long_sharpe": expected["statistics"]["annualized_sharpe"]
        >= comparator["statistics"]["annualized_sharpe"]
        + MINIMUM_COMPARATOR_SHARPE_ADVANTAGE,
        "drawdown_no_worse_than_always_long": expected["maximum_window_drawdown"]
        <= comparator["maximum_window_drawdown"],
    }
    verdict = "ECONOMIC_PASS" if all(gates.values()) else "ECONOMIC_FAIL"
    observed_candidate = producer.get("candidate", {})
    observed_comparator = producer.get("always_long_perpetual_comparator", {})
    numeric_checks = []
    for label in COST_RATES:
        numeric_checks.extend(
            (
                _close(
                    candidates[label]["pooled_net_return"],
                    observed_candidate.get(label, {}).get("pooled_net_return"),
                ),
                _close(
                    comparators[label]["pooled_net_return"],
                    observed_comparator.get(label, {}).get("pooled_net_return"),
                ),
            )
        )
    checks = {
        "pooled_returns_recomputed": all(numeric_checks),
        "expected_statistics_recomputed": all(
            _close(
                value, observed_candidate.get("1.0x", {}).get("statistics", {}).get(key)
            )
            for key, value in expected["statistics"].items()
        ),
        "beta_recomputed": _close(beta, producer.get("strategy_beta_to_btc")),
        "gates_recomputed": producer.get("gates") == gates,
        "final_verdict_recomputed": producer.get("overall_economic_verdict") == verdict,
    }
    return {
        "schema_version": 1,
        "stage": "C8A_H1_H5_INDEPENDENT_FINAL_RECOMPUTE",
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "reference_gates": gates,
        "reference_final_verdict": verdict,
        "imports_production_replay": False,
        "live_state": "LIVE_FORBIDDEN",
    }
