"""Official-public OKX acquisition and normalization primitives for C7A.

The module is deliberately account-free.  It accepts only HTTPS GET requests to
official OKX hosts, forbids authentication material, preserves raw response
provenance, and normalizes mark-price candles and funding settlements into the
row shapes consumed by the frozen C7A calculation.

Long-horizon funding history must come from the official OKX historical-data
download surface.  The REST funding-rate-history endpoint is represented only
for recent validation because OKX documents a three-month retention boundary.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import zipfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from atos.c7a_contract import INSTRUMENTS
from atos.c7a_historical_schedule import (
    C7AHistoricalScheduleError,
    assert_official_public_metadata,
)


class C7APublicDataError(RuntimeError):
    """Raised when public acquisition or normalization cannot be proven safe."""


API_HOSTS = frozenset({"openapi.okx.com", "www.okx.com", "us.okx.com", "eea.okx.com"})
C9A_PUBLIC_SPOT_TRADE_INSTRUMENTS = ("BTC-USDT", "ETH-USDT")
C9A_PUBLIC_TRADE_INSTRUMENTS = (*C9A_PUBLIC_SPOT_TRADE_INSTRUMENTS, *INSTRUMENTS)
TRADE_HISTORY_PATH = "/api/v5/market/history-candles"
MARK_HISTORY_PATH = "/api/v5/market/history-mark-price-candles"
FUNDING_HISTORY_PATH = "/api/v5/public/funding-rate-history"
HISTORICAL_DATA_PATH = "/api/v5/public/market-data-history"
ALLOWED_API_PATHS = frozenset(
    {
        TRADE_HISTORY_PATH,
        MARK_HISTORY_PATH,
        FUNDING_HISTORY_PATH,
        HISTORICAL_DATA_PATH,
    }
)
PROHIBITED_QUERY_KEYS = frozenset(
    {
        "apikey",
        "api_key",
        "secret",
        "passphrase",
        "signature",
        "sign",
        "token",
        "authorization",
    }
)
PROHIBITED_HEADER_KEYS = frozenset(
    {
        "authorization",
        "cookie",
        "ok-access-key",
        "ok-access-sign",
        "ok-access-passphrase",
        "ok-access-timestamp",
    }
)
PRIVATE_PATH_MARKERS = (
    "/api/v5/account/",
    "/api/v5/trade/",
    "/api/v5/asset/",
    "/api/v5/broker/",
    "/api/v5/users/",
)
MAX_RAW_BYTES = 64 * 1024 * 1024
MAX_EXTRACTED_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_EXACT_DECIMAL_INPUT_CHARS = 128
MAX_FIXED_DECIMAL_EXPONENT = 128
HTTP_TIMEOUT_SECONDS = 30
MARK_PAGE_LIMIT = 100
TRADE_PAGE_LIMIT = 300
FUNDING_PAGE_LIMIT = 400
HOUR_MS = 3_600_000
FUNDING_DOWNLOAD_MODULE = "3"
FUNDING_DOWNLOAD_AGGREGATION = "monthly"
# The official endpoint currently rejects an inclusive ten-UTC-month request
# with code 50077 ("cannot exceed 10 months").  Its UTC request bounds can also
# cross into one additional UTC+8 archive month, so nine requested UTC months
# are the largest fail-closed chunk accepted without relying on truncation.
MAX_MONTHS_PER_HISTORY_REQUEST = 9
FUNDING_ARCHIVE_COLUMNS = {
    "instrument": "instrument_name",
    "funding_time": "funding_time",
    "realized_rate": "funding_rate",
}


@dataclass(frozen=True)
class PublicRequest:
    request_id: str
    source_family: str
    url: str
    method: str = "GET"
    headers: tuple[tuple[str, str], ...] = (
        ("Accept", "application/json"),
        ("User-Agent", "ai-autonomous-trading-os/c7a-public-data"),
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["headers"] = dict(self.headers)
        return payload


@dataclass(frozen=True)
class RawObject:
    request_id: str
    source_family: str
    url: str
    collected_at: str
    size: int
    sha256: str
    media_type: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _exact_decimal(
    value: Any,
    label: str,
    *,
    positive: bool = False,
    allow_exponent: bool = False,
) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise C7APublicDataError(f"{label} must be a non-empty exact decimal string")
    if len(value) > MAX_EXACT_DECIMAL_INPUT_CHARS:
        raise C7APublicDataError(f"{label} exact decimal text is too long")
    if not allow_exponent and "e" in value.lower():
        raise C7APublicDataError(f"{label} must not use exponent notation")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise C7APublicDataError(f"{label} is not an exact decimal") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise C7APublicDataError(f"{label} must be {qualifier}")
    if allow_exponent and abs(parsed.adjusted()) > MAX_FIXED_DECIMAL_EXPONENT:
        raise C7APublicDataError(f"{label} exponent exceeds canonical bounds")
    text = format(parsed, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _millis(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise C7APublicDataError(f"{label} must be Unix milliseconds")
    text = str(value)
    if not text.isdigit():
        raise C7APublicDataError(f"{label} must be Unix milliseconds")
    result = int(text)
    if result <= 0:
        raise C7APublicDataError(f"{label} must be positive")
    return result


def _iso_millis(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
    )


def _validate_instrument(instrument: str) -> None:
    if instrument not in INSTRUMENTS:
        raise C7APublicDataError(f"unsupported C7A instrument: {instrument!r}")


def _official_host(hostname: str | None) -> bool:
    if not hostname:
        return False
    lowered = hostname.lower()
    return lowered == "okx.com" or lowered.endswith(".okx.com")


def _query_map(url: str) -> dict[str, str]:
    pairs = parse_qsl(urlparse(url).query, keep_blank_values=True)
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)):
        raise C7APublicDataError("public request contains duplicate query keys")
    return dict(pairs)


def _validate_api_query(
    request: PublicRequest,
    *,
    expected_path: str,
    allowed_keys: frozenset[str],
    required_keys: frozenset[str],
    allowed_instruments: Sequence[str] = INSTRUMENTS,
) -> None:
    query = _query_map(request.url)
    if set(query) - allowed_keys or not required_keys.issubset(query):
        raise C7APublicDataError("public API query contract drift")
    if query.get("instId") not in allowed_instruments:
        raise C7APublicDataError("public API instrument drift")
    if "after" in query and "before" in query:
        raise C7APublicDataError(
            "public API pagination may not use after and before together"
        )
    for key in ("after", "before"):
        if key in query:
            _millis(query[key], key)
    if expected_path in {TRADE_HISTORY_PATH, MARK_HISTORY_PATH}:
        expected_limit = (
            TRADE_PAGE_LIMIT if expected_path == TRADE_HISTORY_PATH else MARK_PAGE_LIMIT
        )
        if query.get("bar") != "1H" or query.get("limit") != str(expected_limit):
            label = (
                "trade-candle" if expected_path == TRADE_HISTORY_PATH else "mark-price"
            )
            raise C7APublicDataError(f"{label} API bar or limit drift")
    elif expected_path == FUNDING_HISTORY_PATH:
        if query.get("limit") != str(FUNDING_PAGE_LIMIT):
            raise C7APublicDataError("funding API limit drift")


def validate_public_request(
    request: PublicRequest, *, trade_instruments: Sequence[str] = INSTRUMENTS
) -> None:
    trade_set = frozenset(trade_instruments)
    if trade_set not in {
        frozenset(INSTRUMENTS),
        frozenset(C9A_PUBLIC_TRADE_INSTRUMENTS),
    }:
        raise C7APublicDataError("unsupported public trade-instrument policy")
    if not request.request_id or request.method != "GET":
        raise C7APublicDataError(
            "public request requires a non-empty ID and GET method"
        )
    if request.source_family not in {
        "OKX_HISTORY_CANDLES_API",
        "OKX_HISTORY_MARK_PRICE_CANDLES_API",
        "OKX_FUNDING_RATE_HISTORY_API",
        "OKX_HISTORICAL_DATA_API",
        "OKX_HISTORICAL_DOWNLOAD",
    }:
        raise C7APublicDataError("unsupported C7A public source family")
    parsed = urlparse(request.url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise C7APublicDataError("public request must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise C7APublicDataError(
            "public request URL contains credentials or a fragment"
        )
    if not _official_host(parsed.hostname):
        raise C7APublicDataError("public request must target an official OKX host")
    if any(marker in parsed.path.lower() for marker in PRIVATE_PATH_MARKERS):
        raise C7APublicDataError("private or account endpoint is forbidden")
    query_keys = {
        key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)
    }
    if query_keys & PROHIBITED_QUERY_KEYS:
        raise C7APublicDataError("public request URL contains a credential query")
    header_keys = {key.lower() for key, _ in request.headers}
    if header_keys & PROHIBITED_HEADER_KEYS:
        raise C7APublicDataError("public request contains authentication material")
    if request.source_family == "OKX_HISTORY_CANDLES_API":
        if parsed.hostname not in API_HOSTS or parsed.path != TRADE_HISTORY_PATH:
            raise C7APublicDataError("trade-candle history endpoint or host drift")
        _validate_api_query(
            request,
            expected_path=TRADE_HISTORY_PATH,
            allowed_keys=frozenset({"instId", "bar", "limit", "after", "before"}),
            required_keys=frozenset({"instId", "bar", "limit"}),
            allowed_instruments=trade_instruments,
        )
    elif request.source_family == "OKX_HISTORY_MARK_PRICE_CANDLES_API":
        if parsed.hostname not in API_HOSTS or parsed.path != MARK_HISTORY_PATH:
            raise C7APublicDataError("mark-price history endpoint or host drift")
        _validate_api_query(
            request,
            expected_path=MARK_HISTORY_PATH,
            allowed_keys=frozenset({"instId", "bar", "limit", "after", "before"}),
            required_keys=frozenset({"instId", "bar", "limit"}),
        )
    elif request.source_family == "OKX_FUNDING_RATE_HISTORY_API":
        if parsed.hostname not in API_HOSTS or parsed.path != FUNDING_HISTORY_PATH:
            raise C7APublicDataError("funding-rate history endpoint or host drift")
        _validate_api_query(
            request,
            expected_path=FUNDING_HISTORY_PATH,
            allowed_keys=frozenset({"instId", "limit", "after", "before"}),
            required_keys=frozenset({"instId", "limit"}),
        )
    elif request.source_family == "OKX_HISTORICAL_DATA_API":
        if parsed.hostname not in API_HOSTS or parsed.path != HISTORICAL_DATA_PATH:
            raise C7APublicDataError("historical-data endpoint or host drift")
        query = _query_map(request.url)
        if set(query) != {
            "module",
            "instType",
            "instFamilyList",
            "dateAggrType",
            "begin",
            "end",
        }:
            raise C7APublicDataError("historical-data API query contract drift")
        if (
            query["module"] != FUNDING_DOWNLOAD_MODULE
            or query["instType"] != "SWAP"
            or query["dateAggrType"] != FUNDING_DOWNLOAD_AGGREGATION
            or f"{query['instFamilyList']}-SWAP" not in INSTRUMENTS
        ):
            raise C7APublicDataError("historical funding query identity drift")
        begin = _millis(query["begin"], "historical begin")
        end = _millis(query["end"], "historical end")
        if begin > end:
            raise C7APublicDataError("historical-data begin is after end")
        months = _month_starts(begin, end + 1)
        if not months or len(months) > MAX_MONTHS_PER_HISTORY_REQUEST:
            raise C7APublicDataError("historical-data request exceeds 9 UTC months")
    else:
        if parsed.path.startswith("/api/"):
            raise C7APublicDataError(
                "historical download source may not masquerade as an API"
            )


def _api_url(host: str, path: str, params: Mapping[str, str]) -> str:
    if host not in API_HOSTS:
        raise C7APublicDataError(f"unsupported OKX API host: {host!r}")
    query = urlencode(sorted(params.items()))
    return urlunparse(("https", host, path, "", query, ""))


def build_mark_price_request(
    instrument: str,
    *,
    after_ms: int | None = None,
    before_ms: int | None = None,
    host: str = "www.okx.com",
) -> PublicRequest:
    _validate_instrument(instrument)
    if after_ms is not None and before_ms is not None:
        raise C7APublicDataError("mark pagination may use after or before, not both")
    params = {"instId": instrument, "bar": "1H", "limit": str(MARK_PAGE_LIMIT)}
    if after_ms is not None:
        params["after"] = str(_millis(after_ms, "after"))
    if before_ms is not None:
        params["before"] = str(_millis(before_ms, "before"))
    request = PublicRequest(
        request_id=f"mark-{instrument}-{after_ms or before_ms or 'latest'}",
        source_family="OKX_HISTORY_MARK_PRICE_CANDLES_API",
        url=_api_url(host, MARK_HISTORY_PATH, params),
    )
    validate_public_request(request)
    return request


def build_trade_candle_request(
    instrument: str,
    *,
    after_ms: int | None = None,
    before_ms: int | None = None,
    host: str = "www.okx.com",
) -> PublicRequest:
    """Build the official completed one-hour perpetual trade-candle request."""
    _validate_instrument(instrument)
    if after_ms is not None and before_ms is not None:
        raise C7APublicDataError("trade pagination may use after or before, not both")
    params = {"instId": instrument, "bar": "1H", "limit": str(TRADE_PAGE_LIMIT)}
    if after_ms is not None:
        params["after"] = str(_millis(after_ms, "after"))
    if before_ms is not None:
        params["before"] = str(_millis(before_ms, "before"))
    request = PublicRequest(
        request_id=f"trade-{instrument}-{after_ms or before_ms or 'latest'}",
        source_family="OKX_HISTORY_CANDLES_API",
        url=_api_url(host, TRADE_HISTORY_PATH, params),
    )
    validate_public_request(request)
    return request


def build_recent_funding_request(
    instrument: str,
    *,
    after_ms: int | None = None,
    before_ms: int | None = None,
    host: str = "www.okx.com",
) -> PublicRequest:
    """Build the documented recent-history request, never a deep-history substitute."""
    _validate_instrument(instrument)
    if after_ms is not None and before_ms is not None:
        raise C7APublicDataError("funding pagination may use after or before, not both")
    params = {"instId": instrument, "limit": str(FUNDING_PAGE_LIMIT)}
    if after_ms is not None:
        params["after"] = str(_millis(after_ms, "after"))
    if before_ms is not None:
        params["before"] = str(_millis(before_ms, "before"))
    request = PublicRequest(
        request_id=f"funding-recent-{instrument}-{after_ms or before_ms or 'latest'}",
        source_family="OKX_FUNDING_RATE_HISTORY_API",
        url=_api_url(host, FUNDING_HISTORY_PATH, params),
    )
    validate_public_request(request)
    return request


def _month_start_ms(value: int) -> int:
    stamp = datetime.fromtimestamp(value / 1000, tz=UTC)
    return int(datetime(stamp.year, stamp.month, 1, tzinfo=UTC).timestamp() * 1000)


def _next_month_ms(value: int) -> int:
    stamp = datetime.fromtimestamp(value / 1000, tz=UTC)
    year = stamp.year + (1 if stamp.month == 12 else 0)
    month = 1 if stamp.month == 12 else stamp.month + 1
    return int(datetime(year, month, 1, tzinfo=UTC).timestamp() * 1000)


def _month_starts(start_inclusive_ms: int, end_exclusive_ms: int) -> tuple[int, ...]:
    if start_inclusive_ms >= end_exclusive_ms:
        return ()
    current = _month_start_ms(start_inclusive_ms)
    final = _month_start_ms(end_exclusive_ms - 1)
    values: list[int] = []
    while current <= final:
        values.append(current)
        current = _next_month_ms(current)
    return tuple(values)


def build_historical_funding_manifest_requests(
    instrument: str,
    *,
    start_inclusive: Any,
    end_exclusive: Any,
    host: str = "openapi.okx.com",
) -> tuple[PublicRequest, ...]:
    """Build bounded official batch-manifest requests for monthly funding archives."""
    _validate_instrument(instrument)
    start_ms = _timestamp_to_ms(start_inclusive)
    end_ms = _timestamp_to_ms(end_exclusive)
    months = _month_starts(start_ms, end_ms)
    if not months:
        raise C7APublicDataError("historical funding interval must be positive")
    requests: list[PublicRequest] = []
    family = instrument.removesuffix("-SWAP")
    for offset in range(0, len(months), MAX_MONTHS_PER_HISTORY_REQUEST):
        chunk = months[offset : offset + MAX_MONTHS_PER_HISTORY_REQUEST]
        begin = chunk[0]
        end = min(end_ms - 1, _next_month_ms(chunk[-1]) - 1)
        request = PublicRequest(
            request_id=f"funding-manifest-{instrument}-{begin}-{end}",
            source_family="OKX_HISTORICAL_DATA_API",
            url=_api_url(
                host,
                HISTORICAL_DATA_PATH,
                {
                    "module": FUNDING_DOWNLOAD_MODULE,
                    "instType": "SWAP",
                    "instFamilyList": family,
                    "dateAggrType": FUNDING_DOWNLOAD_AGGREGATION,
                    "begin": str(begin),
                    "end": str(end),
                },
            ),
        )
        validate_public_request(request)
        requests.append(request)
    return tuple(requests)


def historical_download_request(url: str, *, request_id: str) -> PublicRequest:
    request = PublicRequest(
        request_id=request_id,
        source_family="OKX_HISTORICAL_DOWNLOAD",
        url=url,
        headers=(
            ("Accept", "application/zip,text/csv,application/octet-stream"),
            ("User-Agent", "ai-autonomous-trading-os/c7a-public-data"),
        ),
    )
    validate_public_request(request)
    return request


def fetch_raw(
    request: PublicRequest,
    *,
    opener=urlopen,
    collected_at: datetime | None = None,
) -> tuple[bytes, RawObject]:
    """Execute one safe public GET and return immutable raw bytes plus provenance."""
    validate_public_request(request)
    timestamp = collected_at or datetime.now(tz=UTC)
    if timestamp.tzinfo is None:
        raise C7APublicDataError("collection timestamp must be timezone-aware")
    http_request = Request(
        request.url,
        method="GET",
        headers={key: value for key, value in request.headers},
    )
    response = None
    try:
        response = opener(http_request, timeout=HTTP_TIMEOUT_SECONDS)
        final_url = (
            str(response.geturl()) if hasattr(response, "geturl") else request.url
        )
        final_parsed = urlparse(final_url)
        if final_parsed.scheme != "https" or not _official_host(final_parsed.hostname):
            raise C7APublicDataError("public response redirected outside official OKX")
        raw = response.read(MAX_RAW_BYTES + 1)
        media_type = str(
            response.headers.get("Content-Type", "application/octet-stream")
        )
        status = int(getattr(response, "status", 200))
    except C7APublicDataError:
        raise
    except Exception as exc:
        raise C7APublicDataError(
            f"public request failed: {request.request_id}: {exc}"
        ) from exc
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()
    if status != 200:
        raise C7APublicDataError(f"public request returned HTTP {status}")
    if not raw or len(raw) > MAX_RAW_BYTES:
        raise C7APublicDataError("public response is empty or exceeds the raw-byte cap")
    normalized_media_type = media_type.split(";", 1)[0].strip().lower()
    if request.source_family.endswith("_API") and normalized_media_type not in {
        "application/json",
        "text/json",
    }:
        raise C7APublicDataError("public API response media type is not JSON")
    provenance = RawObject(
        request_id=request.request_id,
        source_family=request.source_family,
        url=request.url,
        collected_at=timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        media_type=normalized_media_type,
    )
    return raw, provenance


def parse_json_object(raw: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise C7APublicDataError("OKX JSON response is invalid") from exc
    if not isinstance(payload, Mapping):
        raise C7APublicDataError("OKX JSON response must be an object")
    if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise C7APublicDataError(
            f"OKX response failed: code={payload.get('code')!r} msg={payload.get('msg')!r}"
        )
    return payload


def normalize_trade_candle_payload(
    payload: Mapping[str, Any],
    *,
    instrument: str,
) -> tuple[dict[str, str], ...]:
    """Normalize only completed, exact-hour OKX perpetual trade candles."""
    _validate_instrument(instrument)
    if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise C7APublicDataError(
            "trade-candle payload is not a successful OKX response"
        )
    normalized: list[dict[str, str]] = []
    seen: set[int] = set()
    for index, row in enumerate(payload["data"]):
        if (
            not isinstance(row, Sequence)
            or isinstance(row, (str, bytes))
            or len(row) != 9
        ):
            raise C7APublicDataError(
                f"trade-candle row {index} must contain nine fields"
            )
        ts = _millis(row[0], f"trade-candle row {index} timestamp")
        if ts % HOUR_MS:
            raise C7APublicDataError(
                "trade-candle timestamp is not aligned to an exact hour"
            )
        if ts in seen:
            raise C7APublicDataError("duplicate trade-candle timestamp")
        seen.add(ts)
        open_px = _exact_decimal(row[1], "trade open", positive=True)
        high_px = _exact_decimal(row[2], "trade high", positive=True)
        low_px = _exact_decimal(row[3], "trade low", positive=True)
        close_px = _exact_decimal(row[4], "trade close", positive=True)
        volumes = tuple(
            _exact_decimal(row[offset], label)
            for offset, label in (
                (5, "trade contract volume"),
                (6, "trade base volume"),
                (7, "trade quote volume"),
            )
        )
        if any(Decimal(value) < 0 for value in volumes):
            raise C7APublicDataError("trade-candle volume must be non-negative")
        if Decimal(high_px) < max(Decimal(open_px), Decimal(close_px), Decimal(low_px)):
            raise C7APublicDataError("trade-candle high is below another OHLC value")
        if Decimal(low_px) > min(Decimal(open_px), Decimal(close_px), Decimal(high_px)):
            raise C7APublicDataError("trade-candle low is above another OHLC value")
        if row[8] != "1":
            raise C7APublicDataError("unconfirmed trade candle is not admissible")
        normalized.append(
            {
                "instrument": instrument,
                "timestamp": _iso_millis(ts),
                "open": open_px,
                "high": high_px,
                "low": low_px,
                "close": close_px,
                "volume_contract": volumes[0],
                "volume_base": volumes[1],
                "volume_quote": volumes[2],
                "confirm": "1",
            }
        )
    normalized.sort(key=lambda item: item["timestamp"])
    return tuple(normalized)


def normalize_mark_price_payload(
    payload: Mapping[str, Any],
    *,
    instrument: str,
) -> tuple[dict[str, str], ...]:
    _validate_instrument(instrument)
    if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise C7APublicDataError("mark-price payload is not a successful OKX response")
    normalized: list[dict[str, str]] = []
    seen: set[int] = set()
    for index, row in enumerate(payload["data"]):
        if (
            not isinstance(row, Sequence)
            or isinstance(row, (str, bytes))
            or len(row) != 6
        ):
            raise C7APublicDataError(f"mark-price row {index} must contain six fields")
        ts = _millis(row[0], f"mark-price row {index} timestamp")
        if ts % HOUR_MS:
            raise C7APublicDataError(
                "mark-price timestamp is not aligned to an exact hour"
            )
        if ts in seen:
            raise C7APublicDataError("duplicate mark-price timestamp")
        seen.add(ts)
        open_px = _exact_decimal(row[1], "mark open", positive=True)
        high_px = _exact_decimal(row[2], "mark high", positive=True)
        low_px = _exact_decimal(row[3], "mark low", positive=True)
        close_px = _exact_decimal(row[4], "mark close", positive=True)
        if Decimal(high_px) < max(Decimal(open_px), Decimal(close_px), Decimal(low_px)):
            raise C7APublicDataError("mark-price high is below another OHLC value")
        if Decimal(low_px) > min(Decimal(open_px), Decimal(close_px), Decimal(high_px)):
            raise C7APublicDataError("mark-price low is above another OHLC value")
        if row[5] != "1":
            raise C7APublicDataError("unconfirmed mark-price candle is not admissible")
        normalized.append(
            {
                "instrument": instrument,
                "timestamp": _iso_millis(ts),
                "open": open_px,
                "high": high_px,
                "low": low_px,
                "close": close_px,
                "confirm": "1",
            }
        )
    normalized.sort(key=lambda item: item["timestamp"])
    return tuple(normalized)


def next_older_mark_request(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    host: str = "www.okx.com",
) -> PublicRequest:
    if not rows:
        raise C7APublicDataError("cannot paginate an empty mark-price page")
    oldest = min(_timestamp_to_ms(row.get("timestamp")) for row in rows)
    _millis(oldest, "mark timestamp")
    return build_mark_price_request(instrument, after_ms=oldest, host=host)


def _timestamp_to_ms(value: Any) -> int:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if not isinstance(value, str) or not value:
        raise C7APublicDataError("timestamp must be ISO-8601 or Unix milliseconds")
    if value.isdigit():
        return int(value)
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise C7APublicDataError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise C7APublicDataError("timestamp must be timezone-aware")
    return int(parsed.timestamp() * 1000)


def normalize_funding_api_payload(
    payload: Mapping[str, Any],
    *,
    instrument: str,
) -> tuple[dict[str, str], ...]:
    _validate_instrument(instrument)
    if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise C7APublicDataError("funding payload is not a successful OKX response")
    return _normalize_funding_records(payload["data"], instrument=instrument)


def normalize_funding_download_csv(
    raw: bytes,
    *,
    instrument: str,
    column_map: Mapping[str, str],
) -> tuple[dict[str, str], ...]:
    """Normalize an official OKX CSV using an explicit, reviewed column map.

    Required canonical keys are ``instrument``, ``funding_time`` and
    ``realized_rate``.  The explicit mapping prevents silent acceptance of a
    changed download schema.
    """
    _validate_instrument(instrument)
    required = {"instrument", "funding_time", "realized_rate"}
    if set(column_map) != required or any(not value for value in column_map.values()):
        raise C7APublicDataError(
            "funding CSV column map must contain exactly three keys"
        )
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise C7APublicDataError("funding CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise C7APublicDataError("funding CSV header is missing")
    expected_columns = set(column_map.values())
    if (
        len(reader.fieldnames) != len(expected_columns)
        or set(reader.fieldnames) != expected_columns
    ):
        raise C7APublicDataError("funding CSV columns do not match reviewed schema")
    records = []
    for index, row in enumerate(reader):
        if None in row:
            raise C7APublicDataError(f"funding CSV row {index} has extra fields")
        records.append(
            {
                "instId": row.get(column_map["instrument"]),
                "fundingTime": row.get(column_map["funding_time"]),
                "realizedRate": row.get(column_map["realized_rate"]),
            }
        )
    return _normalize_funding_records(records, instrument=instrument)


def normalize_funding_download(
    raw: bytes,
    *,
    instrument: str,
    column_map: Mapping[str, str],
) -> tuple[dict[str, str], ...]:
    """Normalize one official CSV or one-member ZIP without archive extraction."""
    if not raw.startswith(b"PK\x03\x04"):
        return normalize_funding_download_csv(
            raw, instrument=instrument, column_map=column_map
        )
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1:
                raise C7APublicDataError(
                    "funding ZIP must contain exactly one regular CSV member"
                )
            member = members[0]
            member_path = member.filename.replace("\\", "/")
            if (
                not member_path.lower().endswith(".csv")
                or "/" in member_path
                or member_path in {"", ".", ".."}
                or member.flag_bits & 0x1
                or (member.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise C7APublicDataError("funding ZIP member is unsafe or not CSV")
            if not 0 < member.file_size <= MAX_EXTRACTED_DOWNLOAD_BYTES:
                raise C7APublicDataError("funding ZIP CSV size is invalid")
            if (
                member.compress_size == 0
                or member.file_size > member.compress_size * 200
            ):
                raise C7APublicDataError("funding ZIP compression ratio is unsafe")
            csv_raw = archive.read(member)
    except C7APublicDataError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise C7APublicDataError("funding ZIP is invalid") from exc
    if len(csv_raw) != member.file_size:
        raise C7APublicDataError("funding ZIP member size changed while reading")
    return normalize_funding_download_csv(
        csv_raw, instrument=instrument, column_map=column_map
    )


def normalize_historical_funding_manifest(
    payload: Mapping[str, Any],
    *,
    instrument: str,
    start_inclusive: Any,
    end_exclusive: Any,
) -> tuple[dict[str, str], ...]:
    """Validate one OKX batch response and return its exact monthly archives."""
    _validate_instrument(instrument)
    if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise C7APublicDataError("historical funding manifest is not successful")
    expected_months = {
        datetime.fromtimestamp(value / 1000, tz=UTC).strftime("%Y-%m")
        for value in _month_starts(
            _timestamp_to_ms(start_inclusive), _timestamp_to_ms(end_exclusive)
        )
    }
    if not expected_months:
        raise C7APublicDataError("historical funding manifest interval is empty")
    family = instrument.removesuffix("-SWAP")
    filename_pattern = re.compile(
        rf"^{re.escape(instrument)}-fundingrates-(20\d{{2}}-\d{{2}})\.zip$"
    )
    archives: dict[str, dict[str, str]] = {}
    for result in payload["data"]:
        if not isinstance(result, Mapping) or result.get("dateAggrType") != "monthly":
            raise C7APublicDataError("historical funding aggregation drift")
        details = result.get("details")
        if not isinstance(details, list) or not details:
            raise C7APublicDataError("historical funding manifest has no details")
        _millis(result.get("ts"), "historical funding response timestamp")
        for detail in details:
            if (
                not isinstance(detail, Mapping)
                or detail.get("instId") not in {"", instrument}
                or detail.get("instFamily") != family
                or detail.get("instType") != "SWAP"
            ):
                raise C7APublicDataError("historical funding detail identity drift")
            range_start = _millis(
                detail.get("dateRangeStart"), "historical funding range start"
            )
            range_end = _millis(
                detail.get("dateRangeEnd"), "historical funding range end"
            )
            if range_start >= range_end:
                raise C7APublicDataError("historical funding detail range is invalid")
            groups = detail.get("groupDetails")
            if not isinstance(groups, list) or not groups:
                raise C7APublicDataError("historical funding detail has no files")
            for group in groups:
                if not isinstance(group, Mapping):
                    raise C7APublicDataError("historical funding file is not an object")
                filename = group.get("filename")
                url = group.get("url")
                date_value = group.get("dateTs", group.get("dataTs"))
                if not isinstance(filename, str) or not isinstance(url, str):
                    raise C7APublicDataError(
                        "historical funding file identity is missing"
                    )
                match = filename_pattern.fullmatch(filename)
                if match is None or urlparse(url).path.rsplit("/", 1)[-1] != filename:
                    raise C7APublicDataError("historical funding filename or URL drift")
                date_ms = _millis(date_value, "historical funding file month")
                utc8_month = datetime.fromtimestamp(
                    (date_ms + 8 * HOUR_MS) / 1000, tz=UTC
                )
                month_label = utc8_month.strftime("%Y-%m")
                if (
                    utc8_month.day != 1
                    or utc8_month.hour != 0
                    or utc8_month.minute != 0
                    or utc8_month.second != 0
                    or utc8_month.microsecond != 0
                    or match.group(1) != month_label
                ):
                    raise C7APublicDataError(
                        "historical funding file month is misaligned"
                    )
                if month_label not in expected_months:
                    continue
                if month_label in archives:
                    raise C7APublicDataError("duplicate historical funding month")
                historical_download_request(
                    url, request_id=f"funding-{instrument}-{month_label}"
                )
                archives[month_label] = {
                    "request_id": f"funding-{instrument}-{month_label}",
                    "instrument": instrument,
                    "url": url,
                }
    if set(archives) != expected_months:
        raise C7APublicDataError("historical funding monthly coverage is incomplete")
    return tuple(archives[month] for month in sorted(archives))


def _normalize_funding_records(
    records: Iterable[Mapping[str, Any]],
    *,
    instrument: str,
) -> tuple[dict[str, str], ...]:
    normalized: list[dict[str, str]] = []
    seen: set[int] = set()
    for index, row in enumerate(records):
        if not isinstance(row, Mapping):
            raise C7APublicDataError(f"funding row {index} must be an object")
        if row.get("instId") != instrument:
            raise C7APublicDataError(f"funding row {index} instrument mismatch")
        ts = _millis(row.get("fundingTime"), f"funding row {index} timestamp")
        if ts in seen:
            raise C7APublicDataError("duplicate funding settlement timestamp")
        seen.add(ts)
        realized = _exact_decimal(
            row.get("realizedRate"),
            f"funding row {index} realized rate",
            allow_exponent=True,
        )
        if not math.isfinite(float(realized)):
            raise C7APublicDataError("non-finite normalized funding rate")
        normalized.append(
            {
                "instrument": instrument,
                "funding_time": _iso_millis(ts),
                "realized_rate": realized,
            }
        )
    if not normalized:
        raise C7APublicDataError("funding source contains no rows")
    normalized.sort(key=lambda item: item["funding_time"])
    return tuple(normalized)


def select_exact_mark_interval(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    start_inclusive: Any,
    end_exclusive: Any,
) -> tuple[dict[str, Any], ...]:
    _validate_instrument(instrument)
    start_ms = _timestamp_to_ms(start_inclusive)
    end_ms = _timestamp_to_ms(end_exclusive)
    if start_ms >= end_ms or (end_ms - start_ms) % HOUR_MS:
        raise C7APublicDataError(
            "mark interval must be a positive whole number of hours"
        )
    by_time: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        if row.get("instrument") != instrument:
            raise C7APublicDataError("mark interval instrument mismatch")
        ts = _timestamp_to_ms(row.get("timestamp"))
        if ts in by_time:
            raise C7APublicDataError("duplicate mark row in interval selection")
        by_time[ts] = row
    expected = tuple(range(start_ms, end_ms, HOUR_MS))
    expected_set = set(expected)
    selected: list[dict[str, Any]] = []
    for ts in expected:
        row = by_time.get(ts)
        if row is None:
            raise C7APublicDataError(f"missing exact mark hour: {_iso_millis(ts)}")
        close = _exact_decimal(row.get("close"), "selected mark close", positive=True)
        selected.append({"timestamp": _iso_millis(ts), "close": close})
    extra = [ts for ts in by_time if start_ms <= ts < end_ms and ts not in expected_set]
    if extra:
        raise C7APublicDataError("unexpected off-grid mark row")
    return tuple(selected)


def select_exact_trade_interval(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    start_inclusive: Any,
    end_exclusive: Any,
) -> tuple[dict[str, Any], ...]:
    """Select a gap-free exact-hour trade-candle interval without overshoot rows."""
    _validate_instrument(instrument)
    start_ms = _timestamp_to_ms(start_inclusive)
    end_ms = _timestamp_to_ms(end_exclusive)
    if start_ms >= end_ms or (end_ms - start_ms) % HOUR_MS:
        raise C7APublicDataError(
            "trade interval must be a positive whole number of hours"
        )
    by_time: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        if row.get("instrument") != instrument:
            raise C7APublicDataError("trade interval instrument mismatch")
        ts = _timestamp_to_ms(row.get("timestamp"))
        if ts in by_time:
            raise C7APublicDataError("duplicate trade row in interval selection")
        by_time[ts] = row
    expected = tuple(range(start_ms, end_ms, HOUR_MS))
    expected_set = set(expected)
    selected: list[dict[str, Any]] = []
    for ts in expected:
        row = by_time.get(ts)
        if row is None:
            raise C7APublicDataError(f"missing exact trade hour: {_iso_millis(ts)}")
        selected.append(
            {
                "timestamp": _iso_millis(ts),
                "open": _exact_decimal(
                    row.get("open"), "selected trade open", positive=True
                ),
                "close": _exact_decimal(
                    row.get("close"), "selected trade close", positive=True
                ),
            }
        )
    extra = [ts for ts in by_time if start_ms <= ts < end_ms and ts not in expected_set]
    if extra:
        raise C7APublicDataError("unexpected off-grid trade row")
    return tuple(selected)


def select_funding_interval(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    start_inclusive: Any,
    end_exclusive: Any,
) -> tuple[dict[str, Any], ...]:
    _validate_instrument(instrument)
    start_ms = _timestamp_to_ms(start_inclusive)
    end_ms = _timestamp_to_ms(end_exclusive)
    if start_ms >= end_ms:
        raise C7APublicDataError("funding interval must be positive")
    selected: list[dict[str, Any]] = []
    seen: set[int] = set()
    for row in rows:
        if row.get("instrument") != instrument:
            raise C7APublicDataError("funding interval instrument mismatch")
        ts = _timestamp_to_ms(row.get("funding_time"))
        if ts in seen:
            raise C7APublicDataError("duplicate funding row in interval selection")
        seen.add(ts)
        if start_ms <= ts < end_ms:
            selected.append(
                {
                    "funding_time": _iso_millis(ts),
                    "realized_rate": _exact_decimal(
                        row.get("realized_rate"),
                        "selected realized funding rate",
                    ),
                }
            )
    if not selected:
        raise C7APublicDataError("funding interval contains no settlements")
    selected.sort(key=lambda item: item["funding_time"])
    return tuple(selected)


def historical_execution_metadata(
    *,
    source_family: str,
    collected_at: str,
) -> dict[str, Any]:
    metadata = {
        "stage": "C7A_HISTORICAL_VALIDATION",
        "source_kind": "OFFICIAL_PUBLIC_OKX",
        "source_family": source_family,
        "authenticated": False,
        "contains_account_data": False,
        "contains_order_data": False,
        "private_api": False,
        "paper_side_effect": False,
        "live_state": "LIVE_FORBIDDEN",
        "collected_at": collected_at,
    }
    try:
        assert_official_public_metadata(metadata)
    except C7AHistoricalScheduleError as exc:
        raise C7APublicDataError(str(exc)) from exc
    return metadata
