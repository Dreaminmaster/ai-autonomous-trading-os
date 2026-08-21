"""Official-public OKX custody for the frozen C9A historical run."""

from __future__ import annotations

import hashlib
import math
import re
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode, urlunparse

from atos.c7a_historical_capture import (
    C7AHistoricalCaptureError,
    CapturePackage,
    CaptureRecord,
    FundingDownloadSpec,
    fetch_raw_strict,
)
from atos.c7a_okx_public_data import (
    API_HOSTS,
    HOUR_MS,
    TRADE_HISTORY_PATH,
    TRADE_PAGE_LIMIT,
    C7APublicDataError,
    PublicRequest,
    parse_json_object,
    validate_public_request,
)
from atos.c8a_historical_capture import (
    C8AHistoricalCaptureError,
    capture_mark_range,
)
from atos.c8a_historical_capture import (
    capture_funding_downloads as _capture_funding_downloads,
)
from atos.c8a_historical_capture import (
    capture_historical_funding_range as _capture_historical_funding_range,
)
from atos.c9a_contract import (
    ALL_TRADE_INSTRUMENTS,
    SWAP_INSTRUMENTS,
    C9AError,
    decimal_value,
    safety_boundary,
)
from atos.c9a_historical_schedule import w1_w5_capture_plan

EXACT_SHA = re.compile(r"[0-9a-f]{40}")
PageFetcher = Callable[[PublicRequest], tuple[bytes, CaptureRecord]]


class C9AHistoricalCaptureError(RuntimeError):
    """Raised unless public custody is exact, complete, and immutable."""


def _decimal(value: Any, label: str, *, positive: bool = False) -> Decimal:
    try:
        return decimal_value(value, label, positive=positive)
    except C9AError as exc:
        raise C9AHistoricalCaptureError(str(exc)) from exc


