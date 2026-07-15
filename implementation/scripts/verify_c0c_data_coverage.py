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
OUTPUT = IMPL / "freqtrade_data/c0c_runtime/c0c_data_coverage.json"
FROZEN_DOWNLOAD_TIMERANGE = "20231001-20250701"


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
    return {
        "pair": pair,
        "timeframe": timeframe,
        "rows": len(rows),
        "earliest": earliest.isoformat(),
        "latest": latest.isoformat(),
        "required_earliest": required_earliest.isoformat(),
        "required_latest": required_latest.isoformat(),
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
    if holdout_start.isoformat() != "2025-07-01T00:00:00+00:00":
        raise C0CDataCoverageError("holdout start drift")

    cells: list[dict[str, Any]] = []
    for pair in config.get("pairs", []):
        for timeframe in ("5m", "1h"):
            path = discover_candle_file(data_dir, str(pair), timeframe)
            item = validate_rows(
                load_candles(path),
                pair=str(pair),
                timeframe=timeframe,
                first_fold_start=first_fold_start,
                holdout_start=holdout_start,
                startup_candles=startup_candles,
            )
            item["path"] = str(path.relative_to(IMPL))
            item["sha256"] = _sha256(path)
            cells.append(item)
    expected = len(config.get("pairs", [])) * 2
    if len(cells) != expected:
        raise C0CDataCoverageError(f"coverage cell count {len(cells)} != {expected}")
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
        "cells": sorted(cells, key=lambda item: (item["pair"], item["timeframe"])),
    }


def main() -> int:
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    report = build_report(
        config=config,
        data_dir=DATA_DIR,
        download_timerange=os.environ.get("C0C_DOWNLOAD_TIMERANGE", ""),
        source_head_sha=os.environ.get("C0C_SOURCE_SHA", os.environ.get("GITHUB_SHA", "local")),
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(OUTPUT)
    print(
        "C0C data coverage PASS: "
        f"{len(report['cells'])} pair/timeframe cells, HOLDOUT_CLOSED"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
