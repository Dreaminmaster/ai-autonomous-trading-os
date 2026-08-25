"""Official-public OKX custody for the frozen C12A historical run."""

from __future__ import annotations

import csv
import hashlib
import io
import re
import time
import zipfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse, urlunparse

from atos.c7a_historical_capture import (
    C7AHistoricalCaptureError,
    CapturePackage,
    CaptureRecord,
    fetch_raw_strict,
)
from atos.c7a_okx_public_data import (
    API_HOSTS,
    C12A_PUBLIC_INSTRUMENTS,
    HISTORICAL_DATA_PATH,
    C7APublicDataError,
    PublicRequest,
    parse_json_object,
    validate_public_request,
)
from atos.c9a_historical_capture import capture_trade_range
from atos.c12a_contract import (
    EXECUTION_MAX_DELAY,
    SPOT_INSTRUMENTS,
    WINDOWS,
    C12AError,
    ContractDecision,
    contract_decisions,
    decimal_value,
    iso_z,
    load_frozen_config,
    safety_boundary,
    utc_timestamp,
)

EXACT_SHA = re.compile(r"[0-9a-f]{40}")
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
FUTURES_HEADER = (
    "instrument_name",
    "trade_id",
    "side",
    "price",
    "size",
    "created_time",
)
HOUR_MS = 3_600_000
MAX_ARCHIVE_ROWS = 5_000_000
C12A_MAX_EXTRACTED_DOWNLOAD_BYTES = 256 * 1024 * 1024
UTC8 = timedelta(hours=8)
PageFetcher = Callable[[PublicRequest], tuple[bytes, CaptureRecord]]


class C12AHistoricalCaptureError(RuntimeError):
    """Raised unless C12A public custody is exact, complete, and immutable."""


@dataclass(frozen=True)
class FuturesArchiveSpec:
    family: str
    month: str
    instrument: str
    request_id: str
    url: str

    def request(self) -> PublicRequest:
        request = PublicRequest(
            request_id=self.request_id,
            source_family="OKX_HISTORICAL_FUTURES_CHAIN_DOWNLOAD",
            url=self.url,
            headers=(
                ("Accept", "application/zip,application/octet-stream"),
                ("User-Agent", "ai-autonomous-trading-os/c12a-public-data"),
            ),
        )
        validate_c12a_public_request(request)
        return request


def _month_bounds(month: str) -> tuple[datetime, datetime]:
    if not re.fullmatch(r"20\d{2}-(0[1-9]|1[0-2])", month):
        raise C12AHistoricalCaptureError("archive month must be YYYY-MM")
    local_start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
    local_next = datetime(
        local_start.year + (1 if local_start.month == 12 else 0),
        1 if local_start.month == 12 else local_start.month + 1,
        1,
        tzinfo=UTC,
    )
    return local_start - UTC8, local_next - UTC8


def _request_month_bounds(month: str) -> tuple[int, int]:
    start, end = _month_bounds(month)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000) - 1


def validate_c12a_public_request(request: PublicRequest) -> None:
    try:
        validate_public_request(
            request,
            instruments=C12A_PUBLIC_INSTRUMENTS,
            trade_instruments=C12A_PUBLIC_INSTRUMENTS,
        )
    except C7APublicDataError as exc:
        raise C12AHistoricalCaptureError(str(exc)) from exc


def fetch_raw_c12a(
    request: PublicRequest, **kwargs: Any
) -> tuple[bytes, CaptureRecord]:
    try:
        return fetch_raw_strict(
            request,
            instruments=C12A_PUBLIC_INSTRUMENTS,
            trade_instruments=C12A_PUBLIC_INSTRUMENTS,
            **kwargs,
        )
    except C7AHistoricalCaptureError as exc:
        raise C12AHistoricalCaptureError(str(exc)) from exc


