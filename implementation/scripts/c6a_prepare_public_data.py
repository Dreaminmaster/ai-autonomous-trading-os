#!/usr/bin/env python3
"""Prepare canonical C6A primitive inputs from hash-verified public objects.

The source archive layout is never guessed silently.  ZIP entries require an
exact `archive_member` in the reviewed source manifest.  Supported record
encodings are CSV with named columns, JSON/JSONL objects, or the documented OKX
candlestick array schema.  All outputs are validated before publication.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from atos.c6a_contract import (
    C6AError,
    FundingRecord,
    MetadataRecord,
    SPOT_INSTRUMENTS,
    SWAP_INSTRUMENTS,
    validate_funding_records,
)
from atos.c6a_data import (
    ECONOMIC_BOUNDARY,
    DOWNLOAD_START,
    strip_boundary_overshoot,
    validate_mark_candles,
    validate_trade_candles,
)
from atos.c6a_evidence import sha256_file, write_json_atomic
from atos.c6a_sources import PublicSourceEntry, validate_source_manifest

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_DOWNLOAD_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_download_report.json"
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_canonical"
DEFAULT_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_prepare_report.json"
MAX_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024


class C6APrepareError(RuntimeError):
    pass


def _safe_member(name: str) -> str:
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts or not path.name:
        raise C6APrepareError(f"unsafe archive member: {name!r}")
    return path.as_posix()


def _decode_records(data: bytes, *, name: str) -> list[Any]:
    suffix = Path(name).suffix.lower()
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise C6APrepareError(f"non-UTF-8 public object: {name}") from exc
    if suffix == ".csv":
        reader = csv.DictReader(io.StringIO(text))
        if reader.fieldnames is None:
            raise C6APrepareError(f"CSV header missing: {name}")
        rows = [dict(row) for row in reader]
    elif suffix in {".jsonl", ".ndjson"}:
        rows = []
        for number, line in enumerate(text.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise C6APrepareError(f"invalid JSONL {name}:{number}: {exc}") from exc
    elif suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise C6APrepareError(f"invalid JSON object: {name}: {exc}") from exc
        if isinstance(payload, Mapping) and isinstance(payload.get("data"), list):
            rows = list(payload["data"])
        elif isinstance(payload, list):
            rows = payload
        else:
            raise C6APrepareError(f"JSON must be a list or contain list data: {name}")
    else:
        raise C6APrepareError(f"unsupported public record encoding: {name}")
    if not rows:
        raise C6APrepareError(f"public record object is empty: {name}")
    return rows


def load_records(path: Path, entry: PublicSourceEntry) -> list[Any]:
    if not path.is_file() or path.is_symlink():
        raise C6APrepareError(f"downloaded source missing or unsafe: {path}")
    if path.suffix.lower() == ".zip":
        if not entry.archive_member:
            raise C6APrepareError(
                f"ZIP source requires exact archive_member: {entry.source_id}"
            )
        member = _safe_member(entry.archive_member)
        try:
            with zipfile.ZipFile(path) as archive:
                names = [_safe_member(info.filename) for info in archive.infolist() if not info.is_dir()]
                if names.count(member) != 1:
                    raise C6APrepareError(
                        f"expected one exact ZIP member {member!r}, found {names.count(member)}"
                    )
                info = archive.getinfo(member)
                if info.file_size > MAX_UNCOMPRESSED_BYTES:
                    raise C6APrepareError(f"ZIP member too large: {member}")
                data = archive.read(info)
        except (OSError, zipfile.BadZipFile, KeyError) as exc:
            raise C6APrepareError(f"invalid ZIP source {path}: {exc}") from exc
        return _decode_records(data, name=member)
    if entry.archive_member:
        raise C6APrepareError(
            f"archive_member supplied for non-ZIP source: {entry.source_id}"
        )
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise C6APrepareError(f"unable to read source {path}: {exc}") from exc
    if len(data) > MAX_UNCOMPRESSED_BYTES:
        raise C6APrepareError(f"public source too large after download: {path}")
    return _decode_records(data, name=path.name)


def _first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def normalize_candle(row: Any, *, mark: bool = False) -> dict[str, Any]:
    if isinstance(row, Sequence) and not isinstance(row, (str, bytes, bytearray)):
        if len(row) < 5:
            raise C6APrepareError("candlestick array has fewer than five fields")
        normalized = {
            "timestamp": row[0],
            "open": row[1],
            "high": row[2],
            "low": row[3],
            "close": row[4],
        }
        if not mark:
            normalized["quote_volume"] = row[7] if len(row) > 7 else "0"
        if len(row) > 8 and str(row[8]) != "1":
            raise C6APrepareError("unconfirmed candlestick is not permitted")
        return normalized
    if not isinstance(row, Mapping):
        raise C6APrepareError("candlestick row must be an object or array")
    confirmed = _first(row, "confirm", "confirmed")
    if confirmed is not None and str(confirmed).lower() not in {"1", "true"}:
        raise C6APrepareError("unconfirmed candlestick is not permitted")
    normalized = {
        "timestamp": _first(row, "timestamp", "date", "ts", "open_time", "time"),
        "open": _first(row, "open", "o"),
        "high": _first(row, "high", "h"),
        "low": _first(row, "low", "l"),
        "close": _first(row, "close", "c"),
    }
    if not mark:
        normalized["quote_volume"] = _first(
            row, "quote_volume", "quoteVolume", "volCcyQuote", "volume_quote"
        ) or "0"
    if any(value is None for value in normalized.values()):
        raise C6APrepareError(f"candlestick field missing: {normalized}")
    return normalized


def normalize_funding(row: Any, *, instrument: str) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise C6APrepareError("funding row must be an object")
    observed = _first(row, "instrument", "instId") or instrument
    if observed != instrument:
        raise C6APrepareError(
            f"funding instrument mismatch: {observed!r} != {instrument!r}"
        )
    timestamp = _first(row, "funding_time", "fundingTime", "timestamp", "ts")
    rate = _first(row, "realized_rate", "realizedRate", "fundingRate", "rate")
    if timestamp is None or rate is None:
        raise C6APrepareError("funding timestamp or realized rate missing")
    return {
        "instrument": instrument,
        "funding_time": timestamp,
        "realized_rate": rate,
    }


def normalize_metadata(row: Any, *, instrument: str) -> dict[str, Any]:
    if not isinstance(row, Mapping):
        raise C6APrepareError("metadata row must be an object")
    result = dict(row)
    observed = _first(result, "instrument", "instId") or instrument
    if observed != instrument:
        raise C6APrepareError(
            f"metadata instrument mismatch: {observed!r} != {instrument!r}"
        )
    result["instrument"] = instrument
    required = ("effective_from", "source", "source_sha256")
    missing = [name for name in required if result.get(name) in (None, "")]
    if missing:
        raise C6APrepareError(
            f"historical metadata lacks explicit authority fields {missing}: {instrument}"
        )
    return result


def _write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    count = 0
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            count += 1
    temporary.replace(path)
    return {
        "path": str(path),
        "row_count": count,
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def prepare(
    *,
    source_manifest: Mapping[str, Any],
    download_report: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    entries = validate_source_manifest(source_manifest)
    if download_report.get("status") != "PASS" or download_report.get("authenticated") is not False:
        raise C6APrepareError("download report is not a valid unauthenticated PASS")
    guard = download_report.get("program_guard")
    if not isinstance(guard, Mapping) or guard.get("status") != "PASS" or guard.get("verified_before_market_access") is not True:
        raise C6APrepareError("download report lacks pre-access program guard")
    downloaded = download_report.get("sources")
    if not isinstance(downloaded, list):
        raise C6APrepareError("download report source list missing")
    by_id = {str(row.get("source_id")): row for row in downloaded if isinstance(row, Mapping)}
    if set(by_id) != {entry.source_id for entry in entries}:
        raise C6APrepareError("download report/source manifest ID mismatch")

    grouped: dict[tuple[str, str], list[tuple[PublicSourceEntry, list[Any]]]] = defaultdict(list)
    for entry in entries:
        report_row = by_id[entry.source_id]
        path = Path(str(report_row.get("path", "")))
        if report_row.get("status") != "PASS" or report_row.get("sha256") != entry.sha256:
            raise C6APrepareError(f"download report hash/status mismatch: {entry.source_id}")
        if not path.is_file() or sha256_file(path) != entry.sha256:
            raise C6APrepareError(f"downloaded file hash mismatch: {entry.source_id}")
        grouped[(entry.kind, entry.instrument)].append((entry, load_records(path, entry)))

    outputs: list[dict[str, Any]] = []
    boundary_reports: list[dict[str, Any]] = []
    for kind in ("spot_trade_candles", "swap_trade_candles", "swap_mark_candles"):
        instruments = SPOT_INSTRUMENTS if kind == "spot_trade_candles" else SWAP_INSTRUMENTS
        for instrument in instruments:
            raw: list[dict[str, Any]] = []
            for entry, rows in sorted(grouped[(kind, instrument)], key=lambda item: item[0].coverage_start):
                raw.extend(normalize_candle(row, mark=kind == "swap_mark_candles") for row in rows)
            raw.sort(key=lambda row: str(row["timestamp"]))
            retained, boundary = strip_boundary_overshoot(raw)
            if kind == "swap_mark_candles":
                validated = validate_mark_candles(retained, instrument=instrument)
                canonical = [
                    {
                        "timestamp": row.timestamp.isoformat(),
                        "open": str(row.open),
                        "high": str(row.high),
                        "low": str(row.low),
                        "close": str(row.close),
                    }
                    for row in validated
                ]
            else:
                validated = validate_trade_candles(retained, instrument=instrument)
                canonical = [
                    {
                        "timestamp": row.timestamp.isoformat(),
                        "open": str(row.open),
                        "high": str(row.high),
                        "low": str(row.low),
                        "close": str(row.close),
                        "quote_volume": str(row.quote_volume),
                    }
                    for row in validated
                ]
            outputs.append(
                {
                    "kind": kind,
                    "instrument": instrument,
                    **_write_jsonl(output_dir / kind / f"{instrument}.jsonl", canonical),
                }
            )
            boundary_reports.append(
                {
                    "kind": kind,
                    "instrument": instrument,
                    "retained_rows": boundary.retained_rows,
                    "removed_rows": boundary.removed_rows,
                    "first_removed_timestamp": None if boundary.first_removed_timestamp is None else boundary.first_removed_timestamp.isoformat(),
                    "last_removed_timestamp": None if boundary.last_removed_timestamp is None else boundary.last_removed_timestamp.isoformat(),
                }
            )

    funding_rows: list[dict[str, Any]] = []
    for instrument in SWAP_INSTRUMENTS:
        for entry, rows in sorted(grouped[("funding_history", instrument)], key=lambda item: item[0].coverage_start):
            funding_rows.extend(normalize_funding(row, instrument=instrument) for row in rows)
    parsed_funding = validate_funding_records(funding_rows)
    funding_output = [
        {
            "instrument": row.instrument,
            "funding_time": row.funding_time.isoformat(),
            "realized_rate": str(row.realized_rate),
        }
        for row in parsed_funding
    ]
    outputs.append(
        {
            "kind": "funding_history",
            "instrument": "ALL",
            **_write_jsonl(output_dir / "funding_history" / "funding.jsonl", funding_output),
        }
    )

    metadata_rows: list[MetadataRecord] = []
    for instrument in (*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS):
        for entry, rows in sorted(grouped[("instrument_metadata", instrument)], key=lambda item: item[0].coverage_start):
            metadata_rows.extend(
                MetadataRecord.from_mapping(normalize_metadata(row, instrument=instrument))
                for row in rows
            )
    metadata_rows.sort(key=lambda row: (row.instrument, row.effective_from))
    # Require exactly one effective record for every decision/terminal transaction hour.
    for instrument in (*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS):
        selected = [row for row in metadata_rows if row.instrument == instrument]
        if not selected:
            raise C6APrepareError(f"historical metadata missing: {instrument}")
        previous_end = None
        for row in selected:
            if previous_end is not None and row.effective_from != previous_end:
                raise C6APrepareError(f"historical metadata gap/overlap: {instrument}")
            previous_end = row.effective_to
            if previous_end is None:
                break
        if selected[0].effective_from > DOWNLOAD_START or (
            selected[-1].effective_to is not None
            and selected[-1].effective_to < ECONOMIC_BOUNDARY
        ):
            raise C6APrepareError(f"historical metadata coverage incomplete: {instrument}")
    metadata_output = [
        {
            "instrument": row.instrument,
            "instrument_type": row.instrument_type,
            "base_currency": row.base_currency,
            "quote_currency": row.quote_currency,
            "settlement_currency": row.settlement_currency,
            "contract_value": None if row.contract_value is None else str(row.contract_value),
            "contract_value_currency": row.contract_value_currency,
            "lot_size": str(row.lot_size),
            "minimum_size": str(row.minimum_size),
            "tick_size": str(row.tick_size),
            "effective_from": row.effective_from.isoformat(),
            "effective_to": None if row.effective_to is None else row.effective_to.isoformat(),
            "source": row.source,
            "source_sha256": row.source_sha256,
        }
        for row in metadata_rows
    ]
    outputs.append(
        {
            "kind": "instrument_metadata",
            "instrument": "ALL",
            **_write_jsonl(output_dir / "instrument_metadata" / "metadata.jsonl", metadata_output),
        }
    )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "download_start": DOWNLOAD_START.isoformat(),
        "economic_boundary_exclusive": ECONOMIC_BOUNDARY.isoformat(),
        "outputs": outputs,
        "boundary_reports": boundary_reports,
        "funding_row_count": len(funding_output),
        "metadata_row_count": len(metadata_output),
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--download-report", type=Path, default=DEFAULT_DOWNLOAD_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)
    try:
        source_manifest = json.loads(args.source_manifest.read_text(encoding="utf-8"))
        download_report = json.loads(args.download_report.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6APrepareError(f"unable to load C6A preparation inputs: {exc}") from exc
    if not isinstance(source_manifest, Mapping) or not isinstance(download_report, Mapping):
        raise C6APrepareError("C6A preparation inputs must be objects")
    try:
        report = prepare(
            source_manifest=source_manifest,
            download_report=download_report,
            output_dir=args.output_dir,
        )
    except C6AError as exc:
        raise C6APrepareError(str(exc)) from exc
    write_json_atomic(args.report, report)
    print(
        "C6A public preparation PASS: "
        f"{len(report['outputs'])} canonical objects / no economic result"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
