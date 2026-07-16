#!/usr/bin/env python3
"""Remove exchange API overshoot at the frozen C0C holdout boundary."""
from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.profitability_diagnostics import discover_candle_file, load_candles

IMPL = Path(__file__).resolve().parents[1]
CONFIG = IMPL / "config/c0c_cost_aware_ema.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
OUTPUT = IMPL / "freqtrade_data/c0c_runtime/c0c_data_boundary.json"
FROZEN_HOLDOUT_START = datetime(2025, 7, 1, tzinfo=UTC)


class C0CDataBoundaryError(RuntimeError):
    """Raised when downloaded data cannot be sealed below the holdout boundary."""


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
        raise C0CDataBoundaryError(f"invalid candle timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_rows(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    suffix = path.suffix.lower()
    if suffix == ".feather":
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:
            raise C0CDataBoundaryError("pandas/pyarrow required for Feather") from exc
        frame = pd.DataFrame([dict(row) for row in rows])
        temporary = path.with_name(path.stem + ".boundary.tmp.feather")
        frame.to_feather(temporary)
        temporary.replace(path)
        return
    if suffix == ".csv":
        if not rows:
            raise C0CDataBoundaryError(f"cannot write empty candle CSV: {path}")
        fields = list(rows[0].keys())
        if "date" not in fields:
            raise C0CDataBoundaryError(f"candle CSV missing date column: {path}")
        temporary = path.with_name(path.name + ".boundary.tmp")
        with temporary.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(dict(row) for row in rows)
        temporary.replace(path)
        return
    if suffix == ".json":
        temporary = path.with_name(path.name + ".boundary.tmp")
        temporary.write_text(
            json.dumps([dict(row) for row in rows], indent=2, default=str),
            encoding="utf-8",
        )
        temporary.replace(path)
        return
    raise C0CDataBoundaryError(f"unsupported candle format: {path.suffix}")


def sanitize_file(
    path: Path,
    *,
    pair: str,
    timeframe: str,
    holdout_start: datetime,
) -> dict[str, Any]:
    rows = load_candles(path)
    if not rows:
        raise C0CDataBoundaryError(f"no candles for {pair} {timeframe}")
    dated = [(_timestamp(row.get("date")), dict(row)) for row in rows]
    dated.sort(key=lambda item: item[0])
    retained = [row for when, row in dated if when < holdout_start]
    removed_dates = [when for when, _ in dated if when >= holdout_start]
    if not retained:
        raise C0CDataBoundaryError(f"sanitization removed every candle for {pair} {timeframe}")

    before_sha = _sha256(path)
    _write_rows(path, retained)
    after_rows = load_candles(path)
    after_dates = sorted(_timestamp(row.get("date")) for row in after_rows)
    if len(after_rows) != len(retained):
        raise C0CDataBoundaryError(f"row count changed while sealing {pair} {timeframe}")
    if not after_dates or after_dates[-1] >= holdout_start:
        raise C0CDataBoundaryError(f"holdout candle remains after sealing {pair} {timeframe}")

    return {
        "pair": pair,
        "timeframe": timeframe,
        "path": str(path.relative_to(IMPL)) if path.is_relative_to(IMPL) else str(path),
        "original_rows": len(rows),
        "retained_rows": len(after_rows),
        "removed_rows": len(removed_dates),
        "original_latest": dated[-1][0].isoformat(),
        "retained_latest": after_dates[-1].isoformat(),
        "first_removed": removed_dates[0].isoformat() if removed_dates else None,
        "last_removed": removed_dates[-1].isoformat() if removed_dates else None,
        "sha256_before": before_sha,
        "sha256_after": _sha256(path),
        "post_boundary_rows": 0,
        "status": "PASS",
    }


def build_report(
    *,
    config: Mapping[str, Any],
    data_dir: Path,
    source_head_sha: str,
) -> dict[str, Any]:
    if config.get("holdout_state") != "HOLDOUT_CLOSED":
        raise C0CDataBoundaryError("holdout must remain closed")
    holdout = config.get("holdout")
    if not isinstance(holdout, Mapping) or holdout.get("start") != "2025-07-01":
        raise C0CDataBoundaryError("holdout start drift")
    if config.get("data_timerange") != "20231101-20250701":
        raise C0CDataBoundaryError("development data timerange drift")
    pairs = config.get("pairs")
    if pairs != ["BTC/USDT", "ETH/USDT", "SOL/USDT"]:
        raise C0CDataBoundaryError("pair universe drift")

    cells: list[dict[str, Any]] = []
    for pair in pairs:
        for timeframe in ("5m", "1h"):
            path = discover_candle_file(data_dir, pair, timeframe)
            cells.append(
                sanitize_file(
                    path,
                    pair=pair,
                    timeframe=timeframe,
                    holdout_start=FROZEN_HOLDOUT_START,
                )
            )
    if len(cells) != 6:
        raise C0CDataBoundaryError("boundary report must contain six cells")
    return {
        "schema_version": 1,
        "status": "PASS",
        "source_head_sha": source_head_sha,
        "holdout_start": FROZEN_HOLDOUT_START.isoformat(),
        "holdout_state": "HOLDOUT_CLOSED",
        "policy": "REMOVE_API_OVERSHOOT_AT_OR_AFTER_HOLDOUT_BEFORE_ANY_RESEARCH_READ",
        "cells": sorted(cells, key=lambda item: (item["pair"], item["timeframe"])),
    }


def _write_report(report: Mapping[str, Any]) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(OUTPUT)


def main() -> int:
    source_head_sha = os.environ.get("C0C_SOURCE_SHA", os.environ.get("GITHUB_SHA", "local"))
    try:
        config = json.loads(CONFIG.read_text(encoding="utf-8"))
        report = build_report(
            config=config,
            data_dir=DATA_DIR,
            source_head_sha=source_head_sha,
        )
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "status": "FAIL",
            "source_head_sha": source_head_sha,
            "holdout_start": FROZEN_HOLDOUT_START.isoformat(),
            "holdout_state": "HOLDOUT_CLOSED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "cells": [],
        }
        _write_report(failure)
        print(f"C0C data boundary FAIL: {failure['error_type']}: {failure['error']}")
        raise

    _write_report(report)
    removed = sum(int(cell["removed_rows"]) for cell in report["cells"])
    print(
        "C0C data boundary PASS: "
        f"six cells sealed below {FROZEN_HOLDOUT_START.isoformat()}, removed {removed} API-overshoot rows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
