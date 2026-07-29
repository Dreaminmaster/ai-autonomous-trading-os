"""Fixed C8A H1-H5 clock and official-public capture bounds."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta

from atos.c8a_contract import EXPECTED_DECISIONS_PER_WINDOW, INSTRUMENTS


class C8AHistoricalScheduleError(RuntimeError):
    """Raised when the frozen C8A time grid drifts."""


@dataclass(frozen=True)
class HistoricalWindow:
    window_id: str
    first_scored_decision: datetime
    end_exclusive: datetime

    def to_dict(self) -> dict[str, str]:
        value = asdict(self)
        return {
            "window_id": str(value["window_id"]),
            "first_scored_decision": iso(value["first_scored_decision"]),
            "end_exclusive": iso(value["end_exclusive"]),
        }


HISTORICAL_WINDOWS = (
    HistoricalWindow(
        "H1", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 7, 1, tzinfo=UTC)
    ),
    HistoricalWindow(
        "H2", datetime(2024, 7, 1, tzinfo=UTC), datetime(2024, 12, 30, tzinfo=UTC)
    ),
    HistoricalWindow(
        "H3", datetime(2024, 12, 30, tzinfo=UTC), datetime(2025, 6, 30, tzinfo=UTC)
    ),
    HistoricalWindow(
        "H4", datetime(2025, 6, 30, tzinfo=UTC), datetime(2025, 12, 29, tzinfo=UTC)
    ),
    HistoricalWindow(
        "H5", datetime(2025, 12, 29, tzinfo=UTC), datetime(2026, 6, 29, tzinfo=UTC)
    ),
)
HOUR = timedelta(hours=1)
WEEK = timedelta(days=7)
MARK_SOURCE_LOOKBACK = timedelta(hours=170)


def iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise C8AHistoricalScheduleError("timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def window_by_id(window_id: str) -> HistoricalWindow:
    found = [window for window in HISTORICAL_WINDOWS if window.window_id == window_id]
    if len(found) != 1:
        raise C8AHistoricalScheduleError(f"unknown historical window: {window_id!r}")
    return found[0]


def decision_times(window: HistoricalWindow | str) -> tuple[datetime, ...]:
    selected = window_by_id(window) if isinstance(window, str) else window
    values: list[datetime] = []
    current = selected.first_scored_decision
    while current < selected.end_exclusive:
        if current.weekday() != 0 or any(
            (current.hour, current.minute, current.second, current.microsecond)
        ):
            raise C8AHistoricalScheduleError("decision grid must be Monday 00:00 UTC")
        values.append(current)
        current += WEEK
    if (
        len(values) != EXPECTED_DECISIONS_PER_WINDOW
        or current != selected.end_exclusive
    ):
        raise C8AHistoricalScheduleError(
            "each C8A window requires exactly 26 complete weeks"
        )
    return tuple(values)


def h1_h5_capture_plan() -> dict[str, object]:
    first = HISTORICAL_WINDOWS[0].first_scored_decision
    end = HISTORICAL_WINDOWS[-1].end_exclusive
    return {
        "window_ids": [window.window_id for window in HISTORICAL_WINDOWS],
        "instruments": list(INSTRUMENTS),
        "mark_start_inclusive": iso(first - MARK_SOURCE_LOOKBACK),
        "mark_end_exclusive": iso(end),
        "trade_start_inclusive": iso(first),
        "trade_end_exclusive": iso(end + HOUR),
        "funding_start_inclusive": iso(first),
        "funding_end_exclusive": iso(end + HOUR),
        "scored_start_inclusive": iso(first),
        "scored_end_exclusive": iso(end),
    }


def validate_historical_windows() -> None:
    if [window.window_id for window in HISTORICAL_WINDOWS] != [
        "H1",
        "H2",
        "H3",
        "H4",
        "H5",
    ]:
        raise C8AHistoricalScheduleError("C8A historical window identity drift")
    previous = None
    for window in HISTORICAL_WINDOWS:
        decision_times(window)
        if previous is not None and window.first_scored_decision != previous:
            raise C8AHistoricalScheduleError("C8A windows must be contiguous")
        previous = window.end_exclusive


validate_historical_windows()
