#!/usr/bin/env python3
"""Seal and verify the exact public C5A input boundary."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c5a_derivatives_crowding import (
    BOUNDARY,
    DOWNLOAD_START,
    EXPECTED_CONFIG_CANONICAL_SHA256,
    canonical_sha256,
    expected_timestamps,
    validate_config,
)

IMPL = Path(__file__).resolve().parents[1]
CONFIG_PATH = IMPL / "config/c5a_derivatives_crowding_regime.json"
INPUT_ROOT = IMPL / "freqtrade_data/c5a_public_input"
RAW_ROOT = INPUT_ROOT / "raw"
SEALED_ROOT = INPUT_ROOT / "sealed"
RUNTIME_ROOT = IMPL / "freqtrade_data/c5a_runtime"
BOUNDARY_REPORT = RUNTIME_ROOT / "c5a_data_boundary.json"
COVERAGE_REPORT = RUNTIME_ROOT / "c5a_data_coverage.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class C5ADataGuardError(RuntimeError):
    pass


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        raw = float(value)
        parsed = datetime.fromtimestamp(raw / (1000 if raw > 10_000_000_000 else 1), tz=UTC)
    else:
        raise C5ADataGuardError(f"invalid timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(IMPL))
    except ValueError:
        return str(path)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _read_rows(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C5ADataGuardError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(payload, list) or any(not isinstance(row, Mapping) for row in payload):
        raise C5ADataGuardError(f"candle file must be a list of objects: {path}")
    return [dict(row) for row in payload]


def _source_sha() -> str:
    value = os.environ.get("C5A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C5ADataGuardError("C5A_SOURCE_SHA must be an exact lowercase 40-character SHA")
    return value


def _config() -> dict[str, Any]:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if canonical_sha256(payload) != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C5ADataGuardError("C5A config hash drift")
    validate_config(payload)
    return payload


def _validate_numeric(row: Mapping[str, Any], fields: Sequence[str], label: str) -> None:
    values: dict[str, float] = {}
    for field in fields:
        try:
            value = float(row[field])
        except (KeyError, TypeError, ValueError) as exc:
            raise C5ADataGuardError(f"{label} invalid {field}") from exc
        if not math.isfinite(value):
            raise C5ADataGuardError(f"{label} non-finite {field}")
        values[field] = value
    for field in fields:
        if field == "quote_volume":
            if values[field] < 0:
                raise C5ADataGuardError(f"{label} negative quote volume")
        elif values[field] <= 0:
            raise C5ADataGuardError(f"{label} non-positive {field}")
    if {"open", "high", "low", "close"}.issubset(values):
        if (
            values["low"] > values["high"]
            or not values["low"] <= values["open"] <= values["high"]
            or not values["low"] <= values["close"] <= values["high"]
        ):
            raise C5ADataGuardError(f"{label} invalid OHLC geometry")


def seal_file(
    raw_path: Path,
    sealed_path: Path,
    *,
    fields: Sequence[str],
    label: str,
) -> dict[str, Any]:
    rows = _read_rows(raw_path)
    timestamps = [_timestamp(row.get("date")) for row in rows]
    if timestamps != sorted(timestamps) or len(set(timestamps)) != len(timestamps):
        raise C5ADataGuardError(f"{label} raw timestamps unordered or duplicated")
    for row in rows:
        _validate_numeric(row, fields, label)
    retained = [row for row, stamp in zip(rows, timestamps, strict=True) if DOWNLOAD_START <= stamp < BOUNDARY]
    removed = [stamp for stamp in timestamps if stamp >= BOUNDARY]
    sealed_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json(sealed_path, retained)
    return {
        "label": label,
        "raw_path": _display_path(raw_path),
        "sealed_path": _display_path(sealed_path),
        "raw_rows": len(rows),
        "retained_rows": len(retained),
        "removed_post_boundary_rows": len(removed),
        "first_removed": removed[0].isoformat() if removed else None,
        "last_removed": removed[-1].isoformat() if removed else None,
        "raw_sha256": _sha256(raw_path),
        "sealed_sha256": _sha256(sealed_path),
        "status": "PASS",
    }


def verify_file(
    path: Path,
    *,
    fields: Sequence[str],
    label: str,
) -> dict[str, Any]:
    rows = _read_rows(path)
    timestamps = [_timestamp(row.get("date")) for row in rows]
    if tuple(timestamps) != expected_timestamps():
        raise C5ADataGuardError(f"{label} exact four-hour coverage mismatch")
    for row in rows:
        _validate_numeric(row, fields, label)
    return {
        "label": label,
        "path": _display_path(path),
        "rows": len(rows),
        "earliest": timestamps[0].isoformat(),
        "latest": timestamps[-1].isoformat(),
        "sha256": _sha256(path),
        "timestamp_sha256": hashlib.sha256(
            "\n".join(stamp.isoformat() for stamp in timestamps).encode("utf-8")
        ).hexdigest(),
        "gaps": 0,
        "duplicates": 0,
        "status": "PASS",
    }


def _files(config: Mapping[str, Any]):
    for spot in config["spot_instruments"]:
        yield (
            RAW_ROOT / "spot" / f"{spot}.json",
            SEALED_ROOT / "spot" / f"{spot}.json",
            ("open", "high", "low", "close", "quote_volume"),
            f"spot:{spot}",
        )
    for swap in config["swap_instruments"]:
        yield (
            RAW_ROOT / "swap" / f"{swap}.json",
            SEALED_ROOT / "swap" / f"{swap}.json",
            ("quote_volume",),
            f"swap:{swap}",
        )
        yield (
            RAW_ROOT / "mark" / f"{swap}.json",
            SEALED_ROOT / "mark" / f"{swap}.json",
            ("close",),
            f"mark:{swap}",
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("sanitize", "verify"))
    args = parser.parse_args()
    config = _config()
    source_sha = _source_sha()
    if args.mode == "sanitize":
        cells = [
            seal_file(raw, sealed, fields=fields, label=label)
            for raw, sealed, fields, label in _files(config)
        ]
        payload = {
            "schema_version": 1,
            "stage": "C5A",
            "mode": "sanitize",
            "status": "PASS",
            "source_head_sha": source_sha,
            "config_canonical_sha256": EXPECTED_CONFIG_CANONICAL_SHA256,
            "economic_boundary_exclusive": BOUNDARY.isoformat(),
            "cell_count": len(cells),
            "cells": cells,
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        }
        _write_json(BOUNDARY_REPORT, payload)
        print(f"C5A data boundary PASS: {len(cells)} public series")
        return 0

    boundary = json.loads(BOUNDARY_REPORT.read_text(encoding="utf-8"))
    if (
        boundary.get("status") != "PASS"
        or boundary.get("source_head_sha") != source_sha
        or boundary.get("economic_boundary_exclusive") != BOUNDARY.isoformat()
        or boundary.get("cell_count") != 9
    ):
        raise C5ADataGuardError("C5A boundary report mismatch")
    cells = [
        verify_file(sealed, fields=fields, label=label)
        for _, sealed, fields, label in _files(config)
    ]
    hashes = {cell["timestamp_sha256"] for cell in cells}
    if len(cells) != 9 or len(hashes) != 1:
        raise C5ADataGuardError("C5A sealed-series alignment mismatch")
    payload = {
        "schema_version": 1,
        "stage": "C5A",
        "mode": "verify",
        "status": "PASS",
        "source_head_sha": source_sha,
        "config_canonical_sha256": EXPECTED_CONFIG_CANONICAL_SHA256,
        "download_start": DOWNLOAD_START.isoformat(),
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "rows_per_series": 2940,
        "cell_count": len(cells),
        "timestamp_sha256": next(iter(hashes)),
        "boundary_report_sha256": _sha256(BOUNDARY_REPORT),
        "cells": cells,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    _write_json(COVERAGE_REPORT, payload)
    print(f"C5A data coverage PASS: {len(cells)} aligned public series")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
