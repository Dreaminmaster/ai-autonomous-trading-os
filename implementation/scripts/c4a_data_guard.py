#!/usr/bin/env python3
"""Seal and verify C4A public four-hour candles below the frozen boundary."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c4a_cross_sectional_runtime import CANDIDATE_PAIRS, validate_config
from atos.profitability_diagnostics import discover_candle_file, load_candles

IMPL = Path(__file__).resolve().parents[1]
CONFIG_PATH = IMPL / "config/c4a_large_liquid_cross_sectional_momentum.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RUNTIME = IMPL / "freqtrade_data/c4a_runtime"
BOUNDARY_PATH = RUNTIME / "c4a_data_boundary.json"
COVERAGE_PATH = RUNTIME / "c4a_data_coverage.json"
DOWNLOAD_START = datetime(2023, 9, 1, tzinfo=UTC)
FORMATION_END = datetime(2024, 1, 1, tzinfo=UTC)
BOUNDARY = datetime(2024, 10, 1, tzinfo=UTC)
STEP = timedelta(hours=4)
EXPECTED_ROWS = 2376
POLICY = "REJECT_UNORDERED_OR_DUPLICATE_THEN_REMOVE_API_OVERSHOOT_AT_OR_AFTER_C4A_BOUNDARY"


class C4ADataGuardError(RuntimeError):
    pass


def _timestamp(value: Any) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        raw = float(value)
        parsed = datetime.fromtimestamp(raw / (1000 if raw > 10_000_000_000 else 1), tz=UTC)
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise C4ADataGuardError(f"invalid candle timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C4ADataGuardError(f"unreadable file {path}: {exc}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    suffix = path.suffix.lower()
    if suffix == ".feather":
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover
            raise C4ADataGuardError("pandas/pyarrow required for Feather") from exc
        temporary = path.with_name(path.stem + ".c4a.tmp.feather")
        pd.DataFrame([dict(row) for row in rows]).to_feather(temporary)
        temporary.replace(path)
        return
    if suffix == ".csv":
        if not rows:
            raise C4ADataGuardError("cannot write empty candle CSV")
        fields = list(rows[0].keys())
        temporary = path.with_name(path.name + ".c4a.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(dict(row) for row in rows)
        temporary.replace(path)
        return
    if suffix == ".json":
        temporary = path.with_name(path.name + ".c4a.tmp")
        temporary.write_text(json.dumps([dict(row) for row in rows], default=str), encoding="utf-8")
        temporary.replace(path)
        return
    raise C4ADataGuardError(f"unsupported candle format: {path.suffix}")


def load_config() -> dict[str, Any]:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C4ADataGuardError(f"invalid C4A config: {exc}") from exc
    validate_config(payload)
    return payload


def _validate_numeric_rows(rows: Sequence[Mapping[str, Any]], pair: str) -> None:
    for row in rows:
        values: dict[str, float] = {}
        for field in ("open", "high", "low", "close", "volume"):
            try:
                value = float(row.get(field))
            except (TypeError, ValueError) as exc:
                raise C4ADataGuardError(f"{pair} invalid {field}") from exc
            if not math.isfinite(value) or value <= 0:
                raise C4ADataGuardError(f"{pair} non-positive/non-finite {field}")
            values[field] = value
        if values["low"] > values["high"]:
            raise C4ADataGuardError(f"{pair} low exceeds high")
        if not values["low"] <= values["open"] <= values["high"]:
            raise C4ADataGuardError(f"{pair} open outside high/low")
        if not values["low"] <= values["close"] <= values["high"]:
            raise C4ADataGuardError(f"{pair} close outside high/low")


def sanitize_file(path: Path, pair: str) -> dict[str, Any]:
    rows = load_candles(path)
    if not rows:
        raise C4ADataGuardError(f"no candles for {pair}")
    dated = [(_timestamp(row.get("date")), dict(row)) for row in rows]
    dates = [item[0] for item in dated]
    if dates != sorted(dates):
        raise C4ADataGuardError(f"unordered candles before sanitization for {pair}")
    if len(set(dates)) != len(dates):
        raise C4ADataGuardError(f"duplicate candles before sanitization for {pair}")
    retained = [row for when, row in dated if when < BOUNDARY]
    removed = [when for when, _ in dated if when >= BOUNDARY]
    if not retained:
        raise C4ADataGuardError(f"sanitization removed every candle for {pair}")
    _validate_numeric_rows(retained, pair)
    before_sha = _sha256(path)
    _write_rows(path, retained)
    reread = load_candles(path)
    reread_dates = [_timestamp(row.get("date")) for row in reread]
    if reread_dates != sorted(reread_dates) or len(set(reread_dates)) != len(reread_dates):
        raise C4ADataGuardError(f"sealed sequence invalid for {pair}")
    if len(reread) != len(retained):
        raise C4ADataGuardError(f"row count changed while sealing {pair}")
    if not reread_dates or reread_dates[-1] >= BOUNDARY:
        raise C4ADataGuardError(f"post-boundary candle remains for {pair}")
    return {
        "pair": pair,
        "timeframe": "4h",
        "path": str(path.relative_to(IMPL)),
        "original_rows": len(rows),
        "retained_rows": len(reread),
        "removed_rows": len(removed),
        "original_latest": dates[-1].isoformat(),
        "retained_latest": reread_dates[-1].isoformat(),
        "first_removed": removed[0].isoformat() if removed else None,
        "last_removed": removed[-1].isoformat() if removed else None,
        "sha256_before": before_sha,
        "sha256_after": _sha256(path),
        "post_boundary_rows": 0,
        "status": "PASS",
    }


def expected_timestamps() -> list[datetime]:
    values = [DOWNLOAD_START + index * STEP for index in range(EXPECTED_ROWS)]
    if values[-1] != BOUNDARY - STEP:
        raise C4ADataGuardError("internal expected timestamp grid mismatch")
    return values


def validate_rows(rows: Sequence[Mapping[str, Any]], pair: str) -> dict[str, Any]:
    if pair not in CANDIDATE_PAIRS:
        raise C4ADataGuardError(f"unexpected pair: {pair}")
    if not rows:
        raise C4ADataGuardError(f"no candles for {pair}")
    dates = [_timestamp(row.get("date")) for row in rows]
    expected = expected_timestamps()
    if dates != expected:
        raise C4ADataGuardError(f"{pair} exact four-hour coverage mismatch")
    _validate_numeric_rows(rows, pair)
    formation_rows = sum(date < FORMATION_END for date in dates)
    if formation_rows != 732 or len(dates) - formation_rows != 1644:
        raise C4ADataGuardError(f"{pair} formation/screen count mismatch")
    timestamp_digest = hashlib.sha256(
        "\n".join(date.isoformat() for date in dates).encode("utf-8")
    ).hexdigest()
    return {
        "pair": pair,
        "timeframe": "4h",
        "rows": len(rows),
        "formation_rows": formation_rows,
        "screen_rows": len(dates) - formation_rows,
        "earliest": dates[0].isoformat(),
        "latest": dates[-1].isoformat(),
        "timestamp_sha256": timestamp_digest,
        "duplicates": 0,
        "gaps": 0,
        "status": "PASS",
    }


def build_boundary_report(config: Mapping[str, Any], source_sha: str) -> dict[str, Any]:
    cells = [
        sanitize_file(discover_candle_file(DATA_DIR, pair, "4h"), pair)
        for pair in config["candidate_pairs"]
    ]
    if len(cells) != 12:
        raise C4ADataGuardError("boundary report must contain twelve cells")
    return {
        "schema_version": 1,
        "stage": "C4A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "policy": POLICY,
        "cells": sorted(cells, key=lambda item: item["pair"]),
    }


def validate_boundary_report(payload: Mapping[str, Any], source_sha: str) -> None:
    if payload.get("stage") != "C4A" or payload.get("status") != "PASS":
        raise C4ADataGuardError("boundary report identity or status mismatch")
    if payload.get("source_head_sha") != source_sha:
        raise C4ADataGuardError("boundary source mismatch")
    if payload.get("economic_boundary_exclusive") != BOUNDARY.isoformat():
        raise C4ADataGuardError("boundary timestamp drift")
    if payload.get("policy") != POLICY:
        raise C4ADataGuardError("boundary policy drift")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C4ADataGuardError("boundary safety drift")
    cells = payload.get("cells")
    if not isinstance(cells, list) or len(cells) != 12:
        raise C4ADataGuardError("boundary cell count mismatch")
    for cell in cells:
        if not isinstance(cell, Mapping) or cell.get("status") != "PASS":
            raise C4ADataGuardError("invalid boundary cell")
        if cell.get("post_boundary_rows") != 0 or _timestamp(cell.get("retained_latest")) >= BOUNDARY:
            raise C4ADataGuardError("boundary cell is not sealed")


def build_coverage_report(
    config: Mapping[str, Any],
    boundary: Mapping[str, Any],
    source_sha: str,
) -> dict[str, Any]:
    validate_boundary_report(boundary, source_sha)
    cells: list[dict[str, Any]] = []
    for pair in config["candidate_pairs"]:
        path = discover_candle_file(DATA_DIR, pair, "4h")
        item = validate_rows(load_candles(path), pair)
        item["path"] = str(path.relative_to(IMPL))
        item["sha256"] = _sha256(path)
        cells.append(item)
    sequence_hashes = {item["timestamp_sha256"] for item in cells}
    if len(cells) != 12 or len(sequence_hashes) != 1:
        raise C4ADataGuardError("candidate coverage alignment mismatch")
    return {
        "schema_version": 1,
        "stage": "C4A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "download_timerange": config["download_timerange"],
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "retained_rows_per_pair": EXPECTED_ROWS,
        "timestamp_sha256": next(iter(sequence_hashes)),
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "boundary_path": str(BOUNDARY_PATH.relative_to(IMPL)),
        "boundary_sha256": _sha256(BOUNDARY_PATH),
        "cells": sorted(cells, key=lambda item: item["pair"]),
    }


def _failure(mode: str, source_sha: str, error: Exception) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "stage": "C4A",
        "status": "FAIL",
        "mode": mode,
        "source_head_sha": source_sha,
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "error_type": type(error).__name__,
        "error": str(error),
        "cells": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("sanitize", "verify"))
    args = parser.parse_args()
    source_sha = os.environ.get("C4A_SOURCE_SHA", os.environ.get("GITHUB_SHA", "local"))
    output = BOUNDARY_PATH if args.mode == "sanitize" else COVERAGE_PATH
    try:
        config = load_config()
        if args.mode == "sanitize":
            report = build_boundary_report(config, source_sha)
        else:
            boundary = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
            report = build_coverage_report(config, boundary, source_sha)
    except Exception as exc:
        report = _failure(args.mode, source_sha, exc)
        _write_json(output, report)
        print(f"C4A data {args.mode} FAIL: {type(exc).__name__}: {exc}")
        raise
    _write_json(output, report)
    print(f"C4A data {args.mode} PASS: {len(report['cells'])} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
