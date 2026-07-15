#!/usr/bin/env python3
"""Fail-closed candle coverage proof for the C0C OKX development run."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.profitability_diagnostics import discover_candle_file, load_candles

IMPL = Path(__file__).resolve().parents[1]
CONFIG = IMPL / "config/c0c_cost_aware_ema.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
BOUNDARY = IMPL / "freqtrade_data/c0c_runtime/c0c_data_boundary.json"
OUTPUT = IMPL / "freqtrade_data/c0c_runtime/c0c_data_coverage.json"
FROZEN_DOWNLOAD_TIMERANGE = "20231001-20250701"
FROZEN_HOLDOUT_START = "2025-07-01T00:00:00+00:00"


class C0CDataCoverageError(RuntimeError):
    """Raised when downloaded candles cannot reproduce the frozen folds."""


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
        raise C0CDataCoverageError(f"invalid candle timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _step(timeframe: str) -> timedelta:
    if timeframe == "5m":
        return timedelta(minutes=5)
    if timeframe == "1h":
        return timedelta(hours=1)
    raise C0CDataCoverageError(f"unsupported C0C timeframe: {timeframe}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_boundary_report(payload: Mapping[str, Any], source_head_sha: str) -> None:
    if payload.get("status") != "PASS":
        raise C0CDataCoverageError("data boundary sanitization did not pass")
    if payload.get("source_head_sha") != source_head_sha:
        raise C0CDataCoverageError("boundary source SHA does not match C0C_SOURCE_SHA")
    if payload.get("holdout_start") != FROZEN_HOLDOUT_START:
        raise C0CDataCoverageError("boundary holdout start drift")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C0CDataCoverageError("boundary report opened holdout")
    if payload.get("policy") != "REMOVE_API_OVERSHOOT_AT_OR_AFTER_HOLDOUT_BEFORE_ANY_RESEARCH_READ":
        raise C0CDataCoverageError("boundary sanitization policy drift")
    cells = payload.get("cells")
    if not isinstance(cells, list) or len(cells) != 6:
        raise C0CDataCoverageError("boundary report must contain six cells")
    holdout_start = _timestamp(FROZEN_HOLDOUT_START)
    for cell in cells:
        if not isinstance(cell, Mapping):
            raise C0CDataCoverageError("invalid boundary cell")
        if cell.get("status") != "PASS" or cell.get("post_boundary_rows") != 0:
            raise C0CDataCoverageError("boundary cell is not sealed")
        retained_latest = _timestamp(cell.get("retained_latest"))
        if retained_latest >= holdout_start:
            raise C0CDataCoverageError("boundary cell retains a holdout candle")


def validate_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    pair: str,
    timeframe: str,
    first_fold_start: datetime,
    holdout_start: datetime,
    startup_candles: int,
) -> dict[str, Any]:
    if not rows:
        raise C0CDataCoverageError(f"no candles for {pair} {timeframe}")
    dates = sorted(_timestamp(row.get("date")) for row in rows)
    if len(set(dates)) != len(dates):
        raise C0CDataCoverageError(f"duplicate candles for {pair} {timeframe}")

    candle_step = _step(timeframe)
    required_earliest = first_fold_start - candle_step * startup_candles
    required_latest = holdout_start - candle_step
    earliest, latest = dates[0], dates[-1]
    if earliest > required_earliest:
        raise C0CDataCoverageError(
            f"{pair} {timeframe} earliest {earliest.isoformat()} is later than "
            f"required startup history {required_earliest.isoformat()}"
        )
    if latest < required_latest:
        raise C0CDataCoverageError(
            f"{pair} {timeframe} latest {latest.isoformat()} is earlier than "
            f"required development end {required_latest.isoformat()}"
        )
    if latest >= holdout_start:
        raise C0CDataCoverageError(
            f"{pair} {timeframe} contains holdout candle {latest.isoformat()}"
        )

    required_dates = [
        value for value in dates if required_earliest <= value <= required_latest
    ]
    expected_rows = int((required_latest - required_earliest) / candle_step) + 1
    if len(required_dates) != expected_rows:
        raise C0CDataCoverageError(
            f"{pair} {timeframe} required rows {len(required_dates)} != {expected_rows}"
        )
    if required_dates[0] != required_earliest or required_dates[-1] != required_latest:
        raise C0CDataCoverageError(f"{pair} {timeframe} required boundary candle missing")
    for previous, current in zip(required_dates, required_dates[1:]):
        if current - previous != candle_step:
            raise C0CDataCoverageError(
                f"{pair} {timeframe} candle gap {previous.isoformat()} -> {current.isoformat()}"
            )

    return {
        "pair": pair,
        "timeframe": timeframe,
        "rows": len(rows),
        "required_rows": expected_rows,
        "earliest": earliest.isoformat(),
        "latest": latest.isoformat(),
        "required_earliest": required_earliest.isoformat(),
        "required_latest": required_latest.isoformat(),
        "duplicates": 0,
        "gaps": 0,
        "status": "PASS",
    }


def build_report(
    *,
    config: Mapping[str, Any],
    data_dir: Path,
    download_timerange: str,
    source_head_sha: str,
) -> dict[str, Any]:
    if download_timerange != FROZEN_DOWNLOAD_TIMERANGE:
        raise C0CDataCoverageError(
            f"download timerange {download_timerange!r} != {FROZEN_DOWNLOAD_TIMERANGE!r}"
        )
    if config.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C0CDataCoverageError("holdout must remain closed")
    if config.get("data_timerange") != "20231101-20250701":
        raise C0CDataCoverageError("evaluation data timerange drift")
    startup = config.get("startup_analysis", {})
    startup_candles = int(startup.get("selected_startup_candles", 0))
    if startup_candles != 1499:
        raise C0CDataCoverageError("selected startup candles must remain 1499")
    folds = config.get("folds")
    holdout = config.get("holdout")
    if not isinstance(folds, list) or not folds or not isinstance(holdout, Mapping):
        raise C0CDataCoverageError("fold/holdout contract missing")
    first_fold_start = _timestamp(folds[0].get("train_start"))
    holdout_start = _timestamp(holdout.get("start"))
    if first_fold_start.isoformat() != "2024-01-01T00:00:00+00:00":
        raise C0CDataCoverageError("first fold start drift")
    if holdout_start.isoformat() != FROZEN_HOLDOUT_START:
        raise C0CDataCoverageError("holdout start drift")

    pairs = config.get("pairs")
    if pairs != ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        raise C0CDataCoverageError("pair universe drift")
    cells: list[dict[str, Any]] = []
    for pair in pairs:
        for timeframe in ("5m", "1h"):
            path = discover_candle_file(data_dir, pair, timeframe)
            item = validate_rows(
                load_candles(path),
                pair=pair,
                timeframe=timeframe,
                first_fold_start=first_fold_start,
                holdout_start=holdout_start,
                startup_candles=startup_candles,
            )
            item["path"] = str(path.relative_to(IMPL))
            item["sha256"] = _sha256(path)
            cells.append(item)
    if len(cells) != 6:
        raise C0CDataCoverageError(f"coverage cell count {len(cells)} != 6")
    return {
        "schema_version": 1,
        "status": "PASS",
        "source_head_sha": source_head_sha,
        "download_timerange": download_timerange,
        "evaluation_data_timerange": config.get("data_timerange"),
        "first_fold_start": first_fold_start.isoformat(),
        "holdout_start": holdout_start.isoformat(),
        "startup_candle_count": startup_candles,
        "holdout_state": "HOLDOUT_CLOSED",
        "data_boundary_path": str(BOUNDARY.relative_to(IMPL)),
        "data_boundary_sha256": _sha256(BOUNDARY),
        "cells": sorted(cells, key=lambda item: (item["pair"], item["timeframe"])),
    }


def build_failure_report(
    *, error: Exception, download_timerange: str, source_head_sha: str
) -> dict[str, Any]:
    """Persist a reviewable fail-closed diagnostic without changing the gate."""
    return {
        "schema_version": 1,
        "status": "FAIL",
        "source_head_sha": source_head_sha,
        "download_timerange": download_timerange,
        "evaluation_data_timerange": "20231101-20250701",
        "holdout_start": FROZEN_HOLDOUT_START,
        "startup_candle_count": 1499,
        "holdout_state": "HOLDOUT_CLOSED",
        "data_boundary_path": str(BOUNDARY.relative_to(IMPL)),
        "error_type": type(error).__name__,
        "error": str(error),
        "cells": [],
    }


def _write_report(report: Mapping[str, Any]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(OUTPUT)


def main() -> int:
    download_timerange = os.environ.get("C0C_DOWNLOAD_TIMERANGE", "")
    source_head_sha = os.environ.get("C0C_SOURCE_SHA", os.environ.get("GITHUB_SHA", "local"))
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        boundary: dict[str, Any] = json.loads(BOUNDARY.read_text(encoding="utf-8"))
        validate_boundary_report(boundary, source_head_sha)
        report = build_report(
            config=config,
            data_dir=DATA_DIR,
            download_timerange=download_timerange,
            source_head_sha=source_head_sha,
        )
    except Exception as exc:
        failure = build_failure_report(
            error=exc,
            download_timerange=download_timerange,
            source_head_sha=source_head_sha,
        )
        _write_report(failure)
        print(f"C0C data coverage FAIL: {failure['error_type']}: {failure['error']}")
        raise

    _write_report(report)
    print(
        "C0C data coverage PASS: "
        f"{len(report['cells'])} pair/timeframe cells, HOLDOUT_CLOSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
