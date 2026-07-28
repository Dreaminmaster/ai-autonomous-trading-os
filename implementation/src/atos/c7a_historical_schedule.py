"""Fixed, immediate C7A historical-validation schedule and public-data boundary.

This module authorizes no account access, private API, order submission, paper side
effect, or live execution. It only defines deterministic historical replay windows
and validates metadata for unauthenticated official OKX public data.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping


class C7AHistoricalScheduleError(RuntimeError):
    """Raised when the fixed historical-validation contract is violated."""


@dataclass(frozen=True)
class HistoricalWindow:
    window_id: str
    first_scored_decision: datetime
    end_exclusive: datetime

    def to_dict(self) -> dict[str, str]:
        payload = asdict(self)
        return {
            "window_id": str(payload["window_id"]),
            "first_scored_decision": _iso(payload["first_scored_decision"]),
            "end_exclusive": _iso(payload["end_exclusive"]),
        }


HISTORICAL_WINDOWS = (
    HistoricalWindow(
        "H1",
        datetime(2024, 1, 1, 0, tzinfo=UTC),
        datetime(2024, 7, 1, 0, tzinfo=UTC),
    ),
    HistoricalWindow(
        "H2",
        datetime(2024, 7, 1, 0, tzinfo=UTC),
        datetime(2024, 12, 30, 0, tzinfo=UTC),
    ),
    HistoricalWindow(
        "H3",
        datetime(2024, 12, 30, 0, tzinfo=UTC),
        datetime(2025, 6, 30, 0, tzinfo=UTC),
    ),
    HistoricalWindow(
        "H4",
        datetime(2025, 6, 30, 0, tzinfo=UTC),
        datetime(2025, 12, 29, 0, tzinfo=UTC),
    ),
    HistoricalWindow(
        "H5",
        datetime(2025, 12, 29, 0, tzinfo=UTC),
        datetime(2026, 6, 29, 0, tzinfo=UTC),
    ),
)

PROSPECTIVE_FIRST_SCORED_DECISION = datetime(2026, 8, 24, 0, tzinfo=UTC)
FUNDING_LOOKBACK = timedelta(days=28)
INITIAL_MARK_LOOKBACK = timedelta(hours=673)
WEEK = timedelta(days=7)
EXPECTED_DECISIONS = 26

OFFICIAL_PUBLIC_SOURCE_FAMILIES = (
    "OKX_HISTORICAL_DOWNLOAD",
    "OKX_HISTORY_CANDLES_API",
    "OKX_HISTORY_MARK_PRICE_CANDLES_API",
    "OKX_FUNDING_RATE_HISTORY_API",
)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _utc(value: Any, label: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError as exc:
            raise C7AHistoricalScheduleError(f"invalid {label}: {value!r}") from exc
    else:
        raise C7AHistoricalScheduleError(f"invalid {label}: {value!r}")
    if parsed.tzinfo is None:
        raise C7AHistoricalScheduleError(f"{label} must be timezone-aware")
    return parsed.astimezone(UTC)


def decision_times(window: HistoricalWindow | str) -> tuple[datetime, ...]:
    selected = window_by_id(window) if isinstance(window, str) else window
    values: list[datetime] = []
    current = selected.first_scored_decision
    while current < selected.end_exclusive:
        if current.weekday() != 0 or any(
            (current.hour, current.minute, current.second, current.microsecond)
        ):
            raise C7AHistoricalScheduleError(
                f"{selected.window_id} decision grid must be Monday 00:00 UTC"
            )
        values.append(current)
        current += WEEK
    if len(values) != EXPECTED_DECISIONS:
        raise C7AHistoricalScheduleError(
            f"{selected.window_id} must contain exactly {EXPECTED_DECISIONS} decisions"
        )
    if values[-1] + WEEK != selected.end_exclusive:
        raise C7AHistoricalScheduleError(
            f"{selected.window_id} end boundary is not one week after final decision"
        )
    return tuple(values)


def required_source_bounds(window: HistoricalWindow | str) -> dict[str, str]:
    selected = window_by_id(window) if isinstance(window, str) else window
    decision_times(selected)
    return {
        "window_id": selected.window_id,
        "funding_start_inclusive": _iso(
            selected.first_scored_decision - FUNDING_LOOKBACK
        ),
        "mark_start_inclusive": _iso(
            selected.first_scored_decision - INITIAL_MARK_LOOKBACK
        ),
        "scored_start_inclusive": _iso(selected.first_scored_decision),
        "scored_end_exclusive": _iso(selected.end_exclusive),
    }


def window_by_id(window_id: str) -> HistoricalWindow:
    matches = [window for window in HISTORICAL_WINDOWS if window.window_id == window_id]
    if len(matches) != 1:
        raise C7AHistoricalScheduleError(f"unknown historical window: {window_id!r}")
    return matches[0]


def validate_historical_windows() -> None:
    if len(HISTORICAL_WINDOWS) != 5:
        raise C7AHistoricalScheduleError("exactly five historical windows are required")
    identifiers = [window.window_id for window in HISTORICAL_WINDOWS]
    if identifiers != ["H1", "H2", "H3", "H4", "H5"]:
        raise C7AHistoricalScheduleError("historical window identity drift")
    previous_end: datetime | None = None
    for window in HISTORICAL_WINDOWS:
        if window.first_scored_decision.tzinfo is None or window.end_exclusive.tzinfo is None:
            raise C7AHistoricalScheduleError("historical window timestamps require UTC")
        if window.first_scored_decision >= window.end_exclusive:
            raise C7AHistoricalScheduleError("historical window must be positive")
        decision_times(window)
        if previous_end is not None and window.first_scored_decision != previous_end:
            raise C7AHistoricalScheduleError(
                "historical windows must be contiguous and non-overlapping"
            )
        previous_end = window.end_exclusive
    if HISTORICAL_WINDOWS[-1].end_exclusive >= PROSPECTIVE_FIRST_SCORED_DECISION:
        raise C7AHistoricalScheduleError(
            "historical windows must end before the prospective confirmation window"
        )


def assert_official_public_metadata(metadata: Mapping[str, Any]) -> None:
    expected = {
        "stage": "C7A_HISTORICAL_VALIDATION",
        "source_kind": "OFFICIAL_PUBLIC_OKX",
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "private_api": False,
        "paper_side_effect": False,
        "live_state": "LIVE_FORBIDDEN",
    }
    for key, value in expected.items():
        if metadata.get(key) != value:
            raise C7AHistoricalScheduleError(
                f"historical public-data boundary violation: {key}"
            )
    source_family = metadata.get("source_family")
    if source_family not in OFFICIAL_PUBLIC_SOURCE_FAMILIES:
        raise C7AHistoricalScheduleError(
            f"unapproved historical source family: {source_family!r}"
        )
    collected_at = _utc(metadata.get("collected_at"), "collected_at")
    if collected_at > datetime.now(tz=UTC) + timedelta(minutes=5):
        raise C7AHistoricalScheduleError("collected_at is implausibly in the future")


validate_historical_windows()
