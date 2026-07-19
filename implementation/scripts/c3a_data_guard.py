#!/usr/bin/env python3
"""Seal and verify C3A four-hour public market data below the frozen boundary."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c3a_residual_reversion import PAIR_ORDER, validate_config
from atos.profitability_diagnostics import discover_candle_file, load_candles


IMPL = Path(__file__).resolve().parents[1]
CONFIG_PATH = IMPL / "config/c3a_residual_mean_reversion.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RUNTIME = IMPL / "freqtrade_data/c3a_runtime"
BOUNDARY_PATH = RUNTIME / "c3a_data_boundary.json"
COVERAGE_PATH = RUNTIME / "c3a_data_coverage.json"
BOUNDARY = datetime(2024, 10, 1, tzinfo=UTC)
FIRST_SCREEN = datetime(2024, 1, 1, tzinfo=UTC)
STEP = timedelta(hours=4)
POLICY = "REMOVE_API_OVERSHOOT_AT_OR_AFTER_C3A_BOUNDARY_BEFORE_ANY_RESEARCH_READ"


class C3ADataGuardError(RuntimeError):
    pass


def _timestamp(value: Any) -> datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / (1000 if float(value) > 10_000_000_000 else 1)
        parsed = datetime.fromtimestamp(seconds, tz=UTC)
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise C3ADataGuardError(f"invalid candle timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C3ADataGuardError(f"unreadable file {path}: {exc}") from exc


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    suffix = path.suffix.lower()
    if suffix == ".feather":
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency is present in research jobs
            raise C3ADataGuardError("pandas/pyarrow required for Feather") from exc
        temporary = path.with_name(path.stem + ".c3a.tmp.feather")
        pd.DataFrame([dict(row) for row in rows]).to_feather(temporary)
        temporary.replace(path)
        return
    if suffix == ".csv":
        if not rows:
            raise C3ADataGuardError("cannot write empty candle CSV")
        fields = list(rows[0].keys())
        if "date" not in fields:
            raise C3ADataGuardError("candle CSV missing date")
        temporary = path.with_name(path.name + ".c3a.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(dict(row) for row in rows)
        temporary.replace(path)
        return
    if suffix == ".json":
        temporary = path.with_name(path.name + ".c3a.tmp")
        temporary.write_text(json.dumps([dict(row) for row in rows], default=str), encoding="utf-8")
        temporary.replace(path)
        return
    raise C3ADataGuardError(f"unsupported candle format: {path.suffix}")


def load_config() -> dict[str, Any]:
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C3ADataGuardError(f"invalid C3A config: {exc}") from exc
    validate_config(payload)
    return payload


def sanitize_file(path: Path, pair: str) -> dict[str, Any]:
    rows = load_candles(path)
    if not rows:
        raise C3ADataGuardError(f"no candles for {pair}")
    dated = [(_timestamp(row.get("date")), dict(row)) for row in rows]
    dated.sort(key=lambda item: item[0])
    retained = [row for when, row in dated if when < BOUNDARY]
    removed = [when for when, _ in dated if when >= BOUNDARY]
    if not retained:
        raise C3ADataGuardError(f"sanitization removed every candle for {pair}")
    before_sha = _sha256(path)
    _write_rows(path, retained)
    reread = load_candles(path)
    dates = sorted(_timestamp(row.get("date")) for row in reread)
    if len(reread) != len(retained):
        raise C3ADataGuardError(f"row count changed while sealing {pair}")
    if not dates or dates[-1] >= BOUNDARY:
        raise C3ADataGuardError(f"post-boundary candle remains for {pair}")
    return {
        "pair": pair,
        "timeframe": "4h",
        "path": str(path.relative_to(IMPL)),
        "original_rows": len(rows),
        "retained_rows": len(reread),
        "removed_rows": len(removed),
        "original_latest": dated[-1][0].isoformat(),
        "retained_latest": dates[-1].isoformat(),
        "first_removed": removed[0].isoformat() if removed else None,
        "last_removed": removed[-1].isoformat() if removed else None,
        "sha256_before": before_sha,
        "sha256_after": _sha256(path),
        "post_boundary_rows": 0,
        "status": "PASS",
    }


def build_boundary_report(config: Mapping[str, Any], source_sha: str) -> dict[str, Any]:
    cells = [sanitize_file(discover_candle_file(DATA_DIR, pair, "4h"), pair) for pair in config["pairs"]]
    if len(cells) != 3:
        raise C3ADataGuardError("boundary report must contain three cells")
    return {
        "schema_version": 1,
        "stage": "C3A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "policy": POLICY,
        "cells": sorted(cells, key=lambda item: item["pair"]),
    }


def validate_boundary_report(payload: Mapping[str, Any], source_sha: str) -> None:
    if payload.get("stage") != "C3A" or payload.get("status") != "PASS":
        raise C3ADataGuardError("boundary report identity or status mismatch")
    if payload.get("source_head_sha") != source_sha:
        raise C3ADataGuardError("boundary source mismatch")
    if payload.get("economic_boundary_exclusive") != BOUNDARY.isoformat():
        raise C3ADataGuardError("boundary report timestamp drift")
    if payload.get("policy") != POLICY:
        raise C3ADataGuardError("boundary policy drift")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C3ADataGuardError("boundary safety drift")
    cells = payload.get("cells")
    if not isinstance(cells, list) or len(cells) != 3:
        raise C3ADataGuardError("boundary cell count mismatch")
    for cell in cells:
        if not isinstance(cell, Mapping) or cell.get("status") != "PASS":
            raise C3ADataGuardError("invalid boundary cell")
        if cell.get("post_boundary_rows") != 0 or _timestamp(cell.get("retained_latest")) >= BOUNDARY:
            raise C3ADataGuardError("boundary cell is not sealed")


def validate_rows(rows: Sequence[Mapping[str, Any]], pair: str, history_candles: int) -> dict[str, Any]:
    if pair not in PAIR_ORDER:
        raise C3ADataGuardError(f"unexpected pair: {pair}")
    if not rows:
        raise C3ADataGuardError(f"no candles for {pair}")
    dates = [_timestamp(row.get("date")) for row in rows]
    if dates != sorted(dates):
        raise C3ADataGuardError(f"unordered candles for {pair}")
    if len(set(dates)) != len(dates):
        raise C3ADataGuardError(f"duplicate candles for {pair}")
    required_earliest = FIRST_SCREEN - STEP * history_candles
    required_latest = BOUNDARY - STEP
    if dates[0] > required_earliest:
        raise C3ADataGuardError(
            f"{pair} earliest {dates[0].isoformat()} later than {required_earliest.isoformat()}"
        )
    if dates[-1] < required_latest or dates[-1] >= BOUNDARY:
        raise C3ADataGuardError(f"{pair} latest candle does not seal the C3A boundary")
    required = [date for date in dates if required_earliest <= date <= required_latest]
    expected = int((required_latest - required_earliest) / STEP) + 1
    if len(required) != expected or required[0] != required_earliest or required[-1] != required_latest:
        raise C3ADataGuardError(f"{pair} required four-hour coverage mismatch")
    for previous, current in zip(required, required[1:]):
        if current - previous != STEP:
            raise C3ADataGuardError(f"{pair} four-hour gap {previous.isoformat()} -> {current.isoformat()}")
    timestamp_digest = hashlib.sha256("\n".join(date.isoformat() for date in required).encode("utf-8")).hexdigest()
    return {
        "pair": pair,
        "timeframe": "4h",
        "rows": len(rows),
        "required_rows": expected,
        "earliest": dates[0].isoformat(),
        "latest": dates[-1].isoformat(),
        "required_earliest": required_earliest.isoformat(),
        "required_latest": required_latest.isoformat(),
        "required_timestamp_sha256": timestamp_digest,
        "duplicates": 0,
        "gaps": 0,
        "status": "PASS",
    }


def build_coverage_report(
    config: Mapping[str, Any], boundary: Mapping[str, Any], source_sha: str
) -> dict[str, Any]:
    validate_boundary_report(boundary, source_sha)
    cells: list[dict[str, Any]] = []
    for pair in config["pairs"]:
        path = discover_candle_file(DATA_DIR, pair, "4h")
        item = validate_rows(load_candles(path), pair, int(config["startup_history_candles"]))
        item["path"] = str(path.relative_to(IMPL))
        item["sha256"] = _sha256(path)
        cells.append(item)
    if len(cells) != 3:
        raise C3ADataGuardError("coverage report must contain three cells")
    sequence_hashes = {item["required_timestamp_sha256"] for item in cells}
    if len(sequence_hashes) != 1:
        raise C3ADataGuardError("BTC/ETH/SOL required timestamp sequences are not identical")
    return {
        "schema_version": 1,
        "stage": "C3A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "download_timerange": config["download_timerange"],
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "required_timestamp_sha256": next(iter(sequence_hashes)),
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "boundary_path": str(BOUNDARY_PATH.relative_to(IMPL)),
        "boundary_sha256": _sha256(BOUNDARY_PATH),
        "cells": sorted(cells, key=lambda item: item["pair"]),
    }


def _failure(mode: str, source_sha: str, error: Exception) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "stage": "C3A",
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
    source_sha = os.environ.get("C3A_SOURCE_SHA", os.environ.get("GITHUB_SHA", "local"))
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
        print(f"C3A data {args.mode} FAIL: {type(exc).__name__}: {exc}")
        raise
    _write_json(output, report)
    print(f"C3A data {args.mode} PASS: {len(report['cells'])} cells")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
