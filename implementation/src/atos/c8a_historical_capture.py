"""C8A wrapper around the reviewed official-public OKX capture primitives."""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable, Mapping, Sequence
from itertools import pairwise
from typing import Any
from urllib.parse import parse_qsl, urlparse

from atos.c7a_historical_capture import (
    C7AHistoricalCaptureError,
    CapturePackage,
    CaptureRecord,
    FundingDownloadSpec,
    capture_mark_range,
    capture_trade_range,
    fetch_raw_strict,
)
from atos.c7a_okx_public_data import (
    FUNDING_ARCHIVE_COLUMNS,
    HOUR_MS,
    C7APublicDataError,
    PublicRequest,
    build_historical_funding_manifest_requests,
    normalize_funding_download,
    normalize_historical_funding_manifest,
    parse_json_object,
    select_funding_interval,
)
from atos.c8a_contract import INSTRUMENTS
from atos.c8a_historical_schedule import h1_h5_capture_plan

EXACT_SHA = re.compile(r"[0-9a-f]{40}")


class C8AHistoricalCaptureError(RuntimeError):
    """Raised when a C8A package cannot prove exact public-data custody."""


PageFetcher = Callable[[PublicRequest], tuple[bytes, CaptureRecord]]
Sleeper = Callable[[float], None]
MAX_FUNDING_GAP_MS = 8 * HOUR_MS + 60_000
FUNDING_REQUEST_PAUSE_SECONDS = 0.5


def _timestamp_ms(value: Any) -> int:
    from datetime import datetime

    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise C8AHistoricalCaptureError(
            f"invalid funding timestamp: {value!r}"
        ) from exc
    if stamp.tzinfo is None:
        raise C8AHistoricalCaptureError("funding timestamp must be timezone-aware")
    return int(stamp.timestamp() * 1000)


def _pause(value: float) -> float:
    if isinstance(value, bool):
        raise C8AHistoricalCaptureError("request pause must be a number")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C8AHistoricalCaptureError("request pause must be a number") from exc
    if not 0 <= result <= 5:
        raise C8AHistoricalCaptureError(
            "request pause must be between zero and five seconds"
        )
    return result


def _retain(
    package: CapturePackage,
    request: PublicRequest,
    raw: bytes,
    record: CaptureRecord,
) -> None:
    if (
        record.request_id != request.request_id
        or record.source_family != request.source_family
        or record.requested_url != request.url
    ):
        raise C8AHistoricalCaptureError("funding capture transport provenance mismatch")
    package.retain_raw(raw, record)


def _assert_complete_funding_interval(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    start_inclusive: str,
    end_exclusive: str,
) -> None:
    start = _timestamp_ms(start_inclusive)
    end = _timestamp_ms(end_exclusive)
    stamps = tuple(_timestamp_ms(row.get("funding_time")) for row in rows)
    if not stamps or stamps != tuple(sorted(stamps)) or len(stamps) != len(set(stamps)):
        raise C8AHistoricalCaptureError(
            f"funding settlements are empty, duplicate, or unordered: {instrument}"
        )
    gaps = (
        stamps[0] - start,
        *(right - left for left, right in pairwise(stamps)),
        end - stamps[-1],
    )
    if any(gap < 0 or gap > MAX_FUNDING_GAP_MS for gap in gaps):
        raise C8AHistoricalCaptureError(
            f"funding coverage gap exceeds eight hours plus tolerance: {instrument}"
        )


def capture_funding_downloads(
    package: CapturePackage,
    *,
    specs: Sequence[FundingDownloadSpec],
    start_inclusive: str,
    end_exclusive: str,
    fetch_object: PageFetcher = fetch_raw_strict,
    download_pause_seconds: float = FUNDING_REQUEST_PAUSE_SECONDS,
    sleeper: Sleeper = time.sleep,
) -> dict[str, tuple[dict[str, Any], ...]]:
    if not specs or {spec.instrument for spec in specs} != set(INSTRUMENTS):
        raise C8AHistoricalCaptureError(
            "funding inventory must cover both C8A instruments"
        )
    request_ids = [spec.request_id for spec in specs]
    if len(request_ids) != len(set(request_ids)):
        raise C8AHistoricalCaptureError("funding request IDs must be unique")
    pause = _pause(download_pause_seconds)
    combined: dict[str, dict[str, dict[str, Any]]] = {
        instrument: {} for instrument in INSTRUMENTS
    }
    for index, spec in enumerate(specs):
        if index and pause:
            sleeper(pause)
        request = spec.request()
        raw, record = fetch_object(request)
        _retain(package, request, raw, record)
        try:
            rows = normalize_funding_download(
                raw, instrument=spec.instrument, column_map=spec.column_map
            )
        except C7APublicDataError as exc:
            raise C8AHistoricalCaptureError(str(exc)) from exc
        for row in rows:
            stamp = str(row["funding_time"])
            if stamp in combined[spec.instrument]:
                raise C8AHistoricalCaptureError(
                    f"duplicate funding settlement across downloads: {spec.instrument} {stamp}"
                )
            combined[spec.instrument][stamp] = dict(row)
    output = {}
    for instrument in INSTRUMENTS:
        try:
            selected = select_funding_interval(
                tuple(combined[instrument].values()),
                instrument=instrument,
                start_inclusive=start_inclusive,
                end_exclusive=end_exclusive,
            )
        except C7APublicDataError as exc:
            raise C8AHistoricalCaptureError(str(exc)) from exc
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
        output[instrument] = selected
    return output


