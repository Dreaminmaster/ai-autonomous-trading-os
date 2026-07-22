"""Primitive public-market data validation for C6A.

The validator is deliberately independent of candidate selection and economic
metrics.  It accepts already-downloaded public rows only.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Mapping, Sequence

from atos.c6a_contract import (
    C6AError,
    ECONOMIC_BOUNDARY,
    SPOT_INSTRUMENTS,
    SWAP_INSTRUMENTS,
    decimal_value,
    parse_timestamp,
)

DOWNLOAD_START = datetime(2023, 6, 5, tzinfo=UTC)
ONE_HOUR = timedelta(hours=1)
EXPECTED_HOURLY_ROWS = 22_512


@dataclass(frozen=True)
class TradeCandle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    quote_volume: Decimal


@dataclass(frozen=True)
class MarkCandle:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal


@dataclass(frozen=True)
class BoundaryReport:
    boundary_exclusive: datetime
    retained_rows: int
    removed_rows: int
    first_removed_timestamp: datetime | None
    last_removed_timestamp: datetime | None


def expected_hourly_grid(
    start: datetime = DOWNLOAD_START,
    end: datetime = ECONOMIC_BOUNDARY,
) -> tuple[datetime, ...]:
    start = parse_timestamp(start)
    end = parse_timestamp(end)
    if start.minute or start.second or start.microsecond or end.minute or end.second or end.microsecond:
        raise C6AError("hourly grid boundaries must be hour-aligned")
    if end <= start:
        raise C6AError("hourly grid end must follow start")
    count = int((end - start) / ONE_HOUR)
    values = tuple(start + index * ONE_HOUR for index in range(count))
    if values[-1] != end - ONE_HOUR:
        raise C6AError("internal hourly grid mismatch")
    if start == DOWNLOAD_START and end == ECONOMIC_BOUNDARY and len(values) != EXPECTED_HOURLY_ROWS:
        raise C6AError("frozen C6A hourly row count mismatch")
    return values


def _timestamp(row: Mapping[str, Any]) -> datetime:
    for key in ("timestamp", "date", "ts", "open_time"):
        if key in row:
            return parse_timestamp(row[key])
    raise C6AError("candle timestamp field missing")


def strip_boundary_overshoot(
    rows: Sequence[Mapping[str, Any]],
    *,
    boundary_exclusive: datetime = ECONOMIC_BOUNDARY,
) -> tuple[tuple[Mapping[str, Any], ...], BoundaryReport]:
    boundary = parse_timestamp(boundary_exclusive)
    retained: list[Mapping[str, Any]] = []
    removed_times: list[datetime] = []
    for row in rows:
        timestamp = _timestamp(row)
        if timestamp < boundary:
            retained.append(row)
        else:
            removed_times.append(timestamp)
    if removed_times and removed_times != sorted(removed_times):
        raise C6AError("overshoot rows are not ordered")
    return tuple(retained), BoundaryReport(
        boundary_exclusive=boundary,
        retained_rows=len(retained),
        removed_rows=len(removed_times),
        first_removed_timestamp=removed_times[0] if removed_times else None,
        last_removed_timestamp=removed_times[-1] if removed_times else None,
    )


def _validate_geometry(
    *, open_price: Decimal, high: Decimal, low: Decimal, close: Decimal, label: str
) -> None:
    if min(open_price, high, low, close) <= 0:
        raise C6AError(f"non-positive price in {label}")
    if low > high or not (low <= open_price <= high) or not (low <= close <= high):
        raise C6AError(f"invalid OHLC geometry in {label}")


def validate_trade_candles(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    start: datetime = DOWNLOAD_START,
    end: datetime = ECONOMIC_BOUNDARY,
) -> tuple[TradeCandle, ...]:
    if instrument not in (*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS):
        raise C6AError(f"unexpected trade-candle instrument: {instrument}")
    expected = expected_hourly_grid(start, end)
    if len(rows) != len(expected):
        raise C6AError(f"{instrument} trade-candle count mismatch: {len(rows)} != {len(expected)}")
    output: list[TradeCandle] = []
    for index, row in enumerate(rows):
        timestamp = _timestamp(row)
        if timestamp != expected[index]:
            raise C6AError(f"{instrument} trade-candle timestamp mismatch at row {index}")
        open_price = decimal_value(row.get("open", row.get("o")), "open")
        high = decimal_value(row.get("high", row.get("h")), "high")
        low = decimal_value(row.get("low", row.get("l")), "low")
        close = decimal_value(row.get("close", row.get("c")), "close")
        quote_volume = decimal_value(
            row.get("quote_volume", row.get("quoteVolume", row.get("volCcyQuote", "0"))),
            "quote volume",
        )
        _validate_geometry(
            open_price=open_price, high=high, low=low, close=close,
            label=f"{instrument}@{timestamp.isoformat()}",
        )
        if quote_volume < 0:
            raise C6AError(f"negative quote volume in {instrument}@{timestamp.isoformat()}")
        output.append(
            TradeCandle(timestamp, open_price, high, low, close, quote_volume)
        )
    return tuple(output)


def validate_mark_candles(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    start: datetime = DOWNLOAD_START,
    end: datetime = ECONOMIC_BOUNDARY,
) -> tuple[MarkCandle, ...]:
    if instrument not in SWAP_INSTRUMENTS:
        raise C6AError(f"unexpected mark-candle instrument: {instrument}")
    expected = expected_hourly_grid(start, end)
    if len(rows) != len(expected):
        raise C6AError(f"{instrument} mark-candle count mismatch: {len(rows)} != {len(expected)}")
    output: list[MarkCandle] = []
    for index, row in enumerate(rows):
        timestamp = _timestamp(row)
        if timestamp != expected[index]:
            raise C6AError(f"{instrument} mark-candle timestamp mismatch at row {index}")
        open_price = decimal_value(row.get("open", row.get("o")), "mark open")
        high = decimal_value(row.get("high", row.get("h")), "mark high")
        low = decimal_value(row.get("low", row.get("l")), "mark low")
        close = decimal_value(row.get("close", row.get("c")), "mark close")
        _validate_geometry(
            open_price=open_price, high=high, low=low, close=close,
            label=f"mark:{instrument}@{timestamp.isoformat()}",
        )
        output.append(MarkCandle(timestamp, open_price, high, low, close))
    return tuple(output)


@dataclass(frozen=True)
class C6AMarket:
    spot: Mapping[str, tuple[TradeCandle, ...]]
    swap: Mapping[str, tuple[TradeCandle, ...]]
    mark: Mapping[str, tuple[MarkCandle, ...]]

    def validate_alignment(self) -> None:
        if set(self.spot) != set(SPOT_INSTRUMENTS):
            raise C6AError("C6A spot dataset set mismatch")
        if set(self.swap) != set(SWAP_INSTRUMENTS):
            raise C6AError("C6A swap dataset set mismatch")
        if set(self.mark) != set(SWAP_INSTRUMENTS):
            raise C6AError("C6A mark dataset set mismatch")
        reference = tuple(row.timestamp for row in self.spot[SPOT_INSTRUMENTS[0]])
        if not reference:
            raise C6AError("empty C6A market")
        for label, series in (
            *((f"spot:{key}", value) for key, value in self.spot.items()),
            *((f"swap:{key}", value) for key, value in self.swap.items()),
            *((f"mark:{key}", value) for key, value in self.mark.items()),
        ):
            if tuple(row.timestamp for row in series) != reference:
                raise C6AError(f"C6A timestamp alignment mismatch: {label}")