def build_futures_manifest_request(
    *, family: str, month: str, host: str = "openapi.okx.com"
) -> PublicRequest:
    if family not in SPOT_INSTRUMENTS or host not in API_HOSTS:
        raise C12AHistoricalCaptureError("C12A futures-manifest identity drift")
    begin, end = _request_month_bounds(month)
    url = urlunparse(
        (
            "https",
            host,
            HISTORICAL_DATA_PATH,
            "",
            urlencode(
                sorted(
                    {
                        "module": "1",
                        "instType": "FUTURES",
                        "instFamilyList": family,
                        "dateAggrType": "monthly",
                        "begin": str(begin),
                        "end": str(end),
                    }.items()
                )
            ),
            "",
        )
    )
    request = PublicRequest(
        request_id=f"c12a-futures-manifest-{family}-{month}",
        source_family="OKX_HISTORICAL_FUTURES_CHAIN_API",
        url=url,
        headers=(
            ("Accept", "application/json"),
            ("User-Agent", "ai-autonomous-trading-os/c12a-public-data"),
        ),
    )
    validate_c12a_public_request(request)
    return request


def normalize_futures_manifest(
    payload: Mapping[str, Any],
    *,
    family: str,
    month: str,
    instrument: str,
) -> FuturesArchiveSpec:
    """Select exactly one official monthly future-chain archive."""

    if family not in SPOT_INSTRUMENTS or not instrument.startswith(f"{family}-"):
        raise C12AHistoricalCaptureError("futures-manifest target identity drift")
    _month_bounds(month)
    if payload.get("code") != "0" or not isinstance(payload.get("data"), list):
        raise C12AHistoricalCaptureError("futures manifest is not successful OKX JSON")
    expected_filename = f"{family}-futureschain-trades-{month}.zip"
    matched: list[str] = []
    for result in payload["data"]:
        if not isinstance(result, Mapping) or result.get("dateAggrType") != "monthly":
            raise C12AHistoricalCaptureError("futures-manifest aggregation drift")
        details = result.get("details")
        if not isinstance(details, list) or not details:
            raise C12AHistoricalCaptureError("futures manifest has no details")
        for detail in details:
            if (
                not isinstance(detail, Mapping)
                or detail.get("instId") not in {"", None}
                or detail.get("instFamily") != family
                or detail.get("instType") != "FUTURES"
            ):
                raise C12AHistoricalCaptureError(
                    "futures-manifest detail identity drift"
                )
            groups = detail.get("groupDetails")
            if not isinstance(groups, list) or not groups:
                raise C12AHistoricalCaptureError("futures manifest has no files")
            for group in groups:
                if not isinstance(group, Mapping):
                    raise C12AHistoricalCaptureError(
                        "futures-manifest file is not an object"
                    )
                filename, url = group.get("filename"), group.get("url")
                if not isinstance(filename, str) or not isinstance(url, str):
                    raise C12AHistoricalCaptureError(
                        "futures-manifest file identity is missing"
                    )
                if filename != expected_filename:
                    continue
                if urlparse(url).path.rsplit("/", 1)[-1] != filename:
                    raise C12AHistoricalCaptureError(
                        "futures archive filename/URL drift"
                    )
                request = PublicRequest(
                    request_id=f"c12a-futures-{family}-{month}",
                    source_family="OKX_HISTORICAL_FUTURES_CHAIN_DOWNLOAD",
                    url=url,
                )
                validate_c12a_public_request(request)
                matched.append(url)
    if len(matched) != 1:
        raise C12AHistoricalCaptureError(
            "futures monthly archive is missing or duplicated"
        )
    return FuturesArchiveSpec(
        family=family,
        month=month,
        instrument=instrument,
        request_id=f"c12a-futures-{family}-{month}",
        url=matched[0],
    )


