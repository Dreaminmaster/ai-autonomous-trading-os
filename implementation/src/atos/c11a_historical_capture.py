"""Official-public, two-phase OKX custody for the frozen C11A screen."""

from __future__ import annotations

import hashlib
import math
import re
import statistics
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from typing import Any
from urllib.parse import parse_qsl, urlparse

from atos.c7a_historical_capture import (
    C7AHistoricalCaptureError,
    CapturePackage,
    CaptureRecord,
    fetch_raw_strict,
)
from atos.c7a_okx_public_data import (
    FUNDING_ARCHIVE_COLUMNS,
    HOUR_MS,
    MARK_PAGE_LIMIT,
    TRADE_PAGE_LIMIT,
    C7APublicDataError,
    PublicRequest,
    build_historical_funding_manifest_requests,
    build_mark_price_request,
    build_trade_candle_request,
    historical_download_request,
    normalize_funding_download,
    normalize_historical_funding_manifest,
    normalize_mark_price_payload,
    normalize_trade_candle_payload,
    parse_json_object,
    select_funding_interval,
    validate_public_request,
)
from atos.c11a_contract import (
    BTC_BETA_BENCHMARK,
    CANDIDATE_POOL,
    SELECTED_UNIVERSE_SIZE,
    capture_plan,
    safety_boundary,
)

EXACT_SHA = re.compile(r"^[0-9a-f]{40}$")
MAX_PAGES = 10_000
MAX_FUNDING_GAP_MS = 8 * HOUR_MS + 60_000
FUNDING_REQUEST_PAUSE_SECONDS = 0.5
PageFetcher = Callable[[PublicRequest], tuple[bytes, CaptureRecord]]
Sleeper = Callable[[float], None]


class C11AHistoricalCaptureError(RuntimeError):
    """Raised unless C11A public custody is exact, complete, and immutable."""


def _timestamp_ms(value: Any) -> int:
    try:
        stamp = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise C11AHistoricalCaptureError(f"invalid timestamp: {value!r}") from exc
    if stamp.tzinfo is None:
        raise C11AHistoricalCaptureError("timestamp must be timezone-aware")
    return int(stamp.timestamp() * 1000)


def _iso_ms(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
    )


