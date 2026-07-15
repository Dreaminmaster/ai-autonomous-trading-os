#!/usr/bin/env python3
"""Finalize the C0C manifest with startup, boundary, and coverage evidence."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

IMPL = Path(__file__).resolve().parents[1]
MANIFEST = IMPL / "freqtrade_data/backtest_results/c0c_development/c0c_development_manifest.json"
CONFIG = IMPL / "config/c0c_cost_aware_ema.json"
STRATEGY = IMPL / "freqtrade_data/strategies/c0c_cost_aware_ema.py"
BOUNDARY = IMPL / "freqtrade_data/c0c_runtime/c0c_data_boundary.json"
COVERAGE = IMPL / "freqtrade_data/c0c_runtime/c0c_data_coverage.json"
EXTRA_SOURCES = [
    IMPL / "src/atos/__init__.py",
    IMPL / "src/atos/c0c_okx_startup.py",
    IMPL / "scripts/finalize_c0c_manifest.py",
    IMPL / "scripts/sanitize_c0c_data_boundary.py",
    IMPL / "scripts/verify_c0c_data_coverage.py",
    IMPL / "tests/test_c0c_data_boundary.py",
    IMPL / "tests/test_c0c_data_coverage.py",
    IMPL / "tests/test_c0c_okx_startup_contract.py",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(IMPL))


def timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    else:
        raise SystemExit(f"invalid timestamp: {value!r}")
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def main() -> int:
    payload: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    boundary: dict[str, Any] = json.loads(BOUNDARY.read_text(encoding="utf-8"))
    coverage: dict[str, Any] = json.loads(COVERAGE.read_text(encoding="utf-8"))
    source_sha = os.environ.get("C0C_SOURCE_SHA")
    if not source_sha or payload.get("source_head_sha") != source_sha:
        raise SystemExit("manifest source SHA does not match C0C_SOURCE_SHA")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED":
        raise SystemExit("holdout must remain closed")
    if config.get("data_timerange") != "20231101-20250701":
        raise SystemExit("development data timerange drift")
    startup = config.get("startup_analysis", {})
    if startup.get("startup_candidates") != [499, 999, 1499]:
        raise SystemExit("OKX startup candidate contract drift")
    if startup.get("selected_startup_candles") != 1499:
        raise SystemExit("OKX selected startup candle drift")
    if "startup_candle_count = 1499" not in STRATEGY.read_text(encoding="utf-8"):
        raise SystemExit("strategy startup candle count drift")

    if boundary.get("status") != "PASS":
        raise SystemExit("C0C data boundary sanitization did not pass")
    if boundary.get("source_head_sha") != source_sha:
        raise SystemExit("boundary source SHA does not match C0C_SOURCE_SHA")
    if boundary.get("holdout_start") != "2025-07-01T00:00:00+00:00":
        raise SystemExit("boundary holdout start drift")
    if boundary.get("holdout_state") != "HOLDOUT_CLOSED":
        raise SystemExit("boundary report opened holdout")
    if boundary.get("policy") != "REMOVE_API_OVERSHOOT_AT_OR_AFTER_HOLDOUT_BEFORE_ANY_RESEARCH_READ":
        raise SystemExit("boundary policy drift")
    boundary_cells = boundary.get("cells")
    if not isinstance(boundary_cells, list) or len(boundary_cells) != 6:
        raise SystemExit("boundary report must contain six cells")
    holdout_start = timestamp(boundary["holdout_start"])
    for cell in boundary_cells:
        if cell.get("status") != "PASS" or cell.get("post_boundary_rows") != 0:
            raise SystemExit("boundary cell is not sealed")
        if timestamp(cell.get("retained_latest")) >= holdout_start:
            raise SystemExit("boundary cell retains holdout data")

    if coverage.get("status") != "PASS":
        raise SystemExit("C0C data coverage did not pass")
    if coverage.get("source_head_sha") != source_sha:
        raise SystemExit("coverage source SHA does not match C0C_SOURCE_SHA")
    if coverage.get("download_timerange") != "20231001-20250701":
        raise SystemExit("coverage download timerange drift")
    if coverage.get("evaluation_data_timerange") != "20231101-20250701":
        raise SystemExit("coverage evaluation timerange drift")
    if coverage.get("holdout_state") != "HOLDOUT_CLOSED":
        raise SystemExit("coverage opened holdout")
    if coverage.get("data_boundary_sha256") != sha256_file(BOUNDARY):
        raise SystemExit("coverage boundary hash mismatch")
    cells = coverage.get("cells")
    if not isinstance(cells, list) or len(cells) != 6:
        raise SystemExit("coverage must contain six pair/timeframe cells")
    for cell in cells:
        if cell.get("status") != "PASS" or cell.get("gaps") != 0 or cell.get("duplicates") != 0:
            raise SystemExit("coverage cell is incomplete")

    source_files = {
        str(item["path"]): dict(item)
        for item in payload.get("source_files", [])
        if isinstance(item, dict) and "path" in item
    }
    for path in EXTRA_SOURCES:
        source_files[relative(path)] = {"path": relative(path), "sha256": sha256_file(path)}
    payload["source_files"] = [source_files[key] for key in sorted(source_files)]
    payload["data_boundary"] = {
        "path": relative(BOUNDARY),
        "sha256": sha256_file(BOUNDARY),
        "status": "PASS",
        "source_head_sha": source_sha,
        "holdout_start": boundary["holdout_start"],
        "holdout_state": "HOLDOUT_CLOSED",
        "policy": boundary["policy"],
        "cells": boundary_cells,
    }
    payload["data_coverage"] = {
        "path": relative(COVERAGE),
        "sha256": sha256_file(COVERAGE),
        "status": "PASS",
        "source_head_sha": source_sha,
        "download_timerange": coverage["download_timerange"],
        "evaluation_data_timerange": coverage["evaluation_data_timerange"],
        "holdout_state": "HOLDOUT_CLOSED",
        "data_boundary_sha256": coverage["data_boundary_sha256"],
        "cells": cells,
    }
    payload["startup_contract_correction"] = {
        "status": "PROSPECTIVELY_FROZEN",
        "reason": "OKX_5M_API_MAX_STARTUP_CANDLES_1499",
        "selected_startup_candles": 1499,
        "startup_candidates": [499, 999, 1499],
        "prior_failed_run_id": "29400676419",
        "prior_run_reached_hyperopt": False,
        "prior_run_opened_development_test": False,
        "holdout_state": "HOLDOUT_CLOSED",
    }
    payload["api_overshoot_correction"] = {
        "status": "PROSPECTIVELY_FROZEN",
        "reason": "OKX_DOWNLOAD_BATCH_OVERSHOT_FROZEN_END_BOUNDARY",
        "diagnostic_run_id": "29425070603",
        "diagnostic_source_sha": "e15b7b7f469aaade1ade165af78dce736ccd2083",
        "diagnostic_latest_timestamp": "2025-07-01T13:50:00+00:00",
        "economic_stages_reached": False,
        "sanitization_policy": boundary["policy"],
        "holdout_state": "HOLDOUT_CLOSED",
    }
    temporary = MANIFEST.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(MANIFEST)
    print("C0C manifest finalized with startup, sealed-boundary, and data-coverage evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