def _read_archive_csv(raw: bytes, *, family: str, month: str) -> bytes:
    if not raw.startswith(b"PK\x03\x04"):
        raise C12AHistoricalCaptureError("futures-chain object must be a ZIP archive")
    expected_member = f"{family}-futureschain-trades-{month}.csv"
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1:
                raise C12AHistoricalCaptureError("futures ZIP must contain one CSV")
            member = members[0]
            name = member.filename.replace("\\", "/")
            if (
                name != expected_member
                or "/" in name
                or member.flag_bits & 0x1
                or (member.external_attr >> 16) & 0o170000 == 0o120000
            ):
                raise C12AHistoricalCaptureError(
                    "futures ZIP member identity is unsafe"
                )
            if not 0 < member.file_size <= C12A_MAX_EXTRACTED_DOWNLOAD_BYTES:
                raise C12AHistoricalCaptureError("futures ZIP CSV size is invalid")
            if (
                member.compress_size == 0
                or member.file_size > member.compress_size * 200
            ):
                raise C12AHistoricalCaptureError(
                    "futures ZIP compression ratio is unsafe"
                )
            data = archive.read(member)
    except C12AHistoricalCaptureError:
        raise
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise C12AHistoricalCaptureError("futures ZIP is invalid") from exc
    if len(data) != member.file_size:
        raise C12AHistoricalCaptureError(
            "futures ZIP member size changed while reading"
        )
    return data