def _timestamp_ms(value: Any) -> int:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError as exc:
        raise C9AHistoricalCaptureError(f"invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        raise C9AHistoricalCaptureError("timestamp must be timezone-aware")
    return int(parsed.timestamp() * 1000)


def _iso_ms(value: int) -> str:
    return (
        datetime.fromtimestamp(value / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
    )


def validate_c9a_public_request(request: PublicRequest) -> None:
    """Allow C7-reviewed swap sources plus C9A spot trade candles only."""
    validate_public_request(request, trade_instruments=ALL_TRADE_INSTRUMENTS)


def fetch_raw_c9a(request: PublicRequest, **kwargs: Any) -> tuple[bytes, CaptureRecord]:
    return fetch_raw_strict(request, trade_instruments=ALL_TRADE_INSTRUMENTS, **kwargs)


def build_trade_candle_request(
    instrument: str, *, after_ms: int, host: str = "www.okx.com"
) -> PublicRequest:
    if instrument not in ALL_TRADE_INSTRUMENTS or host not in API_HOSTS:
        raise C9AHistoricalCaptureError("C9A trade request identity drift")
    if type(after_ms) is not int or after_ms < 0:
        raise C9AHistoricalCaptureError("C9A trade cursor must be milliseconds")
    url = urlunparse(
        (
            "https",
            host,
            TRADE_HISTORY_PATH,
            "",
            urlencode(
                sorted(
                    {
                        "instId": instrument,
                        "bar": "1H",
                        "limit": str(TRADE_PAGE_LIMIT),
                        "after": str(after_ms),
                    }.items()
                )
            ),
            "",
        )
    )
    request = PublicRequest(
        request_id=f"c9a-trade-{instrument}-{after_ms}",
        source_family="OKX_HISTORY_CANDLES_API",
        url=url,
    )
    validate_c9a_public_request(request)
    return request


def capture_funding_downloads(*args: Any, **kwargs: Any) -> Any:
    try:
        return _capture_funding_downloads(*args, **kwargs)
    except (C7AHistoricalCaptureError, C8AHistoricalCaptureError) as exc:
        raise C9AHistoricalCaptureError(str(exc)) from exc


def capture_historical_funding_range(*args: Any, **kwargs: Any) -> Any:
    try:
        return _capture_historical_funding_range(*args, **kwargs)
    except (C7AHistoricalCaptureError, C8AHistoricalCaptureError) as exc:
        raise C9AHistoricalCaptureError(str(exc)) from exc


def normalize_trade_candle_payload(
    payload: Mapping[str, Any], *, instrument: str
) -> tuple[dict[str, str], ...]:
    if instrument not in ALL_TRADE_INSTRUMENTS:
        raise C9AHistoricalCaptureError("unsupported C9A trade instrument")
    if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise C9AHistoricalCaptureError("trade response is not successful OKX JSON")
    output: list[dict[str, str]] = []
    seen: set[int] = set()
    for index, row in enumerate(payload["data"]):
        if (
            not isinstance(row, Sequence)
            or isinstance(row, (str, bytes))
            or len(row) != 9
        ):
            raise C9AHistoricalCaptureError(f"trade row {index} must have nine fields")
        try:
            stamp = int(str(row[0]))
        except ValueError as exc:
            raise C9AHistoricalCaptureError("trade timestamp is invalid") from exc
        if stamp < 0 or stamp % HOUR_MS or stamp in seen:
            raise C9AHistoricalCaptureError(
                "trade timestamps are duplicate or off-grid"
            )
        seen.add(stamp)
        prices = [
            _decimal(row[offset], f"trade price {offset}", positive=True)
            for offset in range(1, 5)
        ]
        volumes = [
            _decimal(row[offset], f"trade volume {offset}") for offset in range(5, 8)
        ]
        if any(value < 0 for value in volumes):
            raise C9AHistoricalCaptureError("trade volumes must be non-negative")
        open_px, high_px, low_px, close_px = prices
        if high_px < max(open_px, low_px, close_px) or low_px > min(
            open_px, high_px, close_px
        ):
            raise C9AHistoricalCaptureError("trade OHLC geometry is invalid")
        if row[8] != "1":
            raise C9AHistoricalCaptureError("unconfirmed trade candle is forbidden")
        output.append(
            {
                "instrument": instrument,
                "timestamp": _iso_ms(stamp),
                "open": str(open_px),
                "high": str(high_px),
                "low": str(low_px),
                "close": str(close_px),
                "volume_contract": str(volumes[0]),
                "volume_base": str(volumes[1]),
                "volume_quote": str(volumes[2]),
                "confirm": "1",
            }
        )
    output.sort(key=lambda row: row["timestamp"])
    return tuple(output)


def _select_trade_interval(
    rows: Sequence[Mapping[str, Any]],
    *,
    instrument: str,
    start_inclusive: str,
    end_exclusive: str,
) -> tuple[dict[str, str], ...]:
    start, end = _timestamp_ms(start_inclusive), _timestamp_ms(end_exclusive)
    if start >= end or (end - start) % HOUR_MS:
        raise C9AHistoricalCaptureError("trade interval must be positive whole hours")
    by_time: dict[int, Mapping[str, Any]] = {}
    for row in rows:
        if row.get("instrument") != instrument:
            raise C9AHistoricalCaptureError("trade interval instrument mismatch")
        stamp = _timestamp_ms(row.get("timestamp"))
        if stamp in by_time:
            raise C9AHistoricalCaptureError("duplicate trade row across pages")
        by_time[stamp] = row
    selected = []
    for stamp in range(start, end, HOUR_MS):
        row = by_time.get(stamp)
        if row is None:
            raise C9AHistoricalCaptureError(
                f"missing exact trade hour: {_iso_ms(stamp)}"
            )
        selected.append(
            {
                "timestamp": _iso_ms(stamp),
                "open": str(_decimal(row.get("open"), "trade open", positive=True)),
                "close": str(_decimal(row.get("close"), "trade close", positive=True)),
            }
        )
    return tuple(selected)


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
        raise C9AHistoricalCaptureError("capture transport provenance mismatch")
    package.retain_raw(raw, record)


def capture_trade_range(
    package: CapturePackage,
    *,
    instrument: str,
    start_inclusive: str,
    end_exclusive: str,
    fetch_page: PageFetcher = fetch_raw_c9a,
    host: str = "www.okx.com",
    max_pages: int = 1000,
    page_pause_seconds: float = 0.11,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[dict[str, str], ...]:
    if (
        instrument not in ALL_TRADE_INSTRUMENTS
        or type(max_pages) is not int
        or not 1 <= max_pages <= 10_000
    ):
        raise C9AHistoricalCaptureError("invalid C9A trade capture policy")
    if isinstance(page_pause_seconds, bool):
        raise C9AHistoricalCaptureError("page pause must be numeric")
    pause = float(page_pause_seconds)
    if not math.isfinite(pause) or not 0 <= pause <= 5:
        raise C9AHistoricalCaptureError(
            "page pause must be between zero and five seconds"
        )
    start, cursor = _timestamp_ms(start_inclusive), _timestamp_ms(end_exclusive)
    if start >= cursor:
        raise C9AHistoricalCaptureError("trade capture interval must be positive")
    combined: dict[str, dict[str, str]] = {}
    for page in range(max_pages):
        if page and pause:
            sleeper(pause)
        request = build_trade_candle_request(instrument, after_ms=cursor, host=host)
        raw, record = fetch_page(request)
        _retain(package, request, raw, record)
        try:
            rows = normalize_trade_candle_payload(
                parse_json_object(raw), instrument=instrument
            )
        except C7APublicDataError as exc:
            raise C9AHistoricalCaptureError(str(exc)) from exc
        if not rows:
            raise C9AHistoricalCaptureError("trade pagination returned an empty page")
        stamps = [_timestamp_ms(row["timestamp"]) for row in rows]
        oldest, newest = min(stamps), max(stamps)
        if oldest >= cursor or newest >= cursor:
            raise C9AHistoricalCaptureError(
                "trade pagination did not move strictly older"
            )
        for row in rows:
            stamp = row["timestamp"]
            if stamp in combined:
                raise C9AHistoricalCaptureError(
                    f"duplicate trade timestamp across pages: {stamp}"
                )
            combined[stamp] = dict(row)
        if oldest <= start:
            break
        cursor = oldest
    else:
        raise C9AHistoricalCaptureError("trade pagination exceeded max_pages")
    selected = _select_trade_interval(
        tuple(combined.values()),
        instrument=instrument,
        start_inclusive=start_inclusive,
        end_exclusive=end_exclusive,
    )
    package.retain_normalized_series(
        series_type="trades",
        instrument=instrument,
        start_inclusive=start_inclusive,
        end_exclusive=end_exclusive,
        rows=selected,
    )
    return selected


class C9ACapturePackage(CapturePackage):
    def __init__(self, root: Any):
        super().__init__(
            root,
            allowed_instruments=ALL_TRADE_INSTRUMENTS,
            public_trade_instruments=ALL_TRADE_INSTRUMENTS,
        )

    def finalize(
        self, *, implementation_sha: str, capture_plan: Mapping[str, Any]
    ) -> dict[str, Any]:
        self._assert_open()
        if not EXACT_SHA.fullmatch(implementation_sha):
            raise C9AHistoricalCaptureError("implementation SHA must be exact")
        plan = dict(capture_plan)
        if plan != w1_w5_capture_plan():
            raise C9AHistoricalCaptureError("capture plan is not frozen C9A W1-W5")
        if not self.records:
            raise C9AHistoricalCaptureError("capture package contains no raw objects")
        expected = {
            ("trades", instrument): (
                str(plan["trade_start_inclusive"]),
                str(plan["trade_end_exclusive"]),
            )
            for instrument in ALL_TRADE_INSTRUMENTS
        }
        expected.update(
            {
                ("marks", instrument): (
                    str(plan["mark_start_inclusive"]),
                    str(plan["mark_end_exclusive"]),
                )
                for instrument in SWAP_INSTRUMENTS
            }
        )
        expected.update(
            {
                ("funding", instrument): (
                    str(plan["funding_start_inclusive"]),
                    str(plan["funding_end_exclusive"]),
                )
                for instrument in SWAP_INSTRUMENTS
            }
        )
        if self._normalized_series != expected:
            raise C9AHistoricalCaptureError(
                "normalized source inventory or bounds drift"
            )
        self.write_json(
            "capture_index.json",
            {
                "schema_version": 1,
                "stage": "C9A_HISTORICAL_CAPTURE",
                "implementation_sha": implementation_sha,
                "capture_plan": plan,
                "records": [record.to_dict() for record in self.records],
                "source_kind": "OFFICIAL_PUBLIC_OKX",
                **safety_boundary(),
            },
        )
        entries = sorted(self.root.rglob("*"))
        if any(path.is_symlink() for path in entries):
            raise C9AHistoricalCaptureError("capture package contains a symbolic link")
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
            "stage": "C9A_HISTORICAL_CAPTURE_PACKAGE",
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
    "C7AHistoricalCaptureError",
    "C9ACapturePackage",
    "C9AHistoricalCaptureError",
    "FundingDownloadSpec",
    "capture_funding_downloads",
    "capture_historical_funding_range",
    "capture_mark_range",
    "capture_trade_range",
    "fetch_raw_c9a",
    "normalize_trade_candle_payload",
    "validate_c9a_public_request",
]
