from datetime import UTC, datetime, timedelta

import pytest

from atos.c6a_contract import C6AError
from atos.c6a_data import (
    C6AMarket,
    expected_hourly_grid,
    strip_boundary_overshoot,
    validate_mark_candles,
    validate_trade_candles,
)


def trade_rows(start: datetime, count: int, price: str = "100") -> list[dict]:
    return [
        {
            "timestamp": (start + timedelta(hours=index)).isoformat(),
            "open": price,
            "high": "101",
            "low": "99",
            "close": price,
            "quote_volume": "1000",
        }
        for index in range(count)
    ]


def mark_rows(start: datetime, count: int, price: str = "100") -> list[dict]:
    return [
        {
            "timestamp": (start + timedelta(hours=index)).isoformat(),
            "open": price,
            "high": "101",
            "low": "99",
            "close": price,
        }
        for index in range(count)
    ]


def test_small_hourly_grid_is_start_inclusive_end_exclusive() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=3)
    assert expected_hourly_grid(start, end) == (
        start,
        start + timedelta(hours=1),
        start + timedelta(hours=2),
    )


def test_trade_and_mark_candles_require_gap_free_exact_grid() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=3)
    trade = validate_trade_candles(
        trade_rows(start, 3), instrument="BTC-USDT", start=start, end=end
    )
    mark = validate_mark_candles(
        mark_rows(start, 3), instrument="BTC-USDT-SWAP", start=start, end=end
    )
    assert len(trade) == len(mark) == 3

    gapped = trade_rows(start, 3)
    gapped[1]["timestamp"] = (start + timedelta(hours=2)).isoformat()
    with pytest.raises(C6AError, match="timestamp mismatch"):
        validate_trade_candles(gapped, instrument="BTC-USDT", start=start, end=end)


def test_invalid_geometry_and_negative_volume_fail_closed() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    bad = trade_rows(start, 1)
    bad[0]["close"] = "102"
    with pytest.raises(C6AError, match="geometry"):
        validate_trade_candles(bad, instrument="ETH-USDT", start=start, end=end)
    bad = trade_rows(start, 1)
    bad[0]["quote_volume"] = "-1"
    with pytest.raises(C6AError, match="negative"):
        validate_trade_candles(bad, instrument="ETH-USDT", start=start, end=end)


def test_boundary_overshoot_is_removed_and_reported_before_read() -> None:
    boundary = datetime(2024, 1, 2, tzinfo=UTC)
    rows = [
        {"timestamp": "2024-01-01T23:00:00Z"},
        {"timestamp": "2024-01-02T00:00:00Z"},
        {"timestamp": "2024-01-02T01:00:00Z"},
    ]
    retained, report = strip_boundary_overshoot(rows, boundary_exclusive=boundary)
    assert len(retained) == 1
    assert report.removed_rows == 2
    assert report.first_removed_timestamp == boundary


def test_market_alignment_covers_all_six_series() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=2)
    spot = {
        instrument: validate_trade_candles(
            trade_rows(start, 2), instrument=instrument, start=start, end=end
        )
        for instrument in ("BTC-USDT", "ETH-USDT")
    }
    swap = {
        instrument: validate_trade_candles(
            trade_rows(start, 2), instrument=instrument, start=start, end=end
        )
        for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
    }
    mark = {
        instrument: validate_mark_candles(
            mark_rows(start, 2), instrument=instrument, start=start, end=end
        )
        for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP")
    }
    C6AMarket(spot=spot, swap=swap, mark=mark).validate_alignment()

    broken = dict(mark)
    broken["ETH-USDT-SWAP"] = tuple(reversed(broken["ETH-USDT-SWAP"]))
    with pytest.raises(C6AError, match="alignment"):
        C6AMarket(spot=spot, swap=swap, mark=broken).validate_alignment()
