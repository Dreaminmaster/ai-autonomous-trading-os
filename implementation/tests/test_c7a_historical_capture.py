from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse, urlunparse

import pytest

from atos.c7a_historical_capture import (
    C7AHistoricalCaptureError,
    CapturePackage,
    CaptureRecord,
    FundingDownloadSpec,
    capture_funding_downloads,
    capture_mark_range,
    fetch_raw_strict,
    h1_h5_capture_plan,
)
from atos.c7a_okx_public_data import build_mark_price_request

BTC = "BTC-USDT-SWAP"
ETH = "ETH-USDT-SWAP"
T0 = 1_704_067_200_000
HOUR = 3_600_000
EXACT_SHA = "a" * 40


def _mark_row(ts: int, close: str) -> list[str]:
    value = int(close)
    return [str(ts), str(value), str(value + 1), str(value - 1), close, "1"]


def _record(request, raw: bytes, *, final_url: str | None = None) -> CaptureRecord:
    return CaptureRecord(
        request_id=request.request_id,
        source_family=request.source_family,
        requested_url=request.url,
        final_url=final_url or request.url,
        collected_at="2026-07-28T00:00:00Z",
        media_type=(
            "application/json"
            if request.source_family.endswith("_API")
            else "text/csv"
        ),
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        relative_path="",
    )


class _Response:
    def __init__(
        self,
        raw: bytes,
        *,
        final_url: str,
        content_type: str = "application/json",
        status: int = 200,
    ):
        self.raw = raw
        self.final_url = final_url
        self.headers = {"Content-Type": content_type}
        self.status = status
        self.closed = False

    def read(self, limit: int) -> bytes:
        return self.raw[:limit]

    def geturl(self) -> str:
        return self.final_url

    def close(self) -> None:
        self.closed = True


def test_strict_fetch_records_official_host_redirect_without_semantic_drift() -> None:
    request = build_mark_price_request(BTC, after_ms=T0)
    parsed = urlparse(request.url)
    final_url = urlunparse(parsed._replace(netloc="us.okx.com"))
    raw = b'{"code":"0","msg":"","data":[]}'

    response = _Response(raw, final_url=final_url)
    fetched, record = fetch_raw_strict(
        request,
        opener=lambda *_args, **_kwargs: response,
        collected_at=datetime(2026, 7, 28, tzinfo=UTC),
    )
    assert fetched == raw
    assert record.requested_url == request.url
    assert record.final_url == final_url
    assert record.sha256 == hashlib.sha256(raw).hexdigest()
    assert response.closed is True


def test_strict_fetch_rejects_api_redirect_query_or_path_drift() -> None:
    request = build_mark_price_request(BTC, after_ms=T0)
    parsed = urlparse(request.url)
    changed_query = parsed.query.replace("limit=100", "limit=99")
    drifted = urlunparse(parsed._replace(query=changed_query))
    with pytest.raises(C7AHistoricalCaptureError):
        fetch_raw_strict(
            request,
            opener=lambda *_args, **_kwargs: _Response(
                b'{"code":"0","data":[]}',
                final_url=drifted,
            ),
        )


def test_capture_package_is_no_overwrite_and_manifested(tmp_path) -> None:
    package = CapturePackage(tmp_path / "capture")
    request = build_mark_price_request(BTC, after_ms=T0)
    raw = b'{"code":"0","data":[]}'
    retained = package.retain_raw(raw, _record(request, raw))
    assert retained.relative_path.endswith(".bin")

    with pytest.raises(C7AHistoricalCaptureError, match="duplicate capture request"):
        package.retain_raw(raw, _record(request, raw))
    with pytest.raises(C7AHistoricalCaptureError, match="inside package"):
        package.write_json("../escape.json", {})

    manifest = package.finalize(
        implementation_sha=EXACT_SHA,
        capture_plan={"window_ids": ["H1"]},
    )
    assert manifest["stage"] == "C7A_HISTORICAL_CAPTURE_PACKAGE"
    assert manifest["file_count"] == 2
    assert (tmp_path / "capture" / "capture_index.json").is_file()
    assert (tmp_path / "capture" / "manifest.json").is_file()
    with pytest.raises(C7AHistoricalCaptureError, match="finalized"):
        package.write_json("late.json", {})


def test_h1_h5_capture_plan_is_exact_and_pooled() -> None:
    assert h1_h5_capture_plan() == {
        "window_ids": ["H1", "H2", "H3", "H4", "H5"],
        "instruments": [BTC, ETH],
        "funding_start_inclusive": "2023-12-04T00:00:00Z",
        "mark_start_inclusive": "2023-12-03T23:00:00Z",
        "scored_end_exclusive": "2026-06-29T00:00:00Z",
    }


