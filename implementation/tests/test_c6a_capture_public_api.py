from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scripts import c6a_capture_public_api as capture


def plan(start: datetime, end: datetime, *, mark: bool = False):
    return capture.CandleApiPlan(
        source_id="btc-series",
        kind="swap_mark_candles" if mark else "spot_trade_candles",
        instrument="BTC-USDT-SWAP" if mark else "BTC-USDT",
        endpoint=capture.MARK_ENDPOINT if mark else capture.TRADE_ENDPOINT,
        start=start,
        end_exclusive=end,
        limit=100,
    )


def response(rows: list[list[str]]) -> io.BytesIO:
    return io.BytesIO(json.dumps({"code": "0", "data": rows}).encode())


def test_paginated_capture_reconstructs_exact_hourly_grid(tmp_path: Path) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=5)
    all_rows = []
    for index in range(5):
        timestamp = int((start + timedelta(hours=index)).timestamp() * 1000)
        all_rows.append(
            [str(timestamp), "100", "100", "100", "100", "1", "1", "1", "1"]
        )
    all_rows.reverse()

    def opener(url: str):
        after = int(parse_qs(urlparse(url).query)["after"][0])
        page = [row for row in all_rows if int(row[0]) < after][:2]
        return response(page)

    destination = tmp_path / "btc.jsonl"
    report = capture.capture_series(
        plan(start, end),
        destination=destination,
        opener=opener,
        sleep=lambda _: None,
    )
    assert report["status"] == "PASS"
    assert report["row_count"] == 5
    assert report["page_count"] == 3
    assert report["authenticated"] is False
    lines = [json.loads(line) for line in destination.read_text().splitlines()]
    assert [row["timestamp"] for row in lines] == [row[0] for row in reversed(all_rows)]
    assert all(
        page["request_url"].startswith(capture.TRADE_ENDPOINT)
        for page in report["pages"]
    )
    assert all(len(page["response_sha256"]) == 64 for page in report["pages"])


def test_mark_capture_uses_only_mark_endpoint_and_exact_schema(tmp_path: Path) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=2)
    rows = [
        [
            str(int((start + timedelta(hours=index)).timestamp() * 1000)),
            "100",
            "100",
            "100",
            "100",
            "1",
        ]
        for index in reversed(range(2))
    ]
    report = capture.capture_series(
        plan(start, end, mark=True),
        destination=tmp_path / "mark.jsonl",
        opener=lambda _: response(rows),
        sleep=lambda _: None,
    )
    assert report["row_count"] == 2
    assert report["pages"][0]["request_url"].startswith(capture.MARK_ENDPOINT)


def test_pagination_conflict_nonadvance_or_gap_fails_closed(tmp_path: Path) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=2)
    timestamp = str(int(start.timestamp() * 1000))

    # A single row at the start finishes on page one; use direct conflicting
    # duplication within the same page to exercise conflict detection.
    with pytest.raises(capture.C6APublicApiCaptureError, match="conflicting duplicate"):
        capture.capture_series(
            plan(start, end),
            destination=tmp_path / "conflict.jsonl",
            opener=lambda _: response(
                [
                    [timestamp, "100", "101", "99", "100", "1", "1", "1", "1"],
                    [timestamp, "100", "101", "99", "101", "1", "1", "1", "1"],
                ]
            ),
            sleep=lambda _: None,
        )

    too_new = str(int(end.timestamp() * 1000))
    with pytest.raises(capture.C6APublicApiCaptureError, match="did not advance"):
        capture.capture_series(
            plan(start, end),
            destination=tmp_path / "nonadvance.jsonl",
            opener=lambda _: response(
                [[too_new, "100", "100", "100", "100", "1", "1", "1", "1"]]
            ),
            sleep=lambda _: None,
        )

    with pytest.raises(
        capture.C6APublicApiCaptureError,
        match="trade-candle count mismatch|coverage mismatch|exact",
    ):
        capture.capture_series(
            plan(start, end),
            destination=tmp_path / "gap.jsonl",
            opener=lambda _: response(
                [[timestamp, "100", "100", "100", "100", "1", "1", "1", "1"]]
            ),
            sleep=lambda _: None,
        )


def test_wrong_endpoint_or_bar_is_rejected() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    with pytest.raises(capture.C6APublicApiCaptureError, match="invalid endpoint"):
        capture.CandleApiPlan(
            source_id="x",
            kind="spot_trade_candles",
            instrument="BTC-USDT",
            endpoint=capture.MARK_ENDPOINT,
            start=start,
            end_exclusive=end,
        ).validate()
    with pytest.raises(capture.C6APublicApiCaptureError, match="bar/limit"):
        capture.CandleApiPlan(
            source_id="x",
            kind="spot_trade_candles",
            instrument="BTC-USDT",
            endpoint=capture.TRADE_ENDPOINT,
            start=start,
            end_exclusive=end,
            bar="4H",
        ).validate()
