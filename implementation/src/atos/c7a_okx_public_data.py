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
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from urllib.request import Request, urlopen

from atos.c7a_contract import INSTRUMENTS
from atos.c7a_historical_schedule import (
    C7AHistoricalScheduleError,
    assert_official_public_metadata,
)


class C7APublicDataError(RuntimeError):
    """Raised when public acquisition or normalization cannot be proven safe."""


API_HOSTS = frozenset({"www.okx.com", "us.okx.com", "eea.okx.com"})
MARK_HISTORY_PATH = "/api/v5/market/history-mark-price-candles"
FUNDING_HISTORY_PATH = "/api/v5/public/funding-rate-history"
ALLOWED_API_PATHS = frozenset({MARK_HISTORY_PATH, FUNDING_HISTORY_PATH})
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
HTTP_TIMEOUT_SECONDS = 30
MARK_PAGE_LIMIT = 100
FUNDING_PAGE_LIMIT = 400
HOUR_MS = 3_600_000


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


def _exact_decimal(value: Any, label: str, *, positive: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise C7APublicDataError(f"{label} must be a non-empty exact decimal string")
    if "e" in value.lower():
        raise C7APublicDataError(f"{label} must not use exponent notation")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        raise C7APublicDataError(f"{label} is not an exact decimal") from exc
    if not parsed.is_finite() or (positive and parsed <= 0):
        qualifier = "positive finite" if positive else "finite"
        raise C7APublicDataError(f"{label} must be {qualifier}")
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
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")


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
) -> None:
    query = _query_map(request.url)
    if set(query) - allowed_keys or not required_keys.issubset(query):
        raise C7APublicDataError("public API query contract drift")
    if query.get("instId") not in INSTRUMENTS:
        raise C7APublicDataError("public API instrument drift")
    if "after" in query and "before" in query:
        raise C7APublicDataError("public API pagination may not use after and before together")
    for key in ("after", "before"):
        if key in query:
            _millis(query[key], key)
    if expected_path == MARK_HISTORY_PATH:
        if query.get("bar") != "1H" or query.get("limit") != str(MARK_PAGE_LIMIT):
            raise C7APublicDataError("mark-price API bar or limit drift")
    elif expected_path == FUNDING_HISTORY_PATH:
        if query.get("limit") != str(FUNDING_PAGE_LIMIT):
            raise C7APublicDataError("funding API limit drift")


def validate_public_request(request: PublicRequest) -> None:
    if not request.request_id or request.method != "GET":
        raise C7APublicDataError("public request requires a non-empty ID and GET method")
    if request.source_family not in {
        "OKX_HISTORY_MARK_PRICE_CANDLES_API",
        "OKX_FUNDING_RATE_HISTORY_API",
        "OKX_HISTORICAL_DOWNLOAD",
    }:
        raise C7APublicDataError("unsupported C7A public source family")
    parsed = urlparse(request.url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise C7APublicDataError("public request must use HTTPS")
    if parsed.username or parsed.password or parsed.fragment:
        raise C7APublicDataError("public request URL contains credentials or a fragment")
    if not _official_host(parsed.hostname):
        raise C7APublicDataError("public request must target an official OKX host")
    if any(marker in parsed.path.lower() for marker in PRIVATE_PATH_MARKERS):
        raise C7APublicDataError("private or account endpoint is forbidden")
    query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
    if query_keys & PROHIBITED_QUERY_KEYS:
        raise C7APublicDataError("public request URL contains a credential query")
    header_keys = {key.lower() for key, _ in request.headers}
    if header_keys & PROHIBITED_HEADER_KEYS:
        raise C7APublicDataError("public request contains authentication material")
    if request.source_family == "OKX_HISTORY_MARK_PRICE_CANDLES_API":
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
    else:
        if parsed.path.startswith("/api/"):
            raise C7APublicDataError("historical download source may not masquerade as an API")


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
        final_url = str(response.geturl()) if hasattr(response, "geturl") else request.url
        final_parsed = urlparse(final_url)
        if final_parsed.scheme != "https" or not _official_host(final_parsed.hostname):
            raise C7APublicDataError("public response redirected outside official OKX")
        raw = response.read(MAX_RAW_BYTES + 1)
        media_type = str(response.headers.get("Content-Type", "application/octet-stream"))
        status = int(getattr(response, "status", 200))
    except C7APublicDataError:
        raise
    except Exception as exc:
        raise C7APublicDataError(f"public request failed: {request.request_id}: {exc}") from exc
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
        if not isinstance(row, Sequence) or isinstance(row, (str, bytes)) or len(row) != 6:
            raise C7APublicDataError(f"mark-price row {index} must contain six fields")
        ts = _millis(row[0], f"mark-price row {index} timestamp")
        if ts % HOUR_MS:
            raise C7APublicDataError("mark-price timestamp is not aligned to an exact hour")
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
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
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
        raise C7APublicDataError("funding CSV column map must contain exactly three keys")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise C7APublicDataError("funding CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        raise C7APublicDataError("funding CSV header is missing")
    missing = set(column_map.values()) - set(reader.fieldnames)
    if missing:
        raise C7APublicDataError(f"funding CSV columns missing: {sorted(missing)}")
    records = [
        {
            "instId": row.get(column_map["instrument"]),
            "fundingTime": row.get(column_map["funding_time"]),
            "realizedRate": row.get(column_map["realized_rate"]),
        }
        for row in reader
    ]
    return _normalize_funding_records(records, instrument=instrument)


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
        raise C7APublicDataError("mark interval must be a positive whole number of hours")
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
