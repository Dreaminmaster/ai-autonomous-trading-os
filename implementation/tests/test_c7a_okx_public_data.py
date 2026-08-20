from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime
from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from atos.c7a_okx_public_data import (
    FUNDING_ARCHIVE_COLUMNS,
    C7APublicDataError,
    PublicRequest,
    build_historical_funding_manifest_requests,
    build_mark_price_request,
    build_recent_funding_request,
    build_trade_candle_request,
    fetch_raw,
    historical_download_request,
    historical_execution_metadata,
    next_older_mark_request,
    normalize_funding_api_payload,
    normalize_funding_download,
    normalize_funding_download_csv,
    normalize_historical_funding_manifest,
    normalize_mark_price_payload,
    normalize_trade_candle_payload,
    parse_json_object,
    select_exact_mark_interval,
    select_exact_trade_interval,
    select_funding_interval,
    validate_public_request,
)

BTC = "BTC-USDT-SWAP"
ETH = "ETH-USDT-SWAP"
T0 = 1_704_067_200_000  # 2024-01-01T00:00:00Z


def _mark_row(ts: int, close: str = "100") -> list[str]:
    close_value = Decimal(close)
    high = max(Decimal(101), close_value + Decimal(1))
    low = min(Decimal(98), close_value - Decimal(1))
    return [str(ts), "99", format(high, "f"), format(low, "f"), close, "1"]


def _trade_row(ts: int, close: str = "100") -> list[str]:
    close_value = Decimal(close)
    high = max(Decimal(101), close_value + Decimal(1))
    low = min(Decimal(98), close_value - Decimal(1))
    return [
        str(ts),
        "99",
        format(high, "f"),
        format(low, "f"),
        close,
        "10",
        "0.1",
        "1000",
        "1",
    ]


def _funding_row(ts: int, rate: str, instrument: str = BTC) -> dict[str, str]:
    return {
        "instId": instrument,
        "fundingTime": str(ts),
        "realizedRate": rate,
    }


def test_mark_request_is_exact_public_contract() -> None:
    request = build_mark_price_request(BTC, after_ms=T0)
    parsed = urlparse(request.url)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "https"
    assert parsed.netloc == "www.okx.com"
    assert parsed.path == "/api/v5/market/history-mark-price-candles"
    assert query == {
        "after": [str(T0)],
        "bar": ["1H"],
        "instId": [BTC],
        "limit": ["100"],
    }
    validate_public_request(request)


def test_trade_request_is_exact_public_contract() -> None:
    request = build_trade_candle_request(ETH, after_ms=T0)
    parsed = urlparse(request.url)
    assert parsed.path == "/api/v5/market/history-candles"
    assert parse_qs(parsed.query) == {
        "after": [str(T0)],
        "bar": ["1H"],
        "instId": [ETH],
        "limit": ["300"],
    }
    validate_public_request(request)


def test_recent_funding_request_is_labeled_recent_and_bounded() -> None:
    request = build_recent_funding_request(ETH, before_ms=T0, host="us.okx.com")
    query = parse_qs(urlparse(request.url).query)
    assert request.request_id.startswith("funding-recent-")
    assert query == {"before": [str(T0)], "instId": [ETH], "limit": ["400"]}
    validate_public_request(request)


