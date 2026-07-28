from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse, urlunparse

import pytest

from atos.c7a_historical_capture import (
    C7AHistoricalCaptureError,
    CapturePackage,
    CaptureRecord,
    FundingDownloadSpec,
    capture_funding_downloads,
    capture_historical_funding_range,
    capture_mark_range,
    capture_trade_range,
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


def _trade_row(ts: int, close: str) -> list[str]:
    value = int(close)
    return [
        str(ts),
        str(value),
        str(value + 1),
        str(value - 1),
        close,
        "1",
        "1",
        close,
        "1",
    ]


def _record(request, raw: bytes, *, final_url: str | None = None) -> CaptureRecord:
    return CaptureRecord(
        request_id=request.request_id,
        source_family=request.source_family,
        requested_url=request.url,
        final_url=final_url or request.url,
        collected_at="2026-07-28T00:00:00Z",
        media_type=(
            "application/json" if request.source_family.endswith("_API") else "text/csv"
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

    capture_plan = {
        "window_ids": ["TEST"],
        "instruments": [BTC, ETH],
        "funding_start_inclusive": "2024-01-01T00:00:00Z",
        "mark_start_inclusive": "2023-12-31T23:00:00Z",
        "trade_start_inclusive": "2024-01-01T00:00:00Z",
        "trade_end_exclusive": "2024-01-02T01:00:00Z",
        "scored_end_exclusive": "2024-01-02T00:00:00Z",
    }
    with pytest.raises(C7AHistoricalCaptureError, match="normalized series"):
        package.finalize(
            implementation_sha=EXACT_SHA,
            capture_plan=capture_plan,
        )

    for instrument in (BTC, ETH):
        package.retain_normalized_series(
            series_type="marks",
            instrument=instrument,
            start_inclusive=capture_plan["mark_start_inclusive"],
            end_exclusive=capture_plan["scored_end_exclusive"],
            rows=({"timestamp": "2023-12-31T23:00:00Z", "close": "1"},),
        )
        package.retain_normalized_series(
            series_type="trades",
            instrument=instrument,
            start_inclusive=capture_plan["trade_start_inclusive"],
            end_exclusive=capture_plan["trade_end_exclusive"],
            rows=({"timestamp": "2024-01-01T00:00:00Z", "open": "1"},),
        )
        package.retain_normalized_series(
            series_type="funding",
            instrument=instrument,
            start_inclusive=capture_plan["funding_start_inclusive"],
            end_exclusive=capture_plan["scored_end_exclusive"],
            rows=({"funding_time": "2024-01-01T00:00:00Z", "realized_rate": "0"},),
        )
    manifest = package.finalize(
        implementation_sha=EXACT_SHA,
        capture_plan=capture_plan,
    )
    assert manifest["stage"] == "C7A_HISTORICAL_CAPTURE_PACKAGE"
    assert manifest["file_count"] == 8
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
        "trade_start_inclusive": "2023-12-04T00:00:00Z",
        "trade_end_exclusive": "2026-06-29T01:00:00Z",
        "scored_end_exclusive": "2026-06-29T00:00:00Z",
    }


def test_trade_capture_paginates_strictly_backward_and_preserves_execution_open(
    tmp_path,
) -> None:
    package = CapturePackage(tmp_path / "trades")
    pages = {
        T0 + 4 * HOUR: [
            _trade_row(T0 + 3 * HOUR, "103"),
            _trade_row(T0 + 2 * HOUR, "102"),
        ],
        T0 + 2 * HOUR: [
            _trade_row(T0 + HOUR, "101"),
            _trade_row(T0, "100"),
        ],
    }

    def fetch_page(request):
        cursor = int(parse_qs(urlparse(request.url).query)["after"][0])
        raw = json.dumps({"code": "0", "msg": "", "data": pages[cursor]}).encode()
        return raw, _record(request, raw)

    pauses = []
    selected = capture_trade_range(
        package,
        instrument=ETH,
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-01-01T04:00:00Z",
        fetch_page=fetch_page,
        max_pages=2,
        sleeper=pauses.append,
    )
    assert [row["open"] for row in selected] == ["100", "101", "102", "103"]
    assert len(package.records) == 2
    assert pauses == [0.11]
    assert (tmp_path / "trades" / "normalized" / "trades" / f"{ETH}.json").is_file()


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

    pauses = []
    selected = capture_mark_range(
        package,
        instrument=BTC,
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-01-01T04:00:00Z",
        fetch_page=fetch_page,
        max_pages=2,
        sleeper=pauses.append,
    )
    assert [row["close"] for row in selected] == ["100", "101", "102", "103"]
    assert len(package.records) == 2
    assert pauses == [0.25]
    assert (tmp_path / "marks" / "normalized" / "marks" / f"{BTC}.json").is_file()


def test_mark_capture_rejects_no_progress_and_transport_provenance_drift(
    tmp_path,
) -> None:
    package = CapturePackage(tmp_path / "bad-marks")

    def no_progress(request):
        cursor = int(parse_qs(urlparse(request.url).query)["after"][0])
        raw = json.dumps({"code": "0", "data": [_mark_row(cursor, "100")]}).encode()
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
        raw = json.dumps({"code": "0", "data": [_mark_row(T0, "100")]}).encode()
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


def test_paginated_capture_rejects_unsafe_pause_configuration(tmp_path) -> None:
    package = CapturePackage(tmp_path / "bad-pause")
    with pytest.raises(C7AHistoricalCaptureError, match="page pause"):
        capture_trade_range(
            package,
            instrument=BTC,
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-01-01T01:00:00Z",
            page_pause_seconds=True,
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
        "btc-funding-h1": (
            "inst,ts,rate\n"
            f"{BTC},{T0},0.0001\n"
            f"{BTC},{T0 + 8 * HOUR},0.0002\n"
            f"{BTC},{T0 + 16 * HOUR},0.0003\n"
        ).encode(),
        "eth-funding-h1": (
            "inst,ts,rate\n"
            f"{ETH},{T0},-0.0002\n"
            f"{ETH},{T0 + 8 * HOUR},-0.0001\n"
            f"{ETH},{T0 + 16 * HOUR},0\n"
        ).encode(),
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
    assert len(result[BTC]) == len(result[ETH]) == 3
    assert len(package.records) == 2


def test_historical_funding_capture_discovers_retains_and_normalizes_zips(
    tmp_path,
) -> None:
    package = CapturePackage(tmp_path / "funding-discovery")
    months = ((T0 - 8 * HOUR, "2024-01"), (1_706_716_800_000, "2024-02"))

    def archive_url(instrument: str, label: str) -> str:
        return (
            "https://static.okx.com/cdn/okex/traderecords/swaprates/monthly/"
            f"{label.replace('-', '')}/{instrument}-fundingrates-{label}.zip"
        )

    def fetch_manifest(request):
        instrument = BTC if "BTC-USDT" in request.url else ETH
        family = instrument.removesuffix("-SWAP")
        raw = json.dumps(
            {
                "code": "0",
                "msg": "",
                "data": [
                    {
                        "ts": str(T0),
                        "dateAggrType": "monthly",
                        "totalSizeMB": "1",
                        "details": [
                            {
                                "instId": instrument,
                                "instFamily": family,
                                "instType": "SWAP",
                                "dateRangeStart": str(T0),
                                "dateRangeEnd": "1709251200000",
                                "groupSizeMB": "1",
                                "groupDetails": [
                                    {
                                        "dateTs": str(stamp),
                                        "filename": f"{instrument}-fundingrates-{label}.zip",
                                        "sizeMB": "1",
                                        "url": archive_url(instrument, label),
                                    }
                                    for stamp, label in months
                                ],
                            }
                        ],
                    }
                ],
            }
        ).encode()
        return raw, _record(request, raw)

    def fetch_object(request):
        instrument = BTC if request.request_id.startswith("funding-BTC") else ETH
        label = (
            request.request_id.rsplit("-", 2)[-2]
            + "-"
            + request.request_id.rsplit("-", 1)[-1]
        )
        month_start = {
            "2024-01": T0,
            "2024-02": 1_706_745_600_000,
        }[label]
        month_end = 1_706_745_600_000 if label == "2024-01" else 1_709_251_200_000
        csv_raw = (
            "instrument_name,funding_time,funding_rate\n"
            + "".join(
                f"{instrument},{stamp},0.0001\n"
                for stamp in range(month_start, month_end, 8 * HOUR)
            )
        ).encode()
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(f"{instrument}-fundingrates-{label}.csv", csv_raw)
        raw = stream.getvalue()
        return raw, _record(request, raw)

    pauses: list[float] = []
    result = capture_historical_funding_range(
        package,
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-03-01T00:00:00Z",
        fetch_manifest=fetch_manifest,
        fetch_object=fetch_object,
        sleeper=pauses.append,
    )
    assert len(result[BTC]) == len(result[ETH]) == 180
    assert len(package.records) == 6
    assert pauses == [0.11, 0.11, 0.11, 0.11]


@pytest.mark.parametrize(
    "offsets,message",
    [
        ((8, 16), "does not start at the requested boundary"),
        ((0, 16), "gap exceeds eight hours"),
    ],
)
def test_funding_download_capture_rejects_missing_settlement_gap(
    tmp_path, offsets, message: str
) -> None:
    package = CapturePackage(tmp_path / "funding-gap")
    specs = [
        FundingDownloadSpec(
            request_id=f"{instrument.split('-', 1)[0].lower()}-gap",
            instrument=instrument,
            url=f"https://static.okx.com/cdn/history/{instrument}.csv",
            column_map={
                "instrument": "inst",
                "funding_time": "ts",
                "realized_rate": "rate",
            },
        )
        for instrument in (BTC, ETH)
    ]

    def fetch_object(request):
        instrument = BTC if request.request_id == "btc-gap" else ETH
        raw = (
            "inst,ts,rate\n"
            + "".join(
                f"{instrument},{T0 + offset * HOUR},0.0001\n" for offset in offsets
            )
        ).encode()
        return raw, _record(request, raw)

    with pytest.raises(C7AHistoricalCaptureError, match=message):
        capture_funding_downloads(
            package,
            specs=specs,
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-01-02T00:00:00Z",
            fetch_object=fetch_object,
        )


def test_funding_download_capture_rejects_duplicate_settlement_across_files(
    tmp_path,
) -> None:
    package = CapturePackage(tmp_path / "duplicate-funding")
    specs = [
        FundingDownloadSpec(
            request_id="btc-a",
            instrument=BTC,
            url="https://static.okx.com/cdn/history/btc-a.csv",
            column_map={
                "instrument": "inst",
                "funding_time": "ts",
                "realized_rate": "rate",
            },
        ),
        FundingDownloadSpec(
            request_id="btc-b",
            instrument=BTC,
            url="https://static.okx.com/cdn/history/btc-b.csv",
            column_map={
                "instrument": "inst",
                "funding_time": "ts",
                "realized_rate": "rate",
            },
        ),
        FundingDownloadSpec(
            request_id="eth-a",
            instrument=ETH,
            url="https://static.okx.com/cdn/history/eth-a.csv",
            column_map={
                "instrument": "inst",
                "funding_time": "ts",
                "realized_rate": "rate",
            },
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