def _pause(value: float) -> float:
    if isinstance(value, bool):
        raise C11AHistoricalCaptureError("request pause must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise C11AHistoricalCaptureError("request pause must be numeric") from exc
    if not math.isfinite(result) or not 0 <= result <= 5:
        raise C11AHistoricalCaptureError(
            "request pause must be between zero and five seconds"
        )
    return result


def validate_c11a_public_request(request: PublicRequest) -> None:
    validate_public_request(
        request,
        instruments=CANDIDATE_POOL,
        trade_instruments=CANDIDATE_POOL,
    )


def fetch_raw_c11a(
    request: PublicRequest, **kwargs: Any
) -> tuple[bytes, CaptureRecord]:
    return fetch_raw_strict(
        request,
        instruments=CANDIDATE_POOL,
        trade_instruments=CANDIDATE_POOL,
        **kwargs,
    )


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
        raise C11AHistoricalCaptureError("capture transport provenance mismatch")
    try:
        package.retain_raw(raw, record)
    except C7AHistoricalCaptureError as exc:
        raise C11AHistoricalCaptureError(str(exc)) from exc


def _select_exact_candles(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    start_inclusive: str,
    end_exclusive: str,
    include_volume: bool,
) -> tuple[dict[str, str], ...]:
    start = _timestamp_ms(start_inclusive)
    end = _timestamp_ms(end_exclusive)
    if start >= end or (end - start) % HOUR_MS:
        raise C11AHistoricalCaptureError("candle interval must be whole positive hours")
    by_time: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        if row.get("instrument") != instrument:
            raise C11AHistoricalCaptureError("candle instrument mismatch")
        stamp = _timestamp_ms(row.get("timestamp"))
        if stamp in by_time:
            raise C11AHistoricalCaptureError("duplicate candle timestamp")
        by_time[stamp] = row
    selected: list[dict[str, str]] = []
    for stamp in range(start, end, HOUR_MS):
        row = by_time.get(stamp)
        if row is None:
            raise C11AHistoricalCaptureError(
                f"missing exact candle hour: {instrument} {_iso_ms(stamp)}"
            )
        if include_volume:
            selected.append(
                {
                    "timestamp": _iso_ms(stamp),
                    "open": str(row["open"]),
                    "high": str(row["high"]),
                    "low": str(row["low"]),
                    "close": str(row["close"]),
                    "volume_contract": str(row["volume_contract"]),
                    "volume_base": str(row["volume_base"]),
                    "volume_quote": str(row["volume_quote"]),
                    "confirm": "1",
                }
            )
        else:
            selected.append(
                {"timestamp": _iso_ms(stamp), "close": str(row["close"])}
            )
    return tuple(selected)


def _capture_candle_range(
    package: C11ACapturePackage,
    *,
    series_type: str,
    instrument: str,
    start_inclusive: str,
    end_exclusive: str,
    fetch_page: PageFetcher,
    host: str,
    max_pages: int,
    page_pause_seconds: float,
    sleeper: Sleeper,
) -> tuple[dict[str, str], ...]:
    if instrument not in CANDIDATE_POOL or type(max_pages) is not int or not (
        1 <= max_pages <= MAX_PAGES
    ):
        raise C11AHistoricalCaptureError("invalid candle capture policy")
    if series_type not in {"formation_trades", "trades", "marks"}:
        raise C11AHistoricalCaptureError("invalid candle series type")
    pause = _pause(page_pause_seconds)
    start = _timestamp_ms(start_inclusive)
    cursor = _timestamp_ms(end_exclusive)
    if start >= cursor:
        raise C11AHistoricalCaptureError("candle capture interval must be positive")
    combined: dict[str, dict[str, str]] = {}
    for page in range(max_pages):
        if page and pause:
            sleeper(pause)
        try:
            if series_type == "marks":
                request = build_mark_price_request(
                    instrument,
                    after_ms=cursor,
                    host=host,
                    allowed_instruments=CANDIDATE_POOL,
                )
            else:
                request = build_trade_candle_request(
                    instrument,
                    after_ms=cursor,
                    host=host,
                    allowed_instruments=CANDIDATE_POOL,
                )
            raw, record = fetch_page(request)
            _retain(package, request, raw, record)
            payload = parse_json_object(raw)
            if series_type == "marks":
                rows = normalize_mark_price_payload(
                    payload,
                    instrument=instrument,
                    allowed_instruments=CANDIDATE_POOL,
                )
            else:
                rows = normalize_trade_candle_payload(
                    payload,
                    instrument=instrument,
                    allowed_instruments=CANDIDATE_POOL,
                )
        except C7APublicDataError as exc:
            raise C11AHistoricalCaptureError(str(exc)) from exc
        if not rows:
            raise C11AHistoricalCaptureError("candle pagination returned an empty page")
        stamps = [_timestamp_ms(row["timestamp"]) for row in rows]
        oldest, newest = min(stamps), max(stamps)
        if oldest >= cursor or newest >= cursor:
            raise C11AHistoricalCaptureError(
                "candle pagination did not move strictly older"
            )
        for row in rows:
            stamp = str(row["timestamp"])
            if stamp in combined:
                raise C11AHistoricalCaptureError(
                    f"duplicate candle timestamp across pages: {stamp}"
                )
            combined[stamp] = dict(row)
        if oldest <= start:
            break
        cursor = oldest
    else:
        raise C11AHistoricalCaptureError("candle pagination exceeded max_pages")

    selected = _select_exact_candles(
        tuple(combined.values()),
        instrument=instrument,
        start_inclusive=start_inclusive,
        end_exclusive=end_exclusive,
        include_volume=series_type != "marks",
    )
    package.retain_c11a_series(
        series_type=series_type,
        instrument=instrument,
        start_inclusive=start_inclusive,
        end_exclusive=end_exclusive,
        rows=selected,
    )
    return selected


def capture_trade_range(
    package: C11ACapturePackage,
    *,
    series_type: str,
    instrument: str,
    start_inclusive: str,
    end_exclusive: str,
    fetch_page: PageFetcher = fetch_raw_c11a,
    host: str = "www.okx.com",
    max_pages: int = MAX_PAGES,
    page_pause_seconds: float = 0.11,
    sleeper: Sleeper = time.sleep,
) -> tuple[dict[str, str], ...]:
    if series_type not in {"formation_trades", "trades"}:
        raise C11AHistoricalCaptureError("trade series must be formation_trades or trades")
    return _capture_candle_range(
        package,
        series_type=series_type,
        instrument=instrument,
        start_inclusive=start_inclusive,
        end_exclusive=end_exclusive,
        fetch_page=fetch_page,
        host=host,
        max_pages=max_pages,
        page_pause_seconds=page_pause_seconds,
        sleeper=sleeper,
    )


def capture_mark_range(
    package: C11ACapturePackage,
    *,
    instrument: str,
    start_inclusive: str,
    end_exclusive: str,
    fetch_page: PageFetcher = fetch_raw_c11a,
    host: str = "www.okx.com",
    max_pages: int = MAX_PAGES,
    page_pause_seconds: float = 0.11,
    sleeper: Sleeper = time.sleep,
) -> tuple[dict[str, str], ...]:
    return _capture_candle_range(
        package,
        series_type="marks",
        instrument=instrument,
        start_inclusive=start_inclusive,
        end_exclusive=end_exclusive,
        fetch_page=fetch_page,
        host=host,
        max_pages=max_pages,
        page_pause_seconds=page_pause_seconds,
        sleeper=sleeper,
    )


def select_formation_universe(
    formation: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Any]:
    if set(formation) != set(CANDIDATE_POOL):
        raise C11AHistoricalCaptureError("formation candidate-pool coverage drift")
    scores: list[tuple[str, Decimal]] = []
    expected_times: tuple[str, ...] | None = None
    for instrument in CANDIDATE_POOL:
        rows = formation[instrument]
        timestamps = tuple(str(row.get("timestamp")) for row in rows)
        if expected_times is None:
            expected_times = timestamps
        if not rows or timestamps != expected_times or len(timestamps) != len(set(timestamps)):
            raise C11AHistoricalCaptureError(
                "formation timestamps are empty, duplicate, or misaligned"
            )
        values: list[Decimal] = []
        for row in rows:
            try:
                value = Decimal(str(row.get("volume_quote")))
            except (InvalidOperation, ValueError) as exc:
                raise C11AHistoricalCaptureError(
                    "formation quote volume is not decimal"
                ) from exc
            if not value.is_finite() or value < 0:
                raise C11AHistoricalCaptureError(
                    "formation quote volume must be finite and non-negative"
                )
            values.append(value)
        scores.append((instrument, statistics.median(values)))
    scores.sort(key=lambda item: (-item[1], item[0]))
    selected = tuple(instrument for instrument, _ in scores[:SELECTED_UNIVERSE_SIZE])
    if len(selected) != SELECTED_UNIVERSE_SIZE:
        raise C11AHistoricalCaptureError("selected universe size drift")
    return {
        "schema_version": 1,
        "stage": "C11A_FORMATION_UNIVERSE",
        "liquidity_field": "volCcyQuote",
        "formation_row_count_per_instrument": len(expected_times or ()),
        "scores": [
            {
                "rank": rank,
                "instrument": instrument,
                "median_quote_volume": format(score, "f"),
                "selected": instrument in selected,
            }
            for rank, (instrument, score) in enumerate(scores, start=1)
        ],
        "selected_universe": list(selected),
        **safety_boundary(),
    }


@dataclass(frozen=True)
class C11AFundingDownloadSpec:
    request_id: str
    instrument: str
    url: str
    column_map: Mapping[str, str]

    def request(self) -> PublicRequest:
        if self.instrument not in CANDIDATE_POOL:
            raise C11AHistoricalCaptureError("funding instrument is not in C11A pool")
        try:
            return historical_download_request(self.url, request_id=self.request_id)
        except C7APublicDataError as exc:
            raise C11AHistoricalCaptureError(str(exc)) from exc


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
        raise C11AHistoricalCaptureError(
            f"funding settlements are empty, duplicate, or unordered: {instrument}"
        )
    gaps = (
        stamps[0] - start,
        *(right - left for left, right in pairwise(stamps)),
        end - stamps[-1],
    )
    if any(gap < 0 or gap > MAX_FUNDING_GAP_MS for gap in gaps):
        raise C11AHistoricalCaptureError(
            f"funding coverage gap exceeds eight hours plus tolerance: {instrument}"
        )


def capture_funding_downloads(
    package: C11ACapturePackage,
    *,
    selected_universe: Sequence[str],
    specs: Sequence[C11AFundingDownloadSpec],
    start_inclusive: str,
    end_exclusive: str,
    fetch_object: PageFetcher = fetch_raw_c11a,
    download_pause_seconds: float = FUNDING_REQUEST_PAUSE_SECONDS,
    sleeper: Sleeper = time.sleep,
) -> dict[str, tuple[dict[str, Any], ...]]:
    selected = tuple(selected_universe)
    if selected != package.selected_universe or not specs or {
        spec.instrument for spec in specs
    } != set(selected):
        raise C11AHistoricalCaptureError("funding inventory does not match frozen top eight")
    request_ids = [spec.request_id for spec in specs]
    if len(request_ids) != len(set(request_ids)):
        raise C11AHistoricalCaptureError("funding request IDs must be unique")
    pause = _pause(download_pause_seconds)
    combined: dict[str, dict[str, dict[str, Any]]] = {
        instrument: {} for instrument in selected
    }
    for index, spec in enumerate(specs):
        if index and pause:
            sleeper(pause)
        request = spec.request()
        raw, record = fetch_object(request)
        _retain(package, request, raw, record)
        try:
            rows = normalize_funding_download(
                raw,
                instrument=spec.instrument,
                column_map=spec.column_map,
                allowed_instruments=CANDIDATE_POOL,
            )
        except C7APublicDataError as exc:
            raise C11AHistoricalCaptureError(str(exc)) from exc
        for row in rows:
            stamp = str(row["funding_time"])
            if stamp in combined[spec.instrument]:
                raise C11AHistoricalCaptureError(
                    f"duplicate funding settlement across files: {spec.instrument} {stamp}"
                )
            combined[spec.instrument][stamp] = dict(row)
    output: dict[str, tuple[dict[str, Any], ...]] = {}
    for instrument in selected:
        try:
            selected_rows = select_funding_interval(
                tuple(combined[instrument].values()),
                instrument=instrument,
                start_inclusive=start_inclusive,
                end_exclusive=end_exclusive,
                allowed_instruments=CANDIDATE_POOL,
            )
        except C7APublicDataError as exc:
            raise C11AHistoricalCaptureError(str(exc)) from exc
        _assert_complete_funding_interval(
            selected_rows,
            instrument=instrument,
            start_inclusive=start_inclusive,
            end_exclusive=end_exclusive,
        )
        package.retain_c11a_series(
            series_type="funding",
            instrument=instrument,
            start_inclusive=start_inclusive,
            end_exclusive=end_exclusive,
            rows=selected_rows,
        )
        output[instrument] = selected_rows
    return output


def capture_historical_funding_range(
    package: C11ACapturePackage,
    *,
    selected_universe: Sequence[str],
    start_inclusive: str,
    end_exclusive: str,
    fetch_manifest: PageFetcher = fetch_raw_c11a,
    fetch_object: PageFetcher = fetch_raw_c11a,
    host: str = "openapi.okx.com",
    request_pause_seconds: float = FUNDING_REQUEST_PAUSE_SECONDS,
    sleeper: Sleeper = time.sleep,
) -> dict[str, tuple[dict[str, Any], ...]]:
    selected = tuple(selected_universe)
    if selected != package.selected_universe:
        raise C11AHistoricalCaptureError("funding selection is not the frozen top eight")
    pause = _pause(request_pause_seconds)
    specs: list[C11AFundingDownloadSpec] = []
    request_count = 0
    for instrument in selected:
        try:
            requests = build_historical_funding_manifest_requests(
                instrument,
                start_inclusive=start_inclusive,
                end_exclusive=end_exclusive,
                host=host,
                allowed_instruments=CANDIDATE_POOL,
            )
        except C7APublicDataError as exc:
            raise C11AHistoricalCaptureError(str(exc)) from exc
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
                    allowed_instruments=CANDIDATE_POOL,
                )
            except (KeyError, ValueError, C7APublicDataError) as exc:
                raise C11AHistoricalCaptureError(str(exc)) from exc
            specs.extend(
                C11AFundingDownloadSpec(
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
        selected_universe=selected,
        specs=tuple(specs),
        start_inclusive=start_inclusive,
        end_exclusive=end_exclusive,
        fetch_object=fetch_object,
        download_pause_seconds=pause,
        sleeper=sleeper,
    )


class C11ACapturePackage(CapturePackage):
    """Immutable two-phase C11A source package over explicit public policy."""

    def __init__(self, root: Any):
        super().__init__(
            root,
            allowed_instruments=CANDIDATE_POOL,
            public_trade_instruments=CANDIDATE_POOL,
        )
        self._selected_universe: tuple[str, ...] = ()

    @property
    def selected_universe(self) -> tuple[str, ...]:
        return self._selected_universe

    def freeze_universe(self, evidence: Mapping[str, Any]) -> tuple[str, ...]:
        self._assert_open()
        if self._selected_universe:
            raise C11AHistoricalCaptureError("formation universe is already frozen")
        selected = evidence.get("selected_universe")
        scores = evidence.get("scores")
        if (
            evidence.get("schema_version") != 1
            or evidence.get("stage") != "C11A_FORMATION_UNIVERSE"
            or evidence.get("liquidity_field") != "volCcyQuote"
            or not isinstance(selected, list)
            or len(selected) != SELECTED_UNIVERSE_SIZE
            or len(set(selected)) != SELECTED_UNIVERSE_SIZE
            or any(instrument not in CANDIDATE_POOL for instrument in selected)
            or not isinstance(scores, list)
            or len(scores) != len(CANDIDATE_POOL)
        ):
            raise C11AHistoricalCaptureError("invalid formation selected universe")
        score_instruments: list[str] = []
        score_selected: list[str] = []
        for rank, row in enumerate(scores, start=1):
            if (
                not isinstance(row, Mapping)
                or row.get("rank") != rank
                or row.get("instrument") not in CANDIDATE_POOL
                or not isinstance(row.get("median_quote_volume"), str)
                or not isinstance(row.get("selected"), bool)
            ):
                raise C11AHistoricalCaptureError("invalid formation score evidence")
            instrument = str(row["instrument"])
            try:
                value = Decimal(str(row["median_quote_volume"]))
            except InvalidOperation as exc:
                raise C11AHistoricalCaptureError(
                    "formation score is not decimal"
                ) from exc
            if not value.is_finite() or value < 0:
                raise C11AHistoricalCaptureError("formation score must be non-negative")
            score_instruments.append(instrument)
            if row["selected"]:
                score_selected.append(instrument)
        if (
            len(score_instruments) != len(set(score_instruments))
            or set(score_instruments) != set(CANDIDATE_POOL)
            or tuple(score_selected) != tuple(selected)
            or tuple(score_instruments[:SELECTED_UNIVERSE_SIZE]) != tuple(selected)
        ):
            raise C11AHistoricalCaptureError("formation rank/selection evidence drift")
        self.write_json("normalized/formation_universe.json", dict(evidence))
        self._selected_universe = tuple(selected)
        return self._selected_universe

    def retain_c11a_series(
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
        if series_type == "formation_trades":
            allowed = instrument in CANDIDATE_POOL
        else:
            allowed = (
                series_type in {"trades", "funding"}
                and instrument in self._selected_universe
            ) or (
                series_type == "marks"
                and instrument in {*self._selected_universe, BTC_BETA_BENCHMARK}
            )
        if not allowed:
            raise C11AHistoricalCaptureError("series identity is outside frozen phase")
        if key in self._normalized_series or not rows:
            raise C11AHistoricalCaptureError("series is empty or already retained")
        if _timestamp_ms(start_inclusive) >= _timestamp_ms(end_exclusive):
            raise C11AHistoricalCaptureError("series interval must be positive")
        self.write_json(f"normalized/{series_type}/{instrument}.json", list(rows))
        self._normalized_series[key] = (start_inclusive, end_exclusive)

    def finalize(
        self, *, implementation_sha: str, capture_plan_value: Mapping[str, Any]
    ) -> dict[str, Any]:
        self._assert_open()
        if not EXACT_SHA.fullmatch(implementation_sha):
            raise C11AHistoricalCaptureError("implementation SHA must be exact")
        plan = dict(capture_plan_value)
        if plan != capture_plan():
            raise C11AHistoricalCaptureError("capture plan is not frozen C11A H1-H5")
        if not self.records or len(self._selected_universe) != SELECTED_UNIVERSE_SIZE:
            raise C11AHistoricalCaptureError("capture records or selected universe missing")
        expected = {
            ("formation_trades", instrument): (
                str(plan["formation_trade_start_inclusive"]),
                str(plan["formation_trade_end_exclusive"]),
            )
            for instrument in CANDIDATE_POOL
        }
        for series_type, start_key, end_key in (
            ("trades", "selected_trade_start_inclusive", "selected_trade_end_exclusive"),
            ("funding", "funding_start_inclusive", "funding_end_exclusive"),
        ):
            expected.update(
                {
                    (series_type, instrument): (
                        str(plan[start_key]),
                        str(plan[end_key]),
                    )
                    for instrument in self._selected_universe
                }
            )
        expected.update(
            {
                ("marks", instrument): (
                    str(plan["mark_start_inclusive"]),
                    str(plan["mark_end_exclusive"]),
                )
                for instrument in {*self._selected_universe, BTC_BETA_BENCHMARK}
            }
        )
        if self._normalized_series != expected:
            raise C11AHistoricalCaptureError(
                "normalized source inventory or bounds drift"
            )
        self.write_json(
            "capture_index.json",
            {
                "schema_version": 1,
                "stage": "C11A_HISTORICAL_CAPTURE",
                "implementation_sha": implementation_sha,
                "capture_plan": plan,
                "selected_universe": list(self._selected_universe),
                "records": [record.to_dict() for record in self.records],
                "source_kind": "OFFICIAL_PUBLIC_OKX",
                **safety_boundary(),
            },
        )
        entries = sorted(self.root.rglob("*"))
        if any(path.is_symlink() for path in entries):
            raise C11AHistoricalCaptureError("capture package contains a symbolic link")
        files = []
        for path in (value for value in entries if value.is_file()):
            relative = path.relative_to(self.root).as_posix()
            if relative == "manifest.json":
                continue
            raw = path.read_bytes()
            files.append(
                {
                    "path": relative,
                    "size": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            )
        manifest = {
            "schema_version": 1,
            "stage": "C11A_HISTORICAL_CAPTURE_PACKAGE",
            "implementation_sha": implementation_sha,
            "file_count": len(files),
            "files": files,
            "real_public_data": True,
            "economic_result": False,
            **safety_boundary(),
        }
        self.write_json("manifest.json", manifest)
        self._finalized = True
        return manifest


__all__ = [
    "MARK_PAGE_LIMIT",
    "TRADE_PAGE_LIMIT",
    "C11ACapturePackage",
    "C11AFundingDownloadSpec",
    "C11AHistoricalCaptureError",
    "capture_funding_downloads",
    "capture_historical_funding_range",
    "capture_mark_range",
    "capture_trade_range",
    "fetch_raw_c11a",
    "select_formation_universe",
    "validate_c11a_public_request",
]