def test_mark_capture_paginates_strictly_backward_and_selects_every_hour(
    tmp_path,
) -> None:
    package = CapturePackage(tmp_path / "marks")
    pages = {
        T0 + 4 * HOUR: [
            _mark_row(T0 + 3 * HOUR, "103"),
            _mark_row(T0 + 2 * HOUR, "102"),
        ],
        T0 + 2 * HOUR: [
            _mark_row(T0 + HOUR, "101"),
            _mark_row(T0, "100"),
        ],
    }

    def fetch_page(request):
        cursor = int(parse_qs(urlparse(request.url).query)["after"][0])
        raw = json.dumps({"code": "0", "msg": "", "data": pages[cursor]}).encode()
        return raw, _record(request, raw)

    selected = capture_mark_range(
        package,
        instrument=BTC,
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-01-01T04:00:00Z",
        fetch_page=fetch_page,
        max_pages=2,
    )
    assert [row["close"] for row in selected] == ["100", "101", "102", "103"]
    assert len(package.records) == 2
    assert (tmp_path / "marks" / "normalized" / "marks" / f"{BTC}.json").is_file()


def test_mark_capture_rejects_no_progress_and_transport_provenance_drift(
    tmp_path,
) -> None:
    package = CapturePackage(tmp_path / "bad-marks")

    def no_progress(request):
        cursor = int(parse_qs(urlparse(request.url).query)["after"][0])
        raw = json.dumps(
            {"code": "0", "data": [_mark_row(cursor, "100")]}
        ).encode()
        return raw, _record(request, raw)

    with pytest.raises(C7AHistoricalCaptureError, match="strictly older"):
        capture_mark_range(
            package,
            instrument=BTC,
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-01-01T01:00:00Z",
            fetch_page=no_progress,
        )

    package2 = CapturePackage(tmp_path / "bad-provenance")

    def wrong_request(request):
        raw = json.dumps(
            {"code": "0", "data": [_mark_row(T0, "100")]}
        ).encode()
        other = build_mark_price_request(ETH, after_ms=T0 + HOUR)
        return raw, _record(other, raw)

    with pytest.raises(C7AHistoricalCaptureError, match="issued request"):
        capture_mark_range(
            package2,
            instrument=BTC,
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-01-01T01:00:00Z",
            fetch_page=wrong_request,
        )


def test_funding_download_capture_requires_both_instruments_and_exact_interval(
    tmp_path,
) -> None:
    package = CapturePackage(tmp_path / "funding")
    specs = [
        FundingDownloadSpec(
            request_id="btc-funding-h1",
            instrument=BTC,
            url="https://static.okx.com/cdn/history/btc-funding.csv",
            column_map={
                "instrument": "inst",
                "funding_time": "ts",
                "realized_rate": "rate",
            },
        ),
        FundingDownloadSpec(
            request_id="eth-funding-h1",
            instrument=ETH,
            url="https://static.okx.com/cdn/history/eth-funding.csv",
            column_map={
                "instrument": "inst",
                "funding_time": "ts",
                "realized_rate": "rate",
            },
        ),
    ]
    raw_by_id = {
        "btc-funding-h1": f"inst,ts,rate\n{BTC},{T0},0.0001\n".encode(),
        "eth-funding-h1": f"inst,ts,rate\n{ETH},{T0},-0.0002\n".encode(),
    }

    def fetch_object(request):
        raw = raw_by_id[request.request_id]
        return raw, _record(request, raw)

    result = capture_funding_downloads(
        package,
        specs=specs,
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-01-02T00:00:00Z",
        fetch_object=fetch_object,
    )
    assert result[BTC][0]["realized_rate"] == "0.0001"
    assert result[ETH][0]["realized_rate"] == "-0.0002"
    assert len(package.records) == 2


def test_funding_download_capture_rejects_duplicate_settlement_across_files(
    tmp_path,
) -> None:
    package = CapturePackage(tmp_path / "duplicate-funding")
    specs = [
        FundingDownloadSpec(
            request_id="btc-a",
            instrument=BTC,
            url="https://static.okx.com/cdn/history/btc-a.csv",
            column_map={"instrument": "inst", "funding_time": "ts", "realized_rate": "rate"},
        ),
        FundingDownloadSpec(
            request_id="btc-b",
            instrument=BTC,
            url="https://static.okx.com/cdn/history/btc-b.csv",
            column_map={"instrument": "inst", "funding_time": "ts", "realized_rate": "rate"},
        ),
        FundingDownloadSpec(
            request_id="eth-a",
            instrument=ETH,
            url="https://static.okx.com/cdn/history/eth-a.csv",
            column_map={"instrument": "inst", "funding_time": "ts", "realized_rate": "rate"},
        ),
    ]

    def fetch_object(request):
        instrument = ETH if request.request_id == "eth-a" else BTC
        raw = f"inst,ts,rate\n{instrument},{T0},0.0001\n".encode()
        return raw, _record(request, raw)

    with pytest.raises(C7AHistoricalCaptureError, match="duplicate funding settlement"):
        capture_funding_downloads(
            package,
            specs=specs,
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-01-02T00:00:00Z",
            fetch_object=fetch_object,
        )