def test_historical_funding_manifest_requests_are_public_and_chunked() -> None:
    requests = build_historical_funding_manifest_requests(
        BTC,
        start_inclusive="2023-12-04T00:00:00Z",
        end_exclusive="2026-06-29T00:00:00Z",
    )
    assert len(requests) == 4
    assert all(
        request.source_family == "OKX_HISTORICAL_DATA_API" for request in requests
    )
    assert all(
        urlparse(request.url).netloc == "openapi.okx.com" for request in requests
    )
    queries = [parse_qs(urlparse(request.url).query) for request in requests]
    first = queries[0]
    assert first["module"] == ["3"]
    assert first["instType"] == ["SWAP"]
    assert first["instFamilyList"] == ["BTC-USDT"]
    assert first["dateAggrType"] == ["monthly"]
    assert datetime.fromtimestamp(int(first["begin"][0]) / 1000, tz=UTC) == datetime(
        2023, 12, 1, tzinfo=UTC
    )
    assert [
        datetime.fromtimestamp(int(query["begin"][0]) / 1000, tz=UTC)
        for query in queries
    ] == [
        datetime(2023, 12, 1, tzinfo=UTC),
        datetime(2024, 9, 1, tzinfo=UTC),
        datetime(2025, 6, 1, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    ]
    def inclusive_utc_months(query: dict[str, list[str]]) -> int:
        begin = datetime.fromtimestamp(int(query["begin"][0]) / 1000, tz=UTC)
        end = datetime.fromtimestamp(int(query["end"][0]) / 1000, tz=UTC)
        return (end.year - begin.year) * 12 + end.month - begin.month + 1

    assert [inclusive_utc_months(query) for query in queries] == [9, 9, 9, 4]
    for request in requests:
        validate_public_request(request)


def test_pagination_may_not_mix_before_and_after() -> None:
    with pytest.raises(C7APublicDataError, match="after or before"):
        build_mark_price_request(BTC, after_ms=T0, before_ms=T0 + 1)
    with pytest.raises(C7APublicDataError, match="after or before"):
        build_recent_funding_request(BTC, after_ms=T0, before_ms=T0 + 1)
    with pytest.raises(C7APublicDataError, match="after or before"):
        build_trade_candle_request(BTC, after_ms=T0, before_ms=T0 + 1)


@pytest.mark.parametrize(
    "public_request,message",
    [
        (
            PublicRequest(
                "bad-host",
                "OKX_HISTORY_MARK_PRICE_CANDLES_API",
                "https://example.com/api/v5/market/history-mark-price-candles"
                "?instId=BTC-USDT-SWAP&bar=1H&limit=100",
            ),
            "official OKX",
        ),
        (
            PublicRequest(
                "auth-query",
                "OKX_HISTORY_MARK_PRICE_CANDLES_API",
                "https://www.okx.com/api/v5/market/history-mark-price-candles"
                "?instId=BTC-USDT-SWAP&bar=1H&limit=100&apiKey=x",
            ),
            "credential query",
        ),
        (
            PublicRequest(
                "auth-header",
                "OKX_HISTORY_MARK_PRICE_CANDLES_API",
                "https://www.okx.com/api/v5/market/history-mark-price-candles"
                "?instId=BTC-USDT-SWAP&bar=1H&limit=100",
                headers=(("OK-ACCESS-KEY", "secret"),),
            ),
            "authentication material",
        ),
        (
            PublicRequest(
                "extra-query",
                "OKX_HISTORY_MARK_PRICE_CANDLES_API",
                "https://www.okx.com/api/v5/market/history-mark-price-candles"
                "?instId=BTC-USDT-SWAP&bar=1H&limit=100&foo=bar",
            ),
            "query contract drift",
        ),
        (
            PublicRequest(
                "duplicate-query",
                "OKX_HISTORY_MARK_PRICE_CANDLES_API",
                "https://www.okx.com/api/v5/market/history-mark-price-candles"
                "?instId=BTC-USDT-SWAP&instId=ETH-USDT-SWAP&bar=1H&limit=100",
            ),
            "duplicate query",
        ),
        (
            PublicRequest(
                "private",
                "OKX_HISTORICAL_DOWNLOAD",
                "https://www.okx.com/api/v5/account/balance",
            ),
            "private or account",
        ),
    ],
)
def test_unsafe_or_drifted_request_is_rejected(
    public_request: PublicRequest, message: str
) -> None:
    with pytest.raises(C7APublicDataError, match=message):
        validate_public_request(public_request)


def test_official_historical_download_request_is_account_free() -> None:
    request = historical_download_request(
        "https://www.okx.com/cdn/okx/traderecords/funding-rate.csv",
        request_id="funding-h1",
    )
    assert request.source_family == "OKX_HISTORICAL_DOWNLOAD"
    validate_public_request(request)


def test_mark_payload_normalizes_reverse_order_to_ascending() -> None:
    payload = {
        "code": "0",
        "msg": "",
        "data": [
            _mark_row(T0 + 3_600_000, "101"),
            _mark_row(T0, "100"),
        ],
    }
    rows = normalize_mark_price_payload(payload, instrument=BTC)
    assert [row["timestamp"] for row in rows] == [
        "2024-01-01T00:00:00Z",
        "2024-01-01T01:00:00Z",
    ]
    assert rows[0]["close"] == "100"
    assert rows[1]["close"] == "101"


def test_trade_payload_normalizes_completed_exact_hour_rows() -> None:
    rows = normalize_trade_candle_payload(
        {
            "code": "0",
            "data": [
                _trade_row(T0 + 3_600_000, "101"),
                _trade_row(T0, "100"),
            ],
        },
        instrument=ETH,
    )
    assert [row["timestamp"] for row in rows] == [
        "2024-01-01T00:00:00Z",
        "2024-01-01T01:00:00Z",
    ]
    assert rows[0]["open"] == "99"
    assert rows[0]["volume_quote"] == "1000"


@pytest.mark.parametrize(
    "offset,value,message",
    [
        (8, "0", "unconfirmed"),
        (0, str(T0 + 1), "exact hour"),
        (5, "-1", "non-negative"),
    ],
)
def test_bad_trade_candle_is_rejected(offset: int, value: str, message: str) -> None:
    row = _trade_row(T0)
    row[offset] = value
    with pytest.raises(C7APublicDataError, match=message):
        normalize_trade_candle_payload({"code": "0", "data": [row]}, instrument=BTC)


@pytest.mark.parametrize(
    "mutator,message",
    [
        (lambda row: row.__setitem__(5, "0"), "unconfirmed"),
        (lambda row: row.__setitem__(0, str(T0 + 1)), "exact hour"),
        (lambda row: row.__setitem__(2, "97"), "high"),
        (lambda row: row.__setitem__(3, "102"), "low"),
    ],
)
def test_bad_mark_row_is_rejected(mutator, message: str) -> None:
    row = _mark_row(T0)
    mutator(row)
    with pytest.raises(C7APublicDataError, match=message):
        normalize_mark_price_payload({"code": "0", "data": [row]}, instrument=BTC)


def test_duplicate_mark_timestamp_is_rejected() -> None:
    row = _mark_row(T0)
    with pytest.raises(C7APublicDataError, match="duplicate"):
        normalize_mark_price_payload(
            {"code": "0", "data": [row, list(row)]},
            instrument=BTC,
        )


def test_next_older_mark_page_uses_oldest_timestamp_as_after_cursor() -> None:
    rows = normalize_mark_price_payload(
        {
            "code": "0",
            "data": [_mark_row(T0 + 3_600_000), _mark_row(T0)],
        },
        instrument=BTC,
    )
    request = next_older_mark_request(rows, instrument=BTC)
    assert parse_qs(urlparse(request.url).query)["after"] == [str(T0)]


def test_funding_api_uses_realized_rate_and_accepts_irregular_settlements() -> None:
    payload = {
        "code": "0",
        "data": [
            _funding_row(T0 + 8 * 3_600_000, "0.0002"),
            _funding_row(T0, "-0.0001"),
            _funding_row(T0 + 12 * 3_600_000, "0.0003"),
        ],
    }
    rows = normalize_funding_api_payload(payload, instrument=BTC)
    assert [row["realized_rate"] for row in rows] == ["-0.0001", "0.0002", "0.0003"]
    selected = select_funding_interval(
        rows,
        instrument=BTC,
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-01-02T00:00:00Z",
    )
    assert len(selected) == 3


def test_funding_scientific_notation_is_canonicalized_exactly() -> None:
    official_rate = "6.77685581E-8"
    expected = "0.0000000677685581"
    api_rows = normalize_funding_api_payload(
        {"code": "0", "data": [_funding_row(T0, official_rate)]},
        instrument=BTC,
    )
    assert api_rows[0]["realized_rate"] == expected

    csv_raw = (
        "instrument_name,funding_time,funding_rate\n"
        f"{BTC},{T0},{official_rate}\n"
    ).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BTC-USDT-SWAP-fundingrates-2024-01.csv", csv_raw)
    archive_rows = normalize_funding_download(
        stream.getvalue(), instrument=BTC, column_map=FUNDING_ARCHIVE_COLUMNS
    )
    assert archive_rows[0]["realized_rate"] == expected


@pytest.mark.parametrize("invalid_rate", ["NaN", "Infinity", "-Infinity"])
def test_funding_scientific_support_still_rejects_non_finite_values(
    invalid_rate: str,
) -> None:
    with pytest.raises(C7APublicDataError, match="must be finite"):
        normalize_funding_api_payload(
            {"code": "0", "data": [_funding_row(T0, invalid_rate)]},
            instrument=BTC,
        )


@pytest.mark.parametrize("unsafe_rate", ["1E+129", "1E-129", "0E-129"])
def test_funding_scientific_support_rejects_format_expansion_dos(
    unsafe_rate: str,
) -> None:
    with pytest.raises(C7APublicDataError, match="exponent exceeds canonical bounds"):
        normalize_funding_api_payload(
            {"code": "0", "data": [_funding_row(T0, unsafe_rate)]},
            instrument=BTC,
        )


def test_exact_decimal_input_length_is_bounded() -> None:
    with pytest.raises(C7APublicDataError, match="exact decimal text is too long"):
        normalize_mark_price_payload(
            {"code": "0", "data": [_mark_row(T0, "1" * 129)]},
            instrument=BTC,
        )


def test_candle_values_still_reject_exponent_notation() -> None:
    with pytest.raises(C7APublicDataError, match="must not use exponent notation"):
        normalize_mark_price_payload(
            {"code": "0", "data": [_mark_row(T0, "1E2")]},
            instrument=BTC,
        )


def test_funding_csv_requires_explicit_reviewed_schema() -> None:
    raw = (
        "\ufeffinstrument,funding_timestamp,settled_rate\n"
        f"{BTC},{T0},0.00010\n"
        f"{BTC},{T0 + 8 * 3_600_000},-0.00020\n"
    ).encode()
    rows = normalize_funding_download_csv(
        raw,
        instrument=BTC,
        column_map={
            "instrument": "instrument",
            "funding_time": "funding_timestamp",
            "realized_rate": "settled_rate",
        },
    )
    assert rows[0]["realized_rate"] == "0.0001"
    assert rows[1]["realized_rate"] == "-0.0002"

    with pytest.raises(C7APublicDataError, match="reviewed schema"):
        normalize_funding_download_csv(
            raw,
            instrument=BTC,
            column_map={
                "instrument": "instrument",
                "funding_time": "funding_timestamp",
                "realized_rate": "unknown",
            },
        )

    with pytest.raises(C7APublicDataError, match="reviewed schema"):
        normalize_funding_download_csv(
            raw.replace(b"settled_rate", b"settled_rate,unexpected"),
            instrument=BTC,
            column_map={
                "instrument": "instrument",
                "funding_time": "funding_timestamp",
                "realized_rate": "settled_rate",
            },
        )


def test_official_funding_zip_is_parsed_without_extracting(tmp_path) -> None:
    csv_raw = (
        "instrument_name,funding_time,funding_rate\n"
        f"{BTC},{T0},0.00010\n"
        f"{BTC},{T0 + 8 * 3_600_000},-0.00020\n"
    ).encode()
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("BTC-USDT-SWAP-fundingrates-2024-01.csv", csv_raw)
    rows = normalize_funding_download(
        stream.getvalue(), instrument=BTC, column_map=FUNDING_ARCHIVE_COLUMNS
    )
    assert [row["realized_rate"] for row in rows] == ["0.0001", "-0.0002"]
    assert not tuple(tmp_path.iterdir())

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("../escape.csv", csv_raw)
    with pytest.raises(C7APublicDataError, match="unsafe"):
        normalize_funding_download(
            stream.getvalue(), instrument=BTC, column_map=FUNDING_ARCHIVE_COLUMNS
        )


def test_historical_funding_manifest_requires_exact_month_coverage() -> None:
    payload = {
        "code": "0",
        "msg": "",
        "data": [
            {
                "ts": str(T0),
                "dateAggrType": "monthly",
                "totalSizeMB": "1",
                "details": [
                    {
                        "instId": BTC,
                        "instFamily": "BTC-USDT",
                        "instType": "SWAP",
                        "dateRangeStart": str(T0),
                        "dateRangeEnd": str(1_709_251_200_000),
                        "groupSizeMB": "1",
                        "groupDetails": [
                            {
                                "dateTs": str(T0 - 8 * 3_600_000),
                                "filename": "BTC-USDT-SWAP-fundingrates-2024-01.zip",
                                "sizeMB": "1",
                                "url": "https://static.okx.com/cdn/okex/traderecords/"
                                "swaprates/monthly/202401/"
                                "BTC-USDT-SWAP-fundingrates-2024-01.zip",
                            },
                            {
                                "dateTs": "1706716800000",
                                "filename": "BTC-USDT-SWAP-fundingrates-2024-02.zip",
                                "sizeMB": "1",
                                "url": "https://static.okx.com/cdn/okex/traderecords/"
                                "swaprates/monthly/202402/"
                                "BTC-USDT-SWAP-fundingrates-2024-02.zip",
                            },
                        ],
                    }
                ],
            }
        ],
    }
    archives = normalize_historical_funding_manifest(
        payload,
        instrument=BTC,
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-03-01T00:00:00Z",
    )
    assert [item["request_id"] for item in archives] == [
        "funding-BTC-USDT-SWAP-2024-01",
        "funding-BTC-USDT-SWAP-2024-02",
    ]
    payload["data"][0]["details"][0]["groupDetails"].pop()
    with pytest.raises(C7APublicDataError, match="coverage is incomplete"):
        normalize_historical_funding_manifest(
            payload,
            instrument=BTC,
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-03-01T00:00:00Z",
        )


def test_funding_instrument_and_duplicate_settlements_are_rejected() -> None:
    with pytest.raises(C7APublicDataError, match="instrument mismatch"):
        normalize_funding_api_payload(
            {"code": "0", "data": [_funding_row(T0, "0.1", instrument=ETH)]},
            instrument=BTC,
        )
    row = _funding_row(T0, "0.1")
    with pytest.raises(C7APublicDataError, match="duplicate"):
        normalize_funding_api_payload(
            {"code": "0", "data": [row, dict(row)]},
            instrument=BTC,
        )


def test_exact_mark_selection_requires_every_hour_and_canonical_close() -> None:
    rows = normalize_mark_price_payload(
        {
            "code": "0",
            "data": [
                _mark_row(T0 + 2 * 3_600_000, "102.000"),
                _mark_row(T0 + 1 * 3_600_000, "101.000"),
                _mark_row(T0, "100.000"),
            ],
        },
        instrument=BTC,
    )
    selected = select_exact_mark_interval(
        rows,
        instrument=BTC,
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-01-01T03:00:00Z",
    )
    assert [row["close"] for row in selected] == ["100", "101", "102"]

    with pytest.raises(C7APublicDataError, match="missing exact mark hour"):
        select_exact_mark_interval(
            (rows[0], rows[2]),
            instrument=BTC,
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-01-01T03:00:00Z",
        )


def test_exact_trade_selection_requires_every_hour_and_preserves_execution_open() -> (
    None
):
    rows = normalize_trade_candle_payload(
        {
            "code": "0",
            "data": [
                _trade_row(T0 + 3_600_000, "101"),
                _trade_row(T0, "100"),
            ],
        },
        instrument=BTC,
    )
    selected = select_exact_trade_interval(
        rows,
        instrument=BTC,
        start_inclusive="2024-01-01T00:00:00Z",
        end_exclusive="2024-01-01T02:00:00Z",
    )
    assert selected == (
        {"timestamp": "2024-01-01T00:00:00Z", "open": "99", "close": "100"},
        {"timestamp": "2024-01-01T01:00:00Z", "open": "99", "close": "101"},
    )

    with pytest.raises(C7APublicDataError, match="missing exact trade hour"):
        select_exact_trade_interval(
            rows[1:],
            instrument=BTC,
            start_inclusive="2024-01-01T00:00:00Z",
            end_exclusive="2024-01-01T02:00:00Z",
        )


class _Headers(dict):
    pass


class _Response:
    def __init__(
        self,
        raw: bytes,
        *,
        content_type: str = "application/json; charset=utf-8",
        status: int = 200,
        final_url: str = "https://www.okx.com/api/v5/market/history-mark-price-candles",
    ):
        self._raw = raw
        self.headers = _Headers({"Content-Type": content_type})
        self.status = status
        self._final_url = final_url
        self.closed = False

    def read(self, limit: int) -> bytes:
        return self._raw[:limit]

    def geturl(self) -> str:
        return self._final_url

    def close(self) -> None:
        self.closed = True


def test_fetch_raw_preserves_hash_size_media_and_closes_response() -> None:
    raw = json.dumps({"code": "0", "msg": "", "data": []}).encode()
    response = _Response(raw)

    def opener(request, timeout):
        assert request.get_method() == "GET"
        assert timeout == 30
        return response

    request = build_mark_price_request(BTC, after_ms=T0)
    fetched, provenance = fetch_raw(
        request,
        opener=opener,
        collected_at=datetime(2026, 7, 28, tzinfo=UTC),
    )
    assert fetched == raw
    assert provenance.size == len(raw)
    assert provenance.sha256 == hashlib.sha256(raw).hexdigest()
    assert provenance.media_type == "application/json"
    assert provenance.collected_at == "2026-07-28T00:00:00Z"
    assert response.closed is True
    assert parse_json_object(fetched)["data"] == []


def test_fetch_raw_rejects_official_to_external_redirect_and_html_api() -> None:
    request = build_mark_price_request(BTC, after_ms=T0)

    with pytest.raises(C7APublicDataError, match="redirected outside"):
        fetch_raw(
            request,
            opener=lambda *_args, **_kwargs: _Response(
                b"{}",
                final_url="https://example.com/data",
            ),
        )

    with pytest.raises(C7APublicDataError, match="media type"):
        fetch_raw(
            request,
            opener=lambda *_args, **_kwargs: _Response(
                b"<html></html>",
                content_type="text/html",
            ),
        )


def test_historical_metadata_is_explicitly_non_private_and_non_live() -> None:
    metadata = historical_execution_metadata(
        source_family="OKX_HISTORICAL_DOWNLOAD",
        collected_at="2026-07-28T00:00:00Z",
    )
    assert metadata["authenticated"] is False
    assert metadata["contains_account_data"] is False
    assert metadata["contains_order_data"] is False
    assert metadata["private_api"] is False
    assert metadata["paper_side_effect"] is False
    assert metadata["live_state"] == "LIVE_FORBIDDEN"
