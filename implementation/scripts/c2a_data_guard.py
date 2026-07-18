#!/usr/bin/env python3
"""Seal and verify C2A daily market data below the preregistered boundary."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.profitability_diagnostics import discover_candle_file, load_candles


IMPL = Path(__file__).resolve().parents[1]
CONFIG_PATH = IMPL / "config/c2a_low_turnover_allocation.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RUNTIME = IMPL / "freqtrade_data/c2a_runtime"
BOUNDARY_PATH = RUNTIME / "c2a_data_boundary.json"
COVERAGE_PATH = RUNTIME / "c2a_data_coverage.json"
BOUNDARY = datetime(2024, 10, 1, tzinfo=UTC)
FIRST_SCREEN = datetime(2024, 1, 1, tzinfo=UTC)
POLICY = "REMOVE_API_OVERSHOOT_AT_OR_AFTER_C2A_BOUNDARY_BEFORE_ANY_RESEARCH_READ"


class C2ADataGuardError(RuntimeError):
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
        raise C2ADataGuardError(f"invalid candle timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C2ADataGuardError(f"unreadable file {path}: {exc}") from exc


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
        except ImportError as exc:
            raise C2ADataGuardError("pandas/pyarrow required for Feather") from exc
        temporary = path.with_name(path.stem + ".c2a.tmp.feather")
        pd.DataFrame([dict(row) for row in rows]).to_feather(temporary)
        temporary.replace(path)
        return
    if suffix == ".csv":
        if not rows:
            raise C2ADataGuardError("cannot write empty candle CSV")
        fields = list(rows[0].keys())
        if "date" not in fields:
            raise C2ADataGuardError("candle CSV missing date")
        temporary = path.with_name(path.name + ".c2a.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(dict(row) for row in rows)
        temporary.replace(path)
        return
    if suffix == ".json":
        temporary = path.with_name(path.name + ".c2a.tmp")
        temporary.write_text(json.dumps([dict(row) for row in rows], default=str), encoding="utf-8")
        temporary.replace(path)
        return
    raise C2ADataGuardError(f"unsupported candle format: {path.suffix}")


def load_config() -> dict[str, Any]:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C2ADataGuardError(f"invalid C2A config: {exc}") from exc
    if config.get("stage") != "C2A":
        raise C2ADataGuardError("stage drift")
    if config.get("live") != "FORBIDDEN" or config.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C2ADataGuardError("safety state drift")
    if config.get("confirmation_opened") is not False:
        raise C2ADataGuardError("confirmation state drift")
    if config.get("pairs") != ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        raise C2ADataGuardError("pair universe drift")
    if config.get("timeframe") != "1d":
        raise C2ADataGuardError("timeframe drift")
    if config.get("download_timerange") != "20230501-20241001":
        raise C2ADataGuardError("download timerange drift")
    if config.get("economic_boundary_exclusive") != "2024-10-01T00:00:00Z":
        raise C2ADataGuardError("boundary drift")
    if int(config.get("startup_history_candles", 0)) != 220:
        raise C2ADataGuardError("startup coverage drift")
    return config


def sanitize_file(path: Path, pair: str) -> dict[str, Any]:
    rows = load_candles(path)
    if not rows:
        raise C2ADataGuardError(f"no candles for {pair}")
    dated = [(_timestamp(row.get("date")), dict(row)) for row in rows]
    dated.sort(key=lambda item: item[0])
    retained = [row for when, row in dated if when < BOUNDARY]
    removed = [when for when, _ in dated if when >= BOUNDARY]
    if not retained:
        raise C2ADataGuardError(f"sanitization removed every candle for {pair}")
    before_sha = _sha256(path)
    _write_rows(path, retained)
    reread = load_candles(path)
    dates = sorted(_timestamp(row.get("date")) for row in reread)
    if len(reread) != len(retained):
        raise C2ADataGuardError(f"row count changed while sealing {pair}")
    if not dates or dates[-1] >= BOUNDARY:
        raise C2ADataGuardError(f"post-boundary candle remains for {pair}")
    return {
        "pair": pair,
        "timeframe": "1d",
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
        "status": "PASS"
    }


def build_boundary_report(config: Mapping[str, Any], source_sha: str) -> dict[str, Any]:
    cells = [
        sanitize_file(discover_candle_file(DATA_DIR, pair, "1d"), pair)
        for pair in config["pairs"]
    ]
    if len(cells) != 3:
        raise C2ADataGuardError("boundary report must contain three cells")
    return {
        "schema_version": 1,
        "status": "PASS",
        "source_head_sha": source_sha,
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "policy": POLICY,
        "cells": sorted(cells, key=lambda item: item["pair"])
    }


def validate_boundary_report(payload: Mapping[str, Any], source_sha: str) -> None:
    if payload.get("status") != "PASS" or payload.get("source_head_sha") != source_sha:
        raise C2ADataGuardError("boundary report status or source mismatch")
    if payload.get("economic_boundary_exclusive") != BOUNDARY.isoformat():
        raise C2ADataGuardError("boundary report timestamp drift")
    if payload.get("policy") != POLICY:
        raise C2ADataGuardError("boundary policy drift")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C2ADataGuardError("boundary safety drift")
    cells = payload.get("cells")
    if not isinstance(cells, list) or len(cells) != 3:
        raise C2ADataGuardError("boundary cell count mismatch")
    for cell in cells:
        if not isinstance(cell, Mapping) or cell.get("status") != "PASS":
            raise C2ADataGuardError("invalid boundary cell")
        if cell.get("post_boundary_rows") != 0 or _timestamp(cell.get("retained_latest")) >= BOUNDARY:
            raise C2ADataGuardError("boundary cell is not sealed")


def validate_rows(rows: Sequence[Mapping[str, Any]], pair: str, history_candles: int) -> dict[str, Any]:
    if not rows:
        raise C2ADataGuardError(f"no candles for {pair}")
    dates = sorted(_timestamp(row.get("date")) for row in rows)
    if len(set(dates)) != len(dates):
        raise C2ADataGuardError(f"duplicate candles for {pair}")
    step = timedelta(days=1)
    required_earliest = FIRST_SCREEN - step * history_candles
    required_latest = BOUNDARY - step
    if dates[0] > required_earliest:
        raise C2ADataGuardError(
            f"{pair} earliest {dates[0].isoformat()} later than {required_earliest.isoformat()}"
        )
    if dates[-1] < required_latest or dates[-1] >= BOUNDARY:
        raise C2ADataGuardError(f"{pair} latest candle does not seal the C2A boundary")
    required = [date for date in dates if required_earliest <= date <= required_latest]
    expected = int((required_latest - required_earliest) / step) + 1
    if len(required) != expected or required[0] != required_earliest or required[-1] != required_latest:
        raise C2ADataGuardError(f"{pair} required daily coverage mismatch")
    for previous, current in zip(required, required[1:]):
        if current - previous != step:
            raise C2ADataGuardError(f"{pair} daily gap {previous.isoformat()} -> {current.isoformat()}")
    return {
        "pair": pair,
        "timeframe": "1d",
        "rows": len(rows),
        "required_rows": expected,
        "earliest": dates[0].isoformat(),
        "latest": dates[-1].isoformat(),
        "required_earliest": required_earliest.isoformat(),
        "required_latest": required_latest.isoformat(),
        "duplicates": 0,
        "gaps": 0,
        "status": "PASS"
    }


def build_coverage_report(
    config: Mapping[str, Any], boundary: Mapping[str, Any], source_sha: str
) -> dict[str, Any]:
    validate_boundary_report(boundary, source_sha)
    cells: list[dict[str, Any]] = []
    for pair in config["pairs"]:
        path = discover_candle_file(DATA_DIR, pair, "1d")
        item = validate_rows(load_candles(path), pair, int(config["startup_history_candles"]))
        item["path"] = str(path.relative_to(IMPL))
        item["sha256"] = _sha256(path)
        cells.append(item)
    if len(cells) != 3:
        raise C2ADataGuardError("coverage report must contain three cells")
    return {
        "schema_version": 1,
        "status": "PASS",
        "source_head_sha": source_sha,
        "download_timerange": config["download_timerange"],
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "boundary_path": str(BOUNDARY_PATH.relative_to(IMPL)),
        "boundary_sha256": _sha256(BOUNDARY_PATH),
        "cells": sorted(cells, key=lambda item: item["pair"])
    }


def _failure(mode: str, source_sha: str, error: Exception) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "status": "FAIL",
        "mode": mode,
        "source_head_sha": source_sha,
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "error_type": type(error).__name__,
        "error": str(error),
        "cells": []
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("sanitize", "verify"))
    args = parser.parse_args()
    source_sha = os.environ.get("C2A_SOURCE_SHA", os.environ.get("GITHUB_SHA", "local"))
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
        print(f"C2A data {args.mode} FAIL: {type(exc).__name__}: {exc}")
        raise
    _write_json(output, report)
    print(
        f"C2A data {args.mode} PASS: {len(report['cells'])} cells below {BOUNDARY.isoformat()}, "
        "HOLDOUT_CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
