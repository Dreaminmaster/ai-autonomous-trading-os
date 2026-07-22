from __future__ import annotations

import base64
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from scripts import c6a_capture_public_api as base
from scripts import c6a_capture_public_api_authoritative as authoritative


def plan(start: datetime, end: datetime) -> base.CandleApiPlan:
    return base.CandleApiPlan(
        source_id="btc-spot",
        kind="spot_trade_candles",
        instrument="BTC-USDT",
        endpoint=base.TRADE_ENDPOINT,
        start=start,
        end_exclusive=end,
        limit=100,
    )


def test_authoritative_api_capture_retains_every_exact_response(
    tmp_path: Path,
) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=3)
    rows = [
        [
            str(int((start + timedelta(hours=index)).timestamp() * 1000)),
            "100",
            "100",
            "100",
            "100",
            "1",
            "1",
            "1",
            "1",
        ]
        for index in reversed(range(3))
    ]
    raw_by_url: dict[str, bytes] = {}

    def opener(url: str):
        after = int(parse_qs(urlparse(url).query)["after"][0])
        page = [row for row in rows if int(row[0]) < after][:2]
        raw = json.dumps({"code": "0", "data": page}, separators=(",", ":")).encode()
        raw_by_url[url] = raw
        return io.BytesIO(raw)

    destination = tmp_path / "series.jsonl"
    transcript = tmp_path / "raw-pages.jsonl"
    report = authoritative.capture_series_with_raw_transcript(
        plan(start, end),
        destination=destination,
        transcript_path=transcript,
        network_opener=opener,
        sleep=lambda _: None,
    )
    assert report["status"] == "PASS"
    assert report["raw_response_bytes_retained"] is True
    assert report["raw_transcript_page_count"] == report["page_count"] == 2
    transcript_rows = [
        json.loads(line) for line in transcript.read_text(encoding="utf-8").splitlines()
    ]
    assert len(transcript_rows) == 2
    for row in transcript_rows:
        assert base64.b64decode(row["response_base64"]) == raw_by_url[
            row["request_url"]
        ]
        assert len(row["response_sha256"]) == 64
    assert report["raw_transcript_size"] == transcript.stat().st_size
    assert len(report["raw_transcript_sha256"]) == 64


def test_authoritative_api_capture_rolls_back_transcript_and_series_on_mismatch(
    tmp_path: Path, monkeypatch
) -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(hours=1)
    destination = tmp_path / "series.jsonl"
    transcript = tmp_path / "raw.jsonl"

    def fake_capture(plan, *, destination, opener, sleep):
        with opener("https://www.okx.com/api/v5/market/history-candles?x=1") as response:
            response.read()
        destination.write_text("{}\n", encoding="utf-8")
        return {
            "status": "PASS",
            "pages": [],
        }

    monkeypatch.setattr(authoritative.base, "capture_series", fake_capture)
    with pytest.raises(
        authoritative.C6AAuthoritativeApiCaptureError,
        match="count mismatch",
    ):
        authoritative.capture_series_with_raw_transcript(
            plan(start, end),
            destination=destination,
            transcript_path=transcript,
            network_opener=lambda _: io.BytesIO(b'{"code":"0","data":[]}'),
            sleep=lambda _: None,
        )
    assert not destination.exists()
    assert not transcript.exists()
