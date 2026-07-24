"""Frozen C7A design constants and synthetic-only validation primitives.

This module contains no network, exchange-account, order, paper, shadow, or live path.
Real C7A data and economic execution remain unauthorized until a later exact-SHA gate.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Sequence

INSTRUMENTS = ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
CANDIDATE_ID = "C7ABetaNeutralFundingDispersion"
COMPARATORS = ("cash", "always_on_funding_rank", "equal_notional_funding_rank")
MARK_SEED_START = datetime(2026, 7, 26, 23, tzinfo=UTC)
DATA_START = datetime(2026, 7, 27, tzinfo=UTC)
FIRST_SCORED_DECISION = datetime(2026, 8, 24, tzinfo=UTC)
SCORED_END_EXCLUSIVE = datetime(2027, 2, 22, tzinfo=UTC)
C7B_END_EXCLUSIVE = datetime(2027, 8, 23, tzinfo=UTC)
LOOKBACK_HOURS = 672
MARK_CLOSE_COUNT = 673
MINIMUM_BETA = 0.50
MAXIMUM_BETA = 2.00
MINIMUM_R_SQUARED = 0.50
MAXIMUM_GROSS_NOTIONAL = 0.50
MINIMUM_PROJECTED_CARRY_28D = 0.00225
MINIMUM_POSITIVE_DAYS = 19
RESIZE_BAND = 0.10
ONE_SIDE_COSTS = {"1.0x": 0.0015, "1.5x": 0.00225, "2.0x": 0.0030}
EXPECTED_CONFIG_CANONICAL_SHA256 = "89072722f3598262660b02f1b34d35fbc8f3460f235bd897784f7ed259484a2c"


class C7AError(RuntimeError):
    """Raised when a frozen C7A invariant fails."""


def timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise C7AError(f"invalid timestamp: {value!r}") from exc
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        raw = float(value)
        parsed = datetime.fromtimestamp(raw / (1000 if raw > 10_000_000_000 else 1), tz=UTC)
    else:
        raise C7AError(f"invalid timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def finite(value: Any, label: str) -> float:
    if value is None or isinstance(value, bool):
        raise C7AError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C7AError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise C7AError(f"{label} must be finite")
    return result


def canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_config(config: Mapping[str, Any]) -> None:
    if canonical_sha256(config) != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C7AError("C7A semantic configuration drift")
    expected = {
        "schema_version": 1,
        "stage": "C7A",
        "change_type": "IMPLEMENTATION_ONLY_SYNTHETIC",
        "required_design_main_sha": "f77d9138c2f14ff1371b541ea47861254cdb44f0",
        "candidate_id": CANDIDATE_ID,
        "instruments": list(INSTRUMENTS),
        "comparators": list(COMPARATORS),
        "mark_seed_start": "2026-07-26T23:00:00Z",
        "data_start": "2026-07-27T00:00:00Z",
        "first_scored_decision": "2026-08-24T00:00:00Z",
        "scored_end_exclusive": "2027-02-22T00:00:00Z",
        "c7b_end_exclusive": "2027-08-23T00:00:00Z",
        "lookback_hours": LOOKBACK_HOURS,
        "mark_close_count": MARK_CLOSE_COUNT,
        "minimum_beta": MINIMUM_BETA,
        "maximum_beta": MAXIMUM_BETA,
        "minimum_r_squared": MINIMUM_R_SQUARED,
        "maximum_gross_notional": MAXIMUM_GROSS_NOTIONAL,
        "minimum_projected_carry_28d": MINIMUM_PROJECTED_CARRY_28D,
        "minimum_positive_days": MINIMUM_POSITIVE_DAYS,
        "resize_band": RESIZE_BAND,
        "one_side_costs": ONE_SIDE_COSTS,
        "real_data_authorized": False,
        "network_execution_authorized": False,
        "economic_run_authorized": False,
        "c7b_state": "CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    for key, expected_value in expected.items():
        if config.get(key) != expected_value:
            raise C7AError(f"C7A config drift: {key}")


def assert_synthetic_only(metadata: Mapping[str, Any]) -> None:
    expected = {
        "stage": "C7A",
        "source_kind": "SYNTHETIC",
        "contains_real_market_rows": False,
        "network_access": False,
        "economic_run": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise C7AError(f"synthetic-only boundary violation: {key}")


def scored_decision_times() -> tuple[datetime, ...]:
    values: list[datetime] = []
    current = FIRST_SCORED_DECISION
    while current < SCORED_END_EXCLUSIVE:
        if current.weekday() != 0 or current.hour != 0 or current.minute != 0:
            raise C7AError("C7A decision grid is not Monday 00 UTC")
        values.append(current)
        current += timedelta(days=7)
    if len(values) != 26 or values[-1] != SCORED_END_EXCLUSIVE - timedelta(days=7):
        raise C7AError("C7A scored decision grid mismatch")
    return tuple(values)


def validate_scored_decision(value: Any) -> datetime:
    decision = timestamp(value)
    if decision not in scored_decision_times():
        raise C7AError("decision is outside the frozen C7A scored grid")
    return decision


def _strict_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    timestamp_field: str,
    value_field: str,
    label: str,
) -> tuple[tuple[datetime, ...], tuple[float, ...]]:
    if not rows:
        raise C7AError(f"empty series: {label}")
    times = tuple(timestamp(row.get(timestamp_field)) for row in rows)
    if times != tuple(sorted(times)) or len(set(times)) != len(times):
        raise C7AError(f"unordered or duplicate timestamps: {label}")
    values = tuple(finite(row.get(value_field), f"{label} {value_field}") for row in rows)
    return times, values


def aligned_mark_returns(
    rows: Sequence[Mapping[str, Any]], *, decision_time: Any, label: str
) -> tuple[float, ...]:
    decision = validate_scored_decision(decision_time)
    times, closes = _strict_rows(
        rows,
        timestamp_field="timestamp",
        value_field="close",
        label=label,
    )
    expected_times = tuple(
        decision - timedelta(hours=MARK_CLOSE_COUNT - index)
        for index in range(MARK_CLOSE_COUNT)
    )
    if times != expected_times:
        raise C7AError(f"exact 673-close alignment mismatch: {label}")
    if any(value <= 0 for value in closes):
        raise C7AError(f"non-positive mark close: {label}")
    returns = tuple(
        math.log(closes[index] / closes[index - 1])
        for index in range(1, len(closes))
    )
    if len(returns) != LOOKBACK_HOURS or not all(
        math.isfinite(value) for value in returns
    ):
        raise C7AError(f"exact 672-return alignment mismatch: {label}")
    return returns


def funding_daily_sums(
    rows: Sequence[Mapping[str, Any]], *, decision_time: Any, label: str
) -> tuple[float, tuple[float, ...]]:
    decision = validate_scored_decision(decision_time)
    times, rates = _strict_rows(
        rows,
        timestamp_field="funding_time",
        value_field="realized_rate",
        label=label,
    )
    start = decision - timedelta(days=28)
    if times[0] < start or times[-1] >= decision:
        raise C7AError(f"funding row outside exact lookback: {label}")
    expected_dates = tuple((start + timedelta(days=index)).date() for index in range(28))
    by_date = {day: [] for day in expected_dates}
    for current, rate in zip(times, rates, strict=True):
        if current.date() not in by_date:
            raise C7AError(f"funding date outside exact lookback: {label}")
        by_date[current.date()].append(rate)
    if any(not by_date[day] for day in expected_dates):
        raise C7AError(f"missing daily funding evidence: {label}")
    daily = tuple(sum(by_date[day]) for day in expected_dates)
    return sum(daily), daily