def normalize_futures_archive(
    raw: bytes,
    *,
    family: str,
    month: str,
    instrument: str,
) -> tuple[dict[str, str], ...]:
    """Validate all rows and retain only one frozen asset-contract."""

    if family not in SPOT_INSTRUMENTS or not instrument.startswith(f"{family}-"):
        raise C12AHistoricalCaptureError("futures archive target identity drift")
    start, end = _month_bounds(month)
    csv_raw = _read_archive_csv(raw, family=family, month=month)
    try:
        text = csv_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise C12AHistoricalCaptureError("futures CSV is not UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if tuple(reader.fieldnames or ()) != FUTURES_HEADER:
        raise C12AHistoricalCaptureError("futures CSV header drift")
    rows: list[dict[str, str]] = []
    seen_all: set[tuple[str, str]] = set()
    count = 0
    for index, row in enumerate(reader, start=2):
        count += 1
        if count > MAX_ARCHIVE_ROWS:
            raise C12AHistoricalCaptureError("futures CSV row cap exceeded")
        if None in row or set(row) != set(FUTURES_HEADER):
            raise C12AHistoricalCaptureError(f"futures CSV row {index} field drift")
        row_instrument = row["instrument_name"]
        trade_id = row["trade_id"]
        if not row_instrument.startswith(f"{family}-") or row_instrument.endswith(
            "-SWAP"
        ):
            raise C12AHistoricalCaptureError("futures CSV escaped its frozen family")
        if not trade_id or not trade_id.isdigit():
            raise C12AHistoricalCaptureError("futures trade ID is invalid")
        identity = (row_instrument, trade_id)
        if identity in seen_all:
            raise C12AHistoricalCaptureError("duplicate futures trade ID")
        seen_all.add(identity)
        side = row["side"].lower()
        if side not in {"buy", "sell"} or row["side"] != side:
            raise C12AHistoricalCaptureError("futures trade side drift")
        price = decimal_value(row["price"], "futures trade price", positive=True)
        size = decimal_value(row["size"], "futures trade size", positive=True)
        timestamp_text = row["created_time"]
        if not timestamp_text.isdigit():
            raise C12AHistoricalCaptureError(
                "futures trade timestamp is not milliseconds"
            )
        timestamp_ms = int(timestamp_text)
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
        local_timestamp = timestamp + UTC8
        if not (start + UTC8 <= local_timestamp < end + UTC8):
            raise C12AHistoricalCaptureError(
                "futures trade escaped archive UTC+8 month"
            )
        if row_instrument == instrument:
            rows.append(
                {
                    "instrument": instrument,
                    "trade_id": trade_id,
                    "side": side,
                    "price": str(price),
                    "size": str(size),
                    "timestamp": iso_z(timestamp),
                }
            )
    if not count:
        raise C12AHistoricalCaptureError("futures CSV is empty")
    if not rows:
        raise C12AHistoricalCaptureError(
            "frozen futures contract has no archive trades"
        )
    rows.sort(key=lambda item: (_timestamp(item["timestamp"]), int(item["trade_id"])))
    return tuple(rows)


def _months_for_decision(decision: ContractDecision) -> tuple[str, ...]:
    first = (decision.signal_cutoff - timedelta(hours=1)) + UTC8
    last = (decision.exit_timestamp + EXECUTION_MAX_DELAY) + UTC8
    output: list[str] = []
    current = datetime(first.year, first.month, 1, tzinfo=UTC)
    final = datetime(last.year, last.month, 1, tzinfo=UTC)
    while current <= final:
        output.append(current.strftime("%Y-%m"))
        current = datetime(
            current.year + (1 if current.month == 12 else 0),
            1 if current.month == 12 else current.month + 1,
            1,
            tzinfo=UTC,
        )
    return tuple(output)


def contracts_by_family_month(
    config: dict[str, Any] | None = None,
) -> dict[tuple[str, str], ContractDecision]:
    payload = config if config is not None else load_frozen_config()
    expected_months = tuple(payload.get("required_archive_months", ()))
    inventory: dict[tuple[str, str], ContractDecision] = {}
    for decision in contract_decisions(payload):
        for month in _months_for_decision(decision):
            key = (decision.spot_instrument, month)
            if key in inventory:
                raise C12AHistoricalCaptureError("overlapping C12A futures contracts")
            inventory[key] = decision
    if {month for _, month in inventory} != set(expected_months):
        raise C12AHistoricalCaptureError("required C12A archive-month inventory drift")
    if set(inventory) != {
        (family, month) for family in SPOT_INSTRUMENTS for month in expected_months
    }:
        raise C12AHistoricalCaptureError("C12A family/month inventory is incomplete")
    return inventory


def _timestamp(value: str) -> datetime:
    try:
        return utc_timestamp(value)
    except C12AError as exc:
        raise C12AHistoricalCaptureError(str(exc)) from exc


def validate_contract_trade_coverage(
    rows: Sequence[Mapping[str, Any]], *, decision: ContractDecision
) -> tuple[dict[str, str], ...]:
    """Prove signal, hourly marks, and bounded execution prints exist."""

    ordered: list[dict[str, str]] = []
    seen: set[str] = set()
    previous: tuple[datetime, int] | None = None
    for row in rows:
        if row.get("instrument") != decision.futures_instrument:
            raise C12AHistoricalCaptureError("normalized futures instrument drift")
        trade_id = str(row.get("trade_id", ""))
        if not trade_id.isdigit() or trade_id in seen:
            raise C12AHistoricalCaptureError("normalized futures trade ID drift")
        seen.add(trade_id)
        stamp = _timestamp(str(row.get("timestamp", "")))
        order = (stamp, int(trade_id))
        if previous is not None and order <= previous:
            raise C12AHistoricalCaptureError("normalized futures trades are unordered")
        previous = order
        ordered.append({key: str(value) for key, value in row.items()})
    if not ordered:
        raise C12AHistoricalCaptureError("normalized futures series is empty")

    hour_buckets: set[datetime] = set()
    timestamps: list[datetime] = []
    for row in ordered:
        stamp = _timestamp(row["timestamp"])
        timestamps.append(stamp)
        hour_buckets.add(stamp.replace(minute=0, second=0, microsecond=0))

    def require_hour(start: datetime, label: str) -> None:
        if start not in hour_buckets:
            raise C12AHistoricalCaptureError(f"missing futures {label}: {iso_z(start)}")

    def require_execution(start: datetime, label: str) -> None:
        if not any(start <= stamp <= start + EXECUTION_MAX_DELAY for stamp in timestamps):
            raise C12AHistoricalCaptureError(f"missing futures {label}: {iso_z(start)}")

    require_hour(
        decision.signal_cutoff - timedelta(hours=1),
        "signal hour",
    )
    current = decision.entry_timestamp
    while current < decision.exit_timestamp:
        require_hour(current, "carried hour")
        current += timedelta(hours=1)
    for stamp, label in (
        (decision.entry_timestamp, "entry execution"),
        (decision.exit_timestamp, "exit execution"),
    ):
        require_execution(stamp, label)
    return tuple(ordered)


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
        raise C12AHistoricalCaptureError("capture transport provenance mismatch")
    try:
        package.retain_raw(raw, record)
    except C7AHistoricalCaptureError as exc:
        raise C12AHistoricalCaptureError(str(exc)) from exc


def capture_futures_archives(
    package: CapturePackage,
    *,
    config: dict[str, Any] | None = None,
    fetch_manifest: PageFetcher = fetch_raw_c12a,
    fetch_archive: PageFetcher = fetch_raw_c12a,
    host: str = "openapi.okx.com",
    pause_seconds: float = 0.11,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, tuple[dict[str, str], ...]]:
    payload = config if config is not None else load_frozen_config()
    inventory = contracts_by_family_month(payload)
    if isinstance(pause_seconds, bool) or not 0 <= float(pause_seconds) <= 5:
        raise C12AHistoricalCaptureError(
            "capture pause must be between zero and five seconds"
        )
    combined: dict[str, dict[str, dict[str, str]]] = {
        decision.futures_instrument: {} for decision in contract_decisions(payload)
    }
    for index, ((family, month), decision) in enumerate(sorted(inventory.items())):
        if index and pause_seconds:
            sleeper(float(pause_seconds))
        manifest_request = build_futures_manifest_request(
            family=family, month=month, host=host
        )
        raw_manifest, manifest_record = fetch_manifest(manifest_request)
        _retain(package, manifest_request, raw_manifest, manifest_record)
        try:
            spec = normalize_futures_manifest(
                parse_json_object(raw_manifest),
                family=family,
                month=month,
                instrument=decision.futures_instrument,
            )
        except C7APublicDataError as exc:
            raise C12AHistoricalCaptureError(str(exc)) from exc
        archive_request = spec.request()
        raw_archive, archive_record = fetch_archive(archive_request)
        _retain(package, archive_request, raw_archive, archive_record)
        rows = normalize_futures_archive(
            raw_archive,
            family=family,
            month=month,
            instrument=decision.futures_instrument,
        )
        target = combined[decision.futures_instrument]
        for row in rows:
            trade_id = row["trade_id"]
            if trade_id in target:
                raise C12AHistoricalCaptureError(
                    "duplicate futures trade across archives"
                )
            target[trade_id] = row

    output: dict[str, tuple[dict[str, str], ...]] = {}
    by_instrument = {
        decision.futures_instrument: decision
        for decision in contract_decisions(payload)
    }
    for instrument, decision in by_instrument.items():
        start = decision.signal_cutoff - timedelta(hours=1)
        end = decision.exit_timestamp + timedelta(hours=1)
        rows = sorted(
            (
                row
                for row in combined[instrument].values()
                if start <= _timestamp(row["timestamp"]) < end
            ),
            key=lambda item: (_timestamp(item["timestamp"]), int(item["trade_id"])),
        )
        selected = validate_contract_trade_coverage(rows, decision=decision)
        try:
            package.retain_normalized_series(
                series_type="trades",
                instrument=instrument,
                start_inclusive=iso_z(start),
                end_exclusive=iso_z(end),
                rows=selected,
            )
        except C7AHistoricalCaptureError as exc:
            raise C12AHistoricalCaptureError(str(exc)) from exc
        output[instrument] = selected
    return output


def capture_plan(config: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = config if config is not None else load_frozen_config()
    decisions = contract_decisions(payload)
    return {
        "window_ids": [window.window_id for window in WINDOWS],
        "spot_instruments": list(SPOT_INSTRUMENTS),
        "futures_instruments": [item.futures_instrument for item in decisions],
        "required_archive_months": list(payload["required_archive_months"]),
        "spot_start_inclusive": str(payload["spot_capture_start"]),
        "spot_end_exclusive": iso_z(WINDOWS[-1].end),
        "futures_source": "OKX_OFFICIAL_MONTHLY_FUTURES_CHAIN_TRADES",
        "archive_calendar_timezone": "UTC+08:00",
    }


class C12ACapturePackage(CapturePackage):
    def __init__(self, root: Path):
        super().__init__(
            root,
            allowed_instruments=C12A_PUBLIC_INSTRUMENTS,
            public_trade_instruments=C12A_PUBLIC_INSTRUMENTS,
        )

    def finalize(
        self, *, implementation_sha: str, frozen_capture_plan: Mapping[str, Any]
    ) -> dict[str, Any]:
        self._assert_open()
        if not EXACT_SHA.fullmatch(implementation_sha):
            raise C12AHistoricalCaptureError("implementation SHA must be exact")
        plan = dict(frozen_capture_plan)
        if plan != capture_plan():
            raise C12AHistoricalCaptureError("capture plan is not frozen C12A H1-H5")
        if not self.records:
            raise C12AHistoricalCaptureError("capture package contains no raw objects")
        decisions = contract_decisions()
        expected = {
            ("trades", instrument): (
                str(plan["spot_start_inclusive"]),
                str(plan["spot_end_exclusive"]),
            )
            for instrument in SPOT_INSTRUMENTS
        }
        expected.update(
            {
                ("trades", item.futures_instrument): (
                    iso_z(item.signal_cutoff - timedelta(hours=1)),
                    iso_z(item.exit_timestamp + timedelta(hours=1)),
                )
                for item in decisions
            }
        )
        if self._normalized_series != expected:
            raise C12AHistoricalCaptureError("normalized C12A source inventory drift")
        self.write_json(
            "capture_index.json",
            {
                "schema_version": 1,
                "stage": "C12A_HISTORICAL_CAPTURE",
                "implementation_sha": implementation_sha,
                "capture_plan": plan,
                "records": [record.to_dict() for record in self.records],
                "source_kind": "OFFICIAL_PUBLIC_OKX",
                **safety_boundary(),
            },
        )
        entries = sorted(self.root.rglob("*"))
        if any(path.is_symlink() for path in entries):
            raise C12AHistoricalCaptureError("capture package contains a symbolic link")
        files: list[dict[str, Any]] = []
        for path in (item for item in entries if item.is_file()):
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
            "stage": "C12A_HISTORICAL_CAPTURE_PACKAGE",
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


def capture_spot_history(
    package: C12ACapturePackage,
    *,
    config: dict[str, Any] | None = None,
    fetch_page: PageFetcher | None = None,
) -> dict[str, tuple[dict[str, str], ...]]:
    payload = config if config is not None else load_frozen_config()
    plan = capture_plan(payload)
    output: dict[str, tuple[dict[str, str], ...]] = {}
    for instrument in SPOT_INSTRUMENTS:
        kwargs: dict[str, Any] = {
            "package": package,
            "instrument": instrument,
            "start_inclusive": plan["spot_start_inclusive"],
            "end_exclusive": plan["spot_end_exclusive"],
        }
        if fetch_page is not None:
            kwargs["fetch_page"] = fetch_page
        try:
            output[instrument] = capture_trade_range(**kwargs)
        except (C7AHistoricalCaptureError, RuntimeError) as exc:
            raise C12AHistoricalCaptureError(str(exc)) from exc
    return output


__all__ = [
    "C12A_MAX_EXTRACTED_DOWNLOAD_BYTES",
    "FUTURES_HEADER",
    "C12ACapturePackage",
    "C12AHistoricalCaptureError",
    "FuturesArchiveSpec",
    "build_futures_manifest_request",
    "capture_futures_archives",
    "capture_plan",
    "capture_spot_history",
    "contracts_by_family_month",
    "fetch_raw_c12a",
    "normalize_futures_archive",
    "normalize_futures_manifest",
    "validate_c12a_public_request",
    "validate_contract_trade_coverage",
]
