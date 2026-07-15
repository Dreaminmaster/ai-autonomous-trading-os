#!/usr/bin/env python3
"""Finalize the C0C manifest with the prospective OKX startup correction."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

IMPL = Path(__file__).resolve().parents[1]
MANIFEST = IMPL / "freqtrade_data/backtest_results/c0c_development/c0c_development_manifest.json"
CONFIG = IMPL / "config/c0c_cost_aware_ema.json"
STRATEGY = IMPL / "freqtrade_data/strategies/c0c_cost_aware_ema.py"
EXTRA_SOURCES = [
    IMPL / "src/atos/__init__.py",
    IMPL / "src/atos/c0c_okx_startup.py",
    IMPL / "scripts/finalize_c0c_manifest.py",
    IMPL / "tests/test_c0c_okx_startup_contract.py",
]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative(path: Path) -> str:
    return str(path.relative_to(IMPL))


def main() -> int:
    payload: dict[str, Any] = json.loads(MANIFEST.read_text(encoding="utf-8"))
    config = json.loads(CONFIG.read_text(encoding="utf-8"))
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

    source_files = {
        str(item["path"]): dict(item)
        for item in payload.get("source_files", [])
        if isinstance(item, dict) and "path" in item
    }
    for path in EXTRA_SOURCES:
        source_files[relative(path)] = {"path": relative(path), "sha256": sha256_file(path)}
    payload["source_files"] = [source_files[key] for key in sorted(source_files)]
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
    temporary = MANIFEST.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(MANIFEST)
    print("C0C manifest finalized with OKX 1499-candle startup contract")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
