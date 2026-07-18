#!/usr/bin/env python3
"""Run the preregistered C2A allocation screen and retain reproducible evidence."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

from atos.c2a_allocation_runtime import (
    COST_LABELS,
    PAIR_ORDER,
    POLICIES,
    aggregate_comparator,
    aggregate_policy,
    decide,
    prepare_market,
    simulate_buy_hold,
    simulate_window,
    validate_config,
)
from atos.profitability_diagnostics import discover_candle_file, load_candles


IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
CONFIG_PATH = IMPL / "config/c2a_low_turnover_allocation.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RUNTIME = IMPL / "freqtrade_data/c2a_runtime"
BOUNDARY_PATH = RUNTIME / "c2a_data_boundary.json"
COVERAGE_PATH = RUNTIME / "c2a_data_coverage.json"
RESULTS = IMPL / "freqtrade_data/backtest_results/c2a_low_turnover_allocation"
CONTRACT_PATHS = (
    ROOT
    / "docs/architecture/phase-c/c2a-low-turnover-allocation/C2A_LOW_TURNOVER_ALLOCATION_CONTRACT_V1.md",
    ROOT
    / "docs/architecture/phase-c/c2a-low-turnover-allocation/C2A_WINDOW_ACCOUNTING_ADDENDUM_V1.md",
)
C1A_RESULT = (
    ROOT
    / "docs/architecture/phase-c/c1a-family-screen/C1A_STRATEGY_FAMILY_SCREEN_RESULT_V1.md"
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class C2AEvidenceError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise C2AEvidenceError(f"unable to hash {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C2AEvidenceError(f"invalid JSON {path}: {exc}") from exc


def exact_sha(name: str) -> str:
    value = os.environ.get(name, "")
    if not SHA_RE.fullmatch(value):
        raise C2AEvidenceError(f"{name} must be an exact lowercase 40-character SHA")
    return value


def verify_guard(report: Mapping[str, Any], source_sha: str, cells: int) -> None:
    if report.get("status") != "PASS" or report.get("source_head_sha") != source_sha:
        raise C2AEvidenceError("data guard status or source SHA mismatch")
    if report.get("economic_boundary_exclusive") not in (
        "2024-10-01T00:00:00+00:00",
        "2024-10-01T00:00:00Z",
    ):
        raise C2AEvidenceError("data guard boundary drift")
    if report.get("holdout_state") != "HOLDOUT_CLOSED" or report.get("live") != "FORBIDDEN":
        raise C2AEvidenceError("data guard safety drift")
    entries = report.get("cells")
    if not isinstance(entries, list) or len(entries) != cells:
        raise C2AEvidenceError("data guard cell count mismatch")
    if any(item.get("status") != "PASS" for item in entries if isinstance(item, Mapping)):
        raise C2AEvidenceError("data guard contains a failed cell")


def snapshot_market(config: Mapping[str, Any]) -> dict[str, list[dict[str, Any]]]:
    payload: dict[str, list[dict[str, Any]]] = {}
    for pair in PAIR_ORDER:
        path = discover_candle_file(DATA_DIR, pair, "1d")
        rows = [dict(row) for row in load_candles(path)]
        if not rows:
            raise C2AEvidenceError(f"no C2A rows for {pair}")
        payload[pair] = rows
        write_json(RESULTS / "input_candles" / f"{pair.replace('/', '_')}_1d.json", rows)
    prepare_market(payload)
    return payload


def compact_cell(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in row.items()
        if key not in {"daily", "events"}
    }


def cell_slug(label: str) -> str:
    return label.replace(".", "_")


def write_pointer(directory: Path, result_path: Path) -> None:
    write_json(
        directory / ".last_result.json",
        {
            "latest": result_path.name,
            "sha256": sha256_file(result_path),
        },
    )


def versions() -> dict[str, str]:
    result = {
        "python": platform.python_version(),
        "platform": platform.platform(),
    }
    for package in ("numpy", "pandas", "scipy", "freqtrade"):
        try:
            result[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            result[package] = "NOT_INSTALLED"
    return result


def build_manifest(source_sha: str, merge_ref_sha: str) -> dict[str, Any]:
    files = []
    for path in sorted(RESULTS.rglob("*")):
        if not path.is_file() or path.name == "manifest.json":
            continue
        files.append(
            {
                "path": str(path.relative_to(RESULTS)),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": 1,
        "stage": "C2A",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_ref_sha,
        "file_count": len(files),
        "files": files,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def main() -> int:
    source_sha = exact_sha("C2A_SOURCE_SHA")
    merge_ref_sha = exact_sha("C2A_MERGE_REF_SHA")
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    RESULTS.mkdir(parents=True)

    config = read_json(CONFIG_PATH)
    if not isinstance(config, Mapping):
        raise C2AEvidenceError("C2A config must be an object")
    validate_config(config)
    if config.get("required_base_sha") != "995dc9aac3c934c01e196270fc2d41d50278063b":
        raise C2AEvidenceError("C2A frozen base SHA drift")
    if tuple(Path(path) for path in config.get("contract_paths", [])) != tuple(
        path.relative_to(ROOT) for path in CONTRACT_PATHS
    ):
        raise C2AEvidenceError("C2A contract path drift")

    boundary = read_json(BOUNDARY_PATH)
    coverage = read_json(COVERAGE_PATH)
    if not isinstance(boundary, Mapping) or not isinstance(coverage, Mapping):
        raise C2AEvidenceError("C2A guard reports must be objects")
    verify_guard(boundary, source_sha, 3)
    verify_guard(coverage, source_sha, 3)

    contracts = []
    for path in (*CONTRACT_PATHS, C1A_RESULT):
        if not path.is_file():
            raise C2AEvidenceError(f"required frozen document missing: {path}")
        contracts.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha256_file(path),
            }
        )
    write_json(RESULTS / "contracts.json", contracts)
    write_json(RESULTS / "config.json", config)
    write_json(RESULTS / "versions.json", versions())
    write_json(RESULTS / "boundary.json", boundary)
    write_json(RESULTS / "coverage.json", coverage)

    candles = snapshot_market(config)
    market = prepare_market(candles)
    if market.index.max().isoformat() >= "2024-10-01T00:00:00+00:00":
        raise C2AEvidenceError("retained market crosses the C2A boundary")

    policy_rows: list[dict[str, Any]] = []
    for policy in POLICIES:
        for window in config["screen_windows"]:
            for cost_label in COST_LABELS:
                row = simulate_window(
                    market,
                    policy=policy,
                    window=window,
                    cost_label=cost_label,
                    config=config,
                )
                directory = (
                    RESULTS
                    / "cells"
                    / policy
                    / window["id"]
                    / cell_slug(cost_label)
                )
                result_path = directory / "result.json"
                write_json(result_path, row)
                write_pointer(directory, result_path)
                policy_rows.append(row)
    if len(policy_rows) != 27 or len(
        {
            (row["policy_id"], row["window_id"], row["cost_label"])
            for row in policy_rows
        }
    ) != 27:
        raise C2AEvidenceError("C2A must retain exactly 27 unique economic rows")

    comparator_rows: list[dict[str, Any]] = []
    for comparator in ("cash", "btc_buy_hold", "equal_weight_buy_hold"):
        for window in config["screen_windows"]:
            for cost_label in COST_LABELS:
                row = simulate_buy_hold(
                    market,
                    comparator_id=comparator,
                    window=window,
                    cost_label=cost_label,
                    config=config,
                )
                directory = (
                    RESULTS
                    / "comparators"
                    / comparator
                    / window["id"]
                    / cell_slug(cost_label)
                )
                result_path = directory / "result.json"
                write_json(result_path, row)
                write_pointer(directory, result_path)
                comparator_rows.append(row)
    if len(comparator_rows) != 27:
        raise C2AEvidenceError("C2A comparator row count mismatch")

    policy_aggregates = [
        aggregate_policy(
            policy_rows,
            policy=policy,
            cost_label=cost_label,
            config=config,
        )
        for policy in POLICIES
        for cost_label in COST_LABELS
    ]
    comparator_aggregates = [
        aggregate_comparator(comparator_rows, comparator, cost_label)
        for comparator in ("cash", "btc_buy_hold", "equal_weight_buy_hold")
        for cost_label in COST_LABELS
    ]
    decision = decide(policy_aggregates, comparator_aggregates, config)

    write_json(RESULTS / "economic_rows.json", [compact_cell(row) for row in policy_rows])
    write_json(RESULTS / "comparator_rows.json", comparator_rows)
    write_json(RESULTS / "policy_aggregates.json", policy_aggregates)
    write_json(RESULTS / "comparator_aggregates.json", comparator_aggregates)
    write_json(RESULTS / "decision.json", decision)
    write_json(
        RESULTS / "run_summary.json",
        {
            "schema_version": 1,
            "stage": "C2A",
            "status": "PASS",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "economic_result": decision["economic_result"],
            "selected_policy": decision["selected_policy"],
            "economic_row_count": 27,
            "comparator_row_count": 27,
            "policy_aggregate_count": 9,
            "comparator_aggregate_count": 9,
            "contract_documents": contracts,
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
            "errors": [],
        },
    )
    write_json(RESULTS / "manifest.json", build_manifest(source_sha, merge_ref_sha))
    print(
        f"C2A evidence PASS: {decision['economic_result']} / "
        f"selected={decision['selected_policy']} / 27 rows / "
        "CONFIRMATION_CLOSED / HOLDOUT_CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        RESULTS.mkdir(parents=True, exist_ok=True)
        write_json(
            RESULTS / "evidence_failure.json",
            {
                "schema_version": 1,
                "stage": "C2A",
                "status": "EVIDENCE_FAILURE",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "confirmation_opened": False,
                "holdout_state": "HOLDOUT_CLOSED",
                "live": "FORBIDDEN",
            },
        )
        print(f"C2A evidence failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