def capture_historical_funding_range(
    package: CapturePackage,
    *,
    start_inclusive: str,
    end_exclusive: str,
    fetch_manifest: PageFetcher = fetch_raw_strict,
    fetch_object: PageFetcher = fetch_raw_strict,
    host: str = "openapi.okx.com",
    request_pause_seconds: float = FUNDING_REQUEST_PAUSE_SECONDS,
    sleeper: Sleeper = time.sleep,
) -> dict[str, tuple[dict[str, Any], ...]]:
    pause = _pause(request_pause_seconds)
    specs: list[FundingDownloadSpec] = []
    request_count = 0
    for instrument in INSTRUMENTS:
        try:
            requests = build_historical_funding_manifest_requests(
                instrument,
                start_inclusive=start_inclusive,
                end_exclusive=end_exclusive,
                host=host,
            )
        except C7APublicDataError as exc:
            raise C8AHistoricalCaptureError(str(exc)) from exc
        for request in requests:
            if request_count and pause:
                sleeper(pause)
            raw, record = fetch_manifest(request)
            _retain(package, request, raw, record)
            try:
                query = dict(parse_qsl(urlparse(request.url).query))
                discovered = normalize_historical_funding_manifest(
                    parse_json_object(raw),
                    instrument=instrument,
                    start_inclusive=query["begin"],
                    end_exclusive=str(int(query["end"]) + 1),
                )
            except (KeyError, ValueError, C7APublicDataError) as exc:
                raise C8AHistoricalCaptureError(str(exc)) from exc
            specs.extend(
                FundingDownloadSpec(
                    request_id=item["request_id"],
                    instrument=item["instrument"],
                    url=item["url"],
                    column_map=FUNDING_ARCHIVE_COLUMNS,
                )
                for item in discovered
            )
            request_count += 1
    return capture_funding_downloads(
        package,
        specs=tuple(specs),
        start_inclusive=start_inclusive,
        end_exclusive=end_exclusive,
        fetch_object=fetch_object,
        download_pause_seconds=pause,
        sleeper=sleeper,
    )


class C8ACapturePackage(CapturePackage):
    """C8A-specific immutable manifest over the shared hardened transport."""

    def finalize(
        self, *, implementation_sha: str, capture_plan: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            self._assert_open()
        except C7AHistoricalCaptureError as exc:
            raise C8AHistoricalCaptureError(str(exc)) from exc
        if not EXACT_SHA.fullmatch(implementation_sha):
            raise C8AHistoricalCaptureError("implementation SHA must be exact")
        plan = dict(capture_plan)
        if plan != h1_h5_capture_plan():
            raise C8AHistoricalCaptureError(
                "capture plan is not the frozen C8A H1-H5 plan"
            )
        if not self.records:
            raise C8AHistoricalCaptureError("capture package contains no raw objects")
        expected = {
            ("marks", instrument): (
                str(plan["mark_start_inclusive"]),
                str(plan["mark_end_exclusive"]),
            )
            for instrument in INSTRUMENTS
        }
        expected.update(
            {
                ("trades", instrument): (
                    str(plan["trade_start_inclusive"]),
                    str(plan["trade_end_exclusive"]),
                )
                for instrument in INSTRUMENTS
            }
        )
        expected.update(
            {
                ("funding", instrument): (
                    str(plan["funding_start_inclusive"]),
                    str(plan["funding_end_exclusive"]),
                )
                for instrument in INSTRUMENTS
            }
        )
        if self._normalized_series != expected:
            raise C8AHistoricalCaptureError(
                "normalized source series are incomplete or interval-drifted"
            )
        self.write_json(
            "capture_index.json",
            {
                "schema_version": 1,
                "stage": "C8A_HISTORICAL_CAPTURE",
                "implementation_sha": implementation_sha,
                "capture_plan": plan,
                "records": [record.to_dict() for record in self.records],
                "source_kind": "OFFICIAL_PUBLIC_OKX",
                "authenticated": False,
                "contains_account_data": False,
                "contains_order_data": False,
                "private_api": False,
                "paper_side_effect": False,
                "shadow_side_effect": False,
                "live_state": "LIVE_FORBIDDEN",
            },
        )
        entries = sorted(self.root.rglob("*"))
        if any(path.is_symlink() for path in entries):
            raise C8AHistoricalCaptureError("capture package contains a symbolic link")
        files = []
        for path in (value for value in entries if value.is_file()):
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
            "stage": "C8A_HISTORICAL_CAPTURE_PACKAGE",
            "implementation_sha": implementation_sha,
            "file_count": len(files),
            "files": files,
            "real_public_data": True,
            "authenticated": False,
            "contains_account_data": False,
            "contains_order_data": False,
            "economic_result": False,
            "paper_side_effect": False,
            "shadow_side_effect": False,
            "live_state": "LIVE_FORBIDDEN",
        }
        self.write_json("manifest.json", manifest)
        self._finalized = True
        return manifest


__all__ = [
    "C7AHistoricalCaptureError",
    "C8ACapturePackage",
    "C8AHistoricalCaptureError",
    "FundingDownloadSpec",
    "capture_funding_downloads",
    "capture_historical_funding_range",
    "capture_mark_range",
    "capture_trade_range",
]
