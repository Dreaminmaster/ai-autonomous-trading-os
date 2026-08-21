"""Frozen C9A W1-W5 clocks and public capture bounds."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from atos.c9a_contract import (
    ALL_TRADE_INSTRUMENTS,
    EXPECTED_DECISIONS_PER_WINDOW,
    HOUR,
    SPOT_INSTRUMENTS,
    SWAP_INSTRUMENTS,
    WEEK,
    C9AError,
    iso,
)


@dataclass(frozen=True)
class HistoricalWindow:
    window_id: str
    start: datetime
    end_exclusive: datetime

    def to_dict(self) -> dict[str, str]:
        row = asdict(self)
        return {
            "window_id": str(row["window_id"]),
            "start": iso(row["start"]),
            "end_exclusive": iso(row["end_exclusive"]),
        }


HISTORICAL_WINDOWS = (
    HistoricalWindow(
        "W1", datetime(2023, 7, 3, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC)
    ),
    HistoricalWindow(
        "W2", datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 7, 1, tzinfo=UTC)
    ),
    HistoricalWindow(
        "W3", datetime(2024, 7, 1, tzinfo=UTC), datetime(2024, 12, 30, tzinfo=UTC)
    ),
    HistoricalWindow(
        "W4", datetime(2024, 12, 30, tzinfo=UTC), datetime(2025, 6, 30, tzinfo=UTC)
    ),
    HistoricalWindow(
        "W5", datetime(2025, 6, 30, tzinfo=UTC), datetime(2025, 12, 29, tzinfo=UTC)
    ),
)
FUNDING_WARMUP_START = datetime(2023, 6, 5, tzinfo=UTC)
PRICE_CUSTODY_START = datetime(2023, 7, 2, 22, tzinfo=UTC)


def window_by_id(window_id: str) -> HistoricalWindow:
    matches = [window for window in HISTORICAL_WINDOWS if window.window_id == window_id]
    if len(matches) != 1:
        raise C9AError(f"unknown C9A window: {window_id!r}")
    return matches[0]


def decision_times(window: HistoricalWindow | str) -> tuple[datetime, ...]:
    selected = window_by_id(window) if isinstance(window, str) else window
    output = []
    current = selected.start
    while current < selected.end_exclusive:
        if current.weekday() != 0 or any(
            (current.hour, current.minute, current.second, current.microsecond)
        ):
            raise C9AError("C9A decisions must be Monday 00:00 UTC")
        output.append(current)
        current += WEEK
    if (
        len(output) != EXPECTED_DECISIONS_PER_WINDOW
        or current != selected.end_exclusive
    ):
        raise C9AError("each C9A window must contain exactly 26 complete weeks")
    return tuple(output)


def w1_w5_capture_plan() -> dict[str, object]:
    end = HISTORICAL_WINDOWS[-1].end_exclusive
    return {
        "window_ids": [window.window_id for window in HISTORICAL_WINDOWS],
        "spot_instruments": list(SPOT_INSTRUMENTS),
        "swap_instruments": list(SWAP_INSTRUMENTS),
        "trade_instruments": list(ALL_TRADE_INSTRUMENTS),
        "funding_start_inclusive": iso(FUNDING_WARMUP_START),
        "funding_end_exclusive": iso(end),
        "mark_start_inclusive": iso(PRICE_CUSTODY_START),
        "mark_end_exclusive": iso(end),
        "trade_start_inclusive": iso(PRICE_CUSTODY_START),
        "trade_end_exclusive": iso(end + HOUR),
        "scored_start_inclusive": iso(HISTORICAL_WINDOWS[0].start),
        "scored_end_exclusive": iso(end),
    }


def validate_historical_windows() -> None:
    previous = None
    for index, window in enumerate(HISTORICAL_WINDOWS, start=1):
        if window.window_id != f"W{index}" or (previous and window.start != previous):
            raise C9AError("C9A historical-window identity or contiguity drift")
        decision_times(window)
        previous = window.end_exclusive


validate_historical_windows()
