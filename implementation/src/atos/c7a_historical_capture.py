"""Durable, fail-closed capture orchestration for C7A historical validation.

The module may access only official unauthenticated OKX public surfaces. It
persists immutable raw bytes before normalization, records requested and final
URLs, rejects API redirect drift, paginates mark history with strict progress
checks, and emits a recursive SHA-256 manifest. It has no account, order, paper,
shadow side-effect, or live path.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlparse
from urllib.request import Request, urlopen

from atos.c7a_contract import INSTRUMENTS
from atos.c7a_historical_schedule import (
    HISTORICAL_WINDOWS,
    required_source_bounds,
)
from atos.c7a_okx_public_data import (
    HOUR_MS,
    HTTP_TIMEOUT_SECONDS,
    MAX_RAW_BYTES,
    C7APublicDataError,
    PublicRequest,
    build_mark_price_request,
    historical_download_request,
    normalize_funding_download_csv,
    normalize_mark_price_payload,
    parse_json_object,
    select_exact_mark_interval,
    select_funding_interval,
    validate_public_request,
)

SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
API_FAMILIES = frozenset(
    {
        "OKX_HISTORY_MARK_PRICE_CANDLES_API",
        "OKX_FUNDING_RATE_HISTORY_API",
    }
)
MAX_FUNDING_SETTLEMENT_GAP_MS = 8 * HOUR_MS
CAPTURE_PLAN_KEYS = frozenset(
    {
        "window_ids",
        "instruments",
        "funding_start_inclusive",
        "mark_start_inclusive",
        "scored_end_exclusive",
    }
)


class C7AHistoricalCaptureError(RuntimeError):
    """Raised when historical capture cannot be proven complete and safe."""


@dataclass(frozen=True)
class CaptureRecord:
    request_id: str
    source_family: str
    requested_url: str
    final_url: str
    collected_at: str
    media_type: str
    size: int
    sha256: str
    relative_path: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FundingDownloadSpec:
    request_id: str
    instrument: str
    url: str
    column_map: Mapping[str, str]

    def request(self) -> PublicRequest:
        if self.instrument not in INSTRUMENTS:
            raise C7AHistoricalCaptureError(
                f"unsupported funding-download instrument: {self.instrument!r}"
            )
        try:
            return historical_download_request(self.url, request_id=self.request_id)
        except C7APublicDataError as exc:
            raise C7AHistoricalCaptureError(str(exc)) from exc


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        raise C7AHistoricalCaptureError("capture timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _timestamp_ms(value: Any) -> int:
    if not isinstance(value, str) or not value:
        raise C7AHistoricalCaptureError("normalized timestamp must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise C7AHistoricalCaptureError(f"invalid normalized timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise C7AHistoricalCaptureError("normalized timestamp must be timezone-aware")
    return int(parsed.timestamp() * 1000)


def _iso_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace(
        "+00:00", "Z"
    )


def _canonical_interval(start_inclusive: str, end_exclusive: str) -> tuple[str, str]:
    start_ms = _timestamp_ms(start_inclusive)
    end_ms = _timestamp_ms(end_exclusive)
    if start_ms >= end_ms:
        raise C7AHistoricalCaptureError("capture interval must be positive")
    return _iso_ms(start_ms), _iso_ms(end_ms)


def _validated_capture_plan(capture_plan: Mapping[str, Any]) -> dict[str, Any]:
    if set(capture_plan) != CAPTURE_PLAN_KEYS:
        raise C7AHistoricalCaptureError("capture plan key set is incomplete or drifted")
    window_ids = capture_plan.get("window_ids")
    if (
        not isinstance(window_ids, list)
        or not window_ids
        or any(not isinstance(item, str) or not SAFE_ID.fullmatch(item) for item in window_ids)
        or len(window_ids) != len(set(window_ids))
    ):
        raise C7AHistoricalCaptureError("capture plan window IDs are invalid")
    if capture_plan.get("instruments") != list(INSTRUMENTS):
        raise C7AHistoricalCaptureError("capture plan instrument set or order drifted")
    funding_start, end = _canonical_interval(
        str(capture_plan.get("funding_start_inclusive", "")),
        str(capture_plan.get("scored_end_exclusive", "")),
    )
    mark_start, mark_end = _canonical_interval(
        str(capture_plan.get("mark_start_inclusive", "")),
        str(capture_plan.get("scored_end_exclusive", "")),
    )
    if mark_end != end:
        raise C7AHistoricalCaptureError("capture plan end boundaries do not match")
    return {
        "window_ids": list(window_ids),
        "instruments": list(INSTRUMENTS),
        "funding_start_inclusive": funding_start,
        "mark_start_inclusive": mark_start,
        "scored_end_exclusive": end,
    }


def _assert_complete_funding_interval(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    start_inclusive: str,
    end_exclusive: str,
) -> None:
    start_ms = _timestamp_ms(start_inclusive)
    end_ms = _timestamp_ms(end_exclusive)
    times = tuple(_timestamp_ms(row.get("funding_time")) for row in rows)
    if not times or times != tuple(sorted(times)) or len(times) != len(set(times)):
        raise C7AHistoricalCaptureError(
            f"funding settlements are empty, duplicate, or unordered: {instrument}"
        )
    if times[0] != start_ms:
        raise C7AHistoricalCaptureError(
            f"funding settlement coverage does not start at the requested boundary: {instrument}"
        )
    gaps = (
        *(right - left for left, right in pairwise(times)),
        end_ms - times[-1],
    )
    if any(gap < 0 or gap > MAX_FUNDING_SETTLEMENT_GAP_MS for gap in gaps):
        raise C7AHistoricalCaptureError(
            f"funding settlement coverage gap exceeds eight hours: {instrument}"
        )


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_DIRECTORY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _api_semantics(url: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    parsed = urlparse(url)
    return parsed.path, tuple(sorted(parse_qsl(parsed.query, keep_blank_values=True)))


def fetch_raw_strict(
    request: PublicRequest,
    *,
    opener=urlopen,
    collected_at: datetime | None = None,
) -> tuple[bytes, CaptureRecord]:
    """Fetch one public object and preserve redirect-aware provenance.

    API redirects may move between approved OKX API hosts but may not change the
    endpoint path or any query parameter. Historical-download redirects are
    revalidated as official OKX download requests and both URLs are retained.
    """
    try:
        validate_public_request(request)
    except C7APublicDataError as exc:
        raise C7AHistoricalCaptureError(str(exc)) from exc

    stamp = collected_at or datetime.now(tz=UTC)
    if stamp.tzinfo is None:
        raise C7AHistoricalCaptureError("capture timestamp must be timezone-aware")

    http_request = Request(
        request.url,
        method="GET",
        headers={key: value for key, value in request.headers},
    )
    response = None
    try:
        response = opener(http_request, timeout=HTTP_TIMEOUT_SECONDS)
        final_url = str(response.geturl()) if hasattr(response, "geturl") else request.url
        final_request = PublicRequest(
            request_id=request.request_id,
            source_family=request.source_family,
            url=final_url,
            method=request.method,
            headers=request.headers,
        )
        validate_public_request(final_request)
        if request.source_family in API_FAMILIES and (
            _api_semantics(final_url) != _api_semantics(request.url)
        ):
            raise C7AHistoricalCaptureError(
                "public API redirect changed endpoint or query semantics"
            )
        raw = response.read(MAX_RAW_BYTES + 1)
        status = int(getattr(response, "status", 200))
        media_type = str(
            response.headers.get("Content-Type", "application/octet-stream")
        ).split(";", 1)[0].strip().lower()
    except C7AHistoricalCaptureError:
        raise
    except C7APublicDataError as exc:
        raise C7AHistoricalCaptureError(str(exc)) from exc
    except Exception as exc:
        raise C7AHistoricalCaptureError(
            f"public capture failed: {request.request_id}: {exc}"
        ) from exc
    finally:
        close = getattr(response, "close", None)
        if callable(close):
            close()

    if status != 200:
        raise C7AHistoricalCaptureError(f"public capture returned HTTP {status}")
    if not raw or len(raw) > MAX_RAW_BYTES:
        raise C7AHistoricalCaptureError(
            "public capture is empty or exceeds the raw-byte cap"
        )
    if request.source_family in API_FAMILIES and media_type not in {
        "application/json",
        "text/json",
    }:
        raise C7AHistoricalCaptureError("public API capture is not JSON")

    record = CaptureRecord(
        request_id=request.request_id,
        source_family=request.source_family,
        requested_url=request.url,
        final_url=final_url,
        collected_at=_iso(stamp),
        media_type=media_type,
        size=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
        relative_path="",
    )
    return raw, record


class CapturePackage:
    """One immutable historical capture package."""

    def __init__(self, root: Path):
        self.root = Path(root)
        if self.root.exists():
            raise C7AHistoricalCaptureError(
                f"capture package already exists: {self.root}"
            )
        self.root.mkdir(parents=True, exist_ok=False, mode=0o700)
        _fsync_directory(self.root.parent)
        self._records: list[CaptureRecord] = []
        self._request_ids: set[str] = set()
        self._normalized_series: dict[tuple[str, str], tuple[str, str]] = {}
        self._finalized = False

    def _assert_open(self) -> None:
        if self._finalized:
            raise C7AHistoricalCaptureError("capture package is already finalized")

    def _safe_relative(self, relative: str) -> Path:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise C7AHistoricalCaptureError("capture path must remain inside package")
        return path

    def _write_bytes(self, relative: str, data: bytes) -> None:
        self._assert_open()
        path = self.root / self._safe_relative(relative)
        if path.exists():
            raise C7AHistoricalCaptureError(f"capture file already exists: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.tmp")
        if temporary.exists():
            raise C7AHistoricalCaptureError(
                f"stale capture temporary exists: {temporary.name}"
            )
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise C7AHistoricalCaptureError(
                f"capture file already exists: {relative}"
            ) from exc
        temporary.unlink()
        _fsync_directory(path.parent)

    def write_json(self, relative: str, payload: Any) -> None:
        data = (
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")
        self._write_bytes(relative, data)

    def retain_normalized_series(
        self,
        *,
        series_type: str,
        instrument: str,
        start_inclusive: str,
        end_exclusive: str,
        rows: Sequence[Mapping[str, Any]],
    ) -> None:
        self._assert_open()
        key = (series_type, instrument)
        if series_type not in {"marks", "funding"} or instrument not in INSTRUMENTS:
            raise C7AHistoricalCaptureError("unsupported normalized series identity")
        if key in self._normalized_series:
            raise C7AHistoricalCaptureError("normalized series is already retained")
        if not rows:
            raise C7AHistoricalCaptureError("normalized series contains no rows")
        bounds = _canonical_interval(start_inclusive, end_exclusive)
        self.write_json(
            f"normalized/{series_type}/{instrument}.json",
            list(rows),
        )
        self._normalized_series[key] = bounds

    def retain_raw(self, raw: bytes, record: CaptureRecord) -> CaptureRecord:
        self._assert_open()
        if not SAFE_ID.fullmatch(record.request_id):
            raise C7AHistoricalCaptureError("unsafe capture request ID")
        if record.request_id in self._request_ids:
            raise C7AHistoricalCaptureError(
                f"duplicate capture request ID: {record.request_id}"
            )
        try:
            requested = PublicRequest(
                record.request_id,
                record.source_family,
                record.requested_url,
            )
            final = PublicRequest(
                record.request_id,
                record.source_family,
                record.final_url,
            )
            validate_public_request(requested)
            validate_public_request(final)
        except C7APublicDataError as exc:
            raise C7AHistoricalCaptureError(str(exc)) from exc
        if record.source_family in API_FAMILIES and (
            _api_semantics(record.requested_url) != _api_semantics(record.final_url)
        ):
            raise C7AHistoricalCaptureError(
                "retained API record changed endpoint or query semantics"
            )
        if len(raw) != record.size or hashlib.sha256(raw).hexdigest() != record.sha256:
            raise C7AHistoricalCaptureError("raw capture provenance mismatch")
        relative = f"raw/{record.source_family.lower()}/{record.request_id}.bin"
        self._write_bytes(relative, raw)
        retained = CaptureRecord(
            **{
                **record.to_dict(),
                "relative_path": relative,
            }
        )
        self._records.append(retained)
        self._request_ids.add(record.request_id)
        return retained

    @property
    def records(self) -> tuple[CaptureRecord, ...]:
        return tuple(self._records)

    def finalize(
        self,
        *,
        implementation_sha: str,
        capture_plan: Mapping[str, Any],
    ) -> dict[str, Any]:
        self._assert_open()
        if not re.fullmatch(r"[0-9a-f]{40}", implementation_sha):
            raise C7AHistoricalCaptureError("implementation SHA must be exact")
        if not self._records:
            raise C7AHistoricalCaptureError("capture package contains no raw objects")
        plan = _validated_capture_plan(capture_plan)
        expected_series = {
            ("marks", instrument): (
                plan["mark_start_inclusive"],
                plan["scored_end_exclusive"],
            )
            for instrument in INSTRUMENTS
        }
        expected_series.update(
            {
                ("funding", instrument): (
                    plan["funding_start_inclusive"],
                    plan["scored_end_exclusive"],
                )
                for instrument in INSTRUMENTS
            }
        )
        if self._normalized_series != expected_series:
            raise C7AHistoricalCaptureError(
                "capture package normalized series are incomplete or bound to the wrong interval"
            )
        index = {
            "schema_version": 1,
            "stage": "C7A_HISTORICAL_CAPTURE",
            "implementation_sha": implementation_sha,
            "capture_plan": plan,
            "records": [record.to_dict() for record in self._records],
            "authenticated": False,
            "contains_account_data": False,
            "contains_order_data": False,
            "paper_side_effect": False,
            "live_state": "LIVE_FORBIDDEN",
        }
        self.write_json("capture_index.json", index)

        files: list[dict[str, Any]] = []
        for path in sorted(item for item in self.root.rglob("*") if item.is_file()):
            relative = path.relative_to(self.root).as_posix()
            if relative == "manifest.json":
                continue
            data = path.read_bytes()
            files.append(
                {
                    "path": relative,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
            )
        manifest = {
            "schema_version": 1,
            "stage": "C7A_HISTORICAL_CAPTURE_PACKAGE",
            "implementation_sha": implementation_sha,
            "file_count": len(files),
            "files": files,
            "real_public_data": True,
            "authenticated": False,
            "contains_account_data": False,
            "contains_order_data": False,
            "economic_result": False,
            "paper_side_effect": False,
            "live_state": "LIVE_FORBIDDEN",
        }
        self.write_json("manifest.json", manifest)
        self._finalized = True
        return manifest


def _retain_response(
    package: CapturePackage,
    request: PublicRequest,
    raw: bytes,
    record: CaptureRecord,
) -> CaptureRecord:
    if (
        record.request_id != request.request_id
        or record.source_family != request.source_family
        or record.requested_url != request.url
    ):
        raise C7AHistoricalCaptureError(
            "capture transport provenance does not match the issued request"
        )
    return package.retain_raw(raw, record)


PageFetcher = Callable[[PublicRequest], tuple[bytes, CaptureRecord]]


def h1_h5_capture_plan() -> dict[str, Any]:
    first = required_source_bounds(HISTORICAL_WINDOWS[0].window_id)
    last = required_source_bounds(HISTORICAL_WINDOWS[-1].window_id)
    return {
        "window_ids": [window.window_id for window in HISTORICAL_WINDOWS],
        "instruments": list(INSTRUMENTS),
        "funding_start_inclusive": first["funding_start_inclusive"],
        "mark_start_inclusive": first["mark_start_inclusive"],
        "scored_end_exclusive": last["scored_end_exclusive"],
    }


def capture_mark_range(
    package: CapturePackage,
    *,
    instrument: str,
    start_inclusive: str,
    end_exclusive: str,
    fetch_page: PageFetcher = fetch_raw_strict,
    host: str = "www.okx.com",
    max_pages: int = 1000,
) -> tuple[dict[str, Any], ...]:
    """Capture complete hourly mark closes by paginating strictly backward."""
    if instrument not in INSTRUMENTS:
        raise C7AHistoricalCaptureError(f"unsupported instrument: {instrument!r}")
    if type(max_pages) is not int or not 1 <= max_pages <= 10_000:
        raise C7AHistoricalCaptureError("max_pages must be an integer from 1 to 10000")
    start_ms = _timestamp_ms(start_inclusive)
    end_ms = _timestamp_ms(end_exclusive)
    if start_ms >= end_ms:
        raise C7AHistoricalCaptureError("mark capture interval must be positive")

    cursor = end_ms
    combined: dict[str, dict[str, str]] = {}
    pages = 0
    while True:
        if pages >= max_pages:
            raise C7AHistoricalCaptureError("mark pagination exceeded max_pages")
        request = build_mark_price_request(instrument, after_ms=cursor, host=host)
        raw, record = fetch_page(request)
        _retain_response(package, request, raw, record)
        try:
            payload = parse_json_object(raw)
            rows = normalize_mark_price_payload(payload, instrument=instrument)
        except C7APublicDataError as exc:
            raise C7AHistoricalCaptureError(str(exc)) from exc
        if not rows:
            raise C7AHistoricalCaptureError("mark pagination returned an empty page")
        oldest = min(_timestamp_ms(row["timestamp"]) for row in rows)
        newest = max(_timestamp_ms(row["timestamp"]) for row in rows)
        if newest >= cursor or oldest >= cursor:
            raise C7AHistoricalCaptureError("mark pagination did not move strictly older")
        for row in rows:
            timestamp = str(row["timestamp"])
            if timestamp in combined:
                raise C7AHistoricalCaptureError(
                    f"duplicate mark timestamp across pages: {timestamp}"
                )
            combined[timestamp] = dict(row)
        pages += 1
        if oldest <= start_ms:
            break
        cursor = oldest

    try:
        selected = select_exact_mark_interval(
            tuple(combined.values()),
            instrument=instrument,
            start_inclusive=start_inclusive,
            end_exclusive=end_exclusive,
        )
    except C7APublicDataError as exc:
        raise C7AHistoricalCaptureError(str(exc)) from exc
    package.retain_normalized_series(
        series_type="marks",
        instrument=instrument,
        start_inclusive=start_inclusive,
        end_exclusive=end_exclusive,
        rows=selected,
    )
    return selected


def capture_funding_downloads(
    package: CapturePackage,
    *,
    specs: Sequence[FundingDownloadSpec],
    start_inclusive: str,
    end_exclusive: str,
    fetch_object: PageFetcher = fetch_raw_strict,
) -> dict[str, tuple[dict[str, Any], ...]]:
    """Capture reviewed official funding downloads and select the exact interval."""
    if not specs:
        raise C7AHistoricalCaptureError("funding download inventory is empty")
    request_ids = [spec.request_id for spec in specs]
    if any(not SAFE_ID.fullmatch(request_id) for request_id in request_ids):
        raise C7AHistoricalCaptureError("unsafe funding-download request ID")
    if len(set(request_ids)) != len(request_ids):
        raise C7AHistoricalCaptureError("funding download request IDs must be unique")
    supplied_instruments = {spec.instrument for spec in specs}
    if supplied_instruments != set(INSTRUMENTS):
        raise C7AHistoricalCaptureError(
            "funding download inventory must cover both C7A instruments"
        )
    rows_by_instrument: dict[str, dict[str, dict[str, str]]] = {
        instrument: {} for instrument in INSTRUMENTS
    }
    for spec in specs:
        request = spec.request()
        raw, record = fetch_object(request)
        _retain_response(package, request, raw, record)
        try:
            rows = normalize_funding_download_csv(
                raw,
                instrument=spec.instrument,
                column_map=spec.column_map,
            )
        except C7APublicDataError as exc:
            raise C7AHistoricalCaptureError(str(exc)) from exc
        target = rows_by_instrument[spec.instrument]
        for row in rows:
            timestamp = str(row["funding_time"])
            if timestamp in target:
                raise C7AHistoricalCaptureError(
                    f"duplicate funding settlement across downloads: "
                    f"{spec.instrument} {timestamp}"
                )
            target[timestamp] = dict(row)

    result: dict[str, tuple[dict[str, Any], ...]] = {}
    for instrument in INSTRUMENTS:
        if not rows_by_instrument[instrument]:
            raise C7AHistoricalCaptureError(
                f"no funding downloads supplied for {instrument}"
            )
        try:
            selected = select_funding_interval(
                tuple(rows_by_instrument[instrument].values()),
                instrument=instrument,
                start_inclusive=start_inclusive,
                end_exclusive=end_exclusive,
            )
        except C7APublicDataError as exc:
            raise C7AHistoricalCaptureError(str(exc)) from exc
        _assert_complete_funding_interval(
            selected,
            instrument=instrument,
            start_inclusive=start_inclusive,
            end_exclusive=end_exclusive,
        )
        package.retain_normalized_series(
            series_type="funding",
            instrument=instrument,
            start_inclusive=start_inclusive,
            end_exclusive=end_exclusive,
            rows=selected,
        )
        result[instrument] = selected
    return result
