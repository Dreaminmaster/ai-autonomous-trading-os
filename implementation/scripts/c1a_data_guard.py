#!/usr/bin/env python3
"""Seal and verify C1A market data below the preregistered screen boundary."""
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
CONFIG_PATH = IMPL / "config/c1a_strategy_family_screen.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RUNTIME = IMPL / "freqtrade_data/c1a_runtime"
BOUNDARY_PATH = RUNTIME / "c1a_data_boundary.json"
COVERAGE_PATH = RUNTIME / "c1a_data_coverage.json"
BOUNDARY = datetime(2024, 10, 1, tzinfo=UTC)
POLICY = "REMOVE_API_OVERSHOOT_AT_OR_AFTER_C1A_BOUNDARY_BEFORE_ANY_RESEARCH_READ"


class C1ADataGuardError(RuntimeError):
    """Raised when C1A data cannot be sealed or reproduced exactly."""


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
        raise C1ADataGuardError(f"invalid candle timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _step(timeframe: str) -> timedelta:
    if timeframe == "1h":
        return timedelta(hours=1)
    if timeframe == "1d":
        return timedelta(days=1)
    raise C1ADataGuardError(f"unsupported C1A timeframe: {timeframe}")


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C1ADataGuardError(f"unreadable evidence file {path}: {exc}") from exc


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
            raise C1ADataGuardError("pandas/pyarrow required for Feather") from exc
        temporary = path.with_name(path.stem + ".c1a.tmp.feather")
        pd.DataFrame([dict(row) for row in rows]).to_feather(temporary)
        temporary.replace(path)
        return
    if suffix == ".csv":
        if not rows:
            raise C1ADataGuardError(f"cannot write empty candle CSV: {path}")
        fields = list(rows[0].keys())
        if "date" not in fields:
            raise C1ADataGuardError(f"candle CSV missing date column: {path}")
        temporary = path.with_name(path.name + ".c1a.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(dict(row) for row in rows)
        temporary.replace(path)
        return
    if suffix == ".json":
        temporary = path.with_name(path.name + ".c1a.tmp")
        temporary.write_text(
            json.dumps([dict(row) for row in rows], indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(path)
        return
    raise C1ADataGuardError(f"unsupported candle format: {path.suffix}")


def _load_config() -> dict[str, Any]:
    try:
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C1ADataGuardError(f"invalid C1A config: {exc}") from exc
    if config.get("stage") != "C1A":
        raise C1ADataGuardError("stage drift")
    if config.get("live") != "FORBIDDEN" or config.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C1ADataGuardError("safety state drift")
    if config.get("download_timerange") != "20230701-20241001":
        raise C1ADataGuardError("download timerange drift")
    if config.get("economic_boundary_exclusive") != "2024-10-01T00:00:00Z":
        raise C1ADataGuardError("economic boundary drift")
    if config.get("pairs") != ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        raise C1ADataGuardError("pair universe drift")
    if config.get("coverage_history_candles") != {"1h": 1499, "1d": 120}:
        raise C1ADataGuardError("coverage history drift")
    return config


def sanitize_file(path: Path, *, pair: str, timeframe: str) -> dict[str, Any]:
    rows = load_candles(path)
    if not rows:
        raise C1ADataGuardError(f"no candles for {pair} {timeframe}")
    dated = sorted((_timestamp(row.get("date")), dict(row)) for row in rows)
    retained = [row for when, row in dated if when < BOUNDARY]
    removed = [when for when, _ in dated if when >= BOUNDARY]
    if not retained:
        raise C1ADataGuardError(f"sanitization removed every candle for {pair} {timeframe}")
    before_sha = _sha256(path)
    _write_rows(path, retained)
    reread = load_candles(path)
    after_dates = sorted(_timestamp(row.get("date")) for row in reread)
    if len(reread) != len(retained):
        raise C1ADataGuardError(f"row count changed while sealing {pair} {timeframe}")
    if not after_dates or after_dates[-1] >= BOUNDARY:
        raise C1ADataGuardError(f"post-boundary candle remains for {pair} {timeframe}")
    return {
        "pair": pair,
        "timeframe": timeframe,
        "path": str(path.relative_to(IMPL)),
        "original_rows": len(rows),
        "retained_rows": len(reread),
        "removed_rows": len(removed),
        "original_latest": dated[-1][0].isoformat(),
        "retained_latest": after_dates[-1].isoformat(),
        "first_removed": removed[0].isoformat() if removed else None,
        "last_removed": removed[-1].isoformat() if removed else None,
        "sha256_before": before_sha,
        "sha256_after": _sha256(path),
        "post_boundary_rows": 0,
        "status": "PASS",
    }


def build_boundary_report(config: Mapping[str, Any], source_sha: str) -> dict[str, Any]:
    cells = [
        sanitize_file(
            discover_candle_file(DATA_DIR, pair, timeframe),
            pair=pair,
            timeframe=timeframe,
        )
        for pair in config["pairs"]
        for timeframe in ("1h", "1d")
    ]
    if len(cells) != 6:
        raise C1ADataGuardError("boundary report must contain six cells")
    return {
        "schema_version": 1,
        "status": "PASS",
        "source_head_sha": source_sha,
        "economic_boundary_exclusive": BOUNDARY.isoformat(),
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "policy": POLICY,
        "cells": sorted(cells, key=lambda item: (item["pair"], item["timeframe"])),
    }


def validate_boundary_report(payload: Mapping[str, Any], source_sha: str) -> None:
    if payload.get("status") != "PASS":
        raise C1ADataGuardError("boundary sanitization did not pass")
    if payload.get("source_head_sha") != source_sha:
        raise C1ADataGuardError("boundary source SHA mismatch")
    if payload.get("economic_boundary_exclusive") != BOUNDARY.isoformat():
        raise C1ADataGuardError("boundary timestamp drift")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C1ADataGuardError("boundary safety state drift")
    if payload.get("policy") != POLICY:
        raise C1ADataGuardError("boundary policy drift")
    cells = payload.get("cells")
    if not isinstance(cells, list) or len(cells) != 6:
        raise C1ADataGuardError("boundary report cell count mismatch")
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise C1ADataGuardError("invalid boundary cell")
        if cell.get("status") != "PASS" or cell.get("post_boundary_rows") != 0:
            raise C1ADataGuardError("boundary cell is not sealed")
        if _timestamp(cell.get("retained_latest")) >= BOUNDARY:
            raise C1ADataGuardError("boundary cell retains future screen data")


def validate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    pair: str,
    timeframe: str,
    history_candles: int,
) -> dict[str, Any]:
    if not rows:
        raise C1ADataGuardError(f"no candles for {pair} {timeframe}")
    dates = sorted(_timestamp(row.get("date")) for row in rows)
    if len(set(dates)) != len(dates):
        raise C1ADataGuardError(f"duplicate candles for {pair} {timeframe}")
    step = _step(timeframe)
    first_screen = datetime(2024, 1, 1, tzinfo=UTC)
    required_earliest = first_screen - step * history_candles
    required_latest = BOUNDARY - step
    if dates[0] > required_earliest:
        raise C1ADataGuardError(
            f"{pair} {timeframe} earliest {dates[0].isoformat()} later than {required_earliest.isoformat()}"
        )
    if dates[-1] < required_latest:
        raise C1ADataGuardError(
            f"{pair} {timeframe} latest {dates[-1].isoformat()} earlier than {required_latest.isoformat()}"
        )
    if dates[-1] >= BOUNDARY:
        raise C1ADataGuardError(f"{pair} {timeframe} contains post-boundary candle")
    required = [date for date in dates if required_earliest <= date <= required_latest]
    expected = int((required_latest - required_earliest) / step) + 1
    if len(required) != expected:
        raise C1ADataGuardError(
            f"{pair} {timeframe} required rows {len(required)} != {expected}"
        )
    if required[0] != required_earliest or required[-1] != required_latest:
        raise C1ADataGuardError(f"{pair} {timeframe} required boundary candle missing")
    for previous, current in zip(required, required[1:]):
        if current - previous != step:
            raise C1ADataGuardError(
                f"{pair} {timeframe} candle gap {previous.isoformat()} -> {current.isoformat()}"
            )
    return {
        "pair": pair,
        "timeframe": timeframe,
        "rows": len(rows),
        "required_rows": expected,
        "earliest": dates[0].isoformat(),
        "latest": dates[-1].isoformat(),
        "required_earliest": required_earliest.isoformat(),
        "required_latest": required_latest.isoformat(),
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
        for timeframe in ("1h", "1d"):
            path = discover_candle_file(DATA_DIR, pair, timeframe)
            item = validate_rows(
                load_candles(path),
                pair=pair,
                timeframe=timeframe,
                history_candles=int(config["coverage_history_candles"][timeframe]),
            )
            item["path"] = str(path.relative_to(IMPL))
            item["sha256"] = _sha256(path)
            cells.append(item)
    if len(cells) != 6:
        raise C1ADataGuardError("coverage report must contain six cells")
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
        "cells": sorted(cells, key=lambda item: (item["pair"], item["timeframe"])),
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
        "cells": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("sanitize", "verify"))
    args = parser.parse_args()
    source_sha = os.environ.get("C1A_SOURCE_SHA", os.environ.get("GITHUB_SHA", "local"))
    output = BOUNDARY_PATH if args.mode == "sanitize" else COVERAGE_PATH
    try:
        config = _load_config()
        if args.mode == "sanitize":
            report = build_boundary_report(config, source_sha)
        else:
            boundary = json.loads(BOUNDARY_PATH.read_text(encoding="utf-8"))
            report = build_coverage_report(config, boundary, source_sha)
    except Exception as exc:
        report = _failure(args.mode, source_sha, exc)
        _write_json(output, report)
        print(f"C1A data {args.mode} FAIL: {type(exc).__name__}: {exc}")
        raise
    _write_json(output, report)
    print(
        f"C1A data {args.mode} PASS: {len(report['cells'])} cells below {BOUNDARY.isoformat()}, "
        "HOLDOUT_CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
