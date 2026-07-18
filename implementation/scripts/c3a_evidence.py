#!/usr/bin/env python3
"""Run the preregistered C3A screen and retain reproducible primitive evidence."""
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

from atos.c3a_residual_reversion import (
    COMPARATORS,
    COST_LABELS,
    PAIR_ORDER,
    POLICIES,
    prepare_market,
    run_screen,
    validate_config,
)
from atos.profitability_diagnostics import discover_candle_file, load_candles


IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
CONFIG_PATH = IMPL / "config/c3a_residual_mean_reversion.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RUNTIME = IMPL / "freqtrade_data/c3a_runtime"
BOUNDARY_PATH = RUNTIME / "c3a_data_boundary.json"
COVERAGE_PATH = RUNTIME / "c3a_data_coverage.json"
RESULTS = IMPL / "freqtrade_data/backtest_results/c3a_residual_mean_reversion"
CONTRACT_PATHS = (
    ROOT / "docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_RESIDUAL_MEAN_REVERSION_CONTRACT_V1.md",
    ROOT / "docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_EXECUTION_ACCOUNTING_ADDENDUM_V1.md",
    ROOT / "docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_COOLDOWN_CLARIFICATION_V1.md",
)
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class C3AEvidenceError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise C3AEvidenceError(f"unable to hash {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C3AEvidenceError(f"invalid JSON {path}: {exc}") from exc


def exact_sha(name: str) -> str:
    value = os.environ.get(name, "")
    if not SHA_RE.fullmatch(value):
        raise C3AEvidenceError(f"{name} must be an exact lowercase 40-character SHA")
    return value


def verify_guard(report: Mapping[str, Any], source_sha: str) -> None:
    if report.get("stage") != "C3A" or report.get("status") != "PASS":
        raise C3AEvidenceError("data guard identity or status mismatch")
    if report.get("source_head_sha") != source_sha:
        raise C3AEvidenceError("data guard source SHA mismatch")
    if report.get("economic_boundary_exclusive") not in (
        "2024-10-01T00:00:00+00:00",
        "2024-10-01T00:00:00Z",
    ):
        raise C3AEvidenceError("data guard boundary drift")
    if report.get("holdout_state") != "HOLDOUT_CLOSED" or report.get("live") != "FORBIDDEN":
        raise C3AEvidenceError("data guard safety drift")
    cells = report.get("cells")
    if not isinstance(cells, list) or len(cells) != 3:
        raise C3AEvidenceError("data guard cell count mismatch")
    if any(not isinstance(item, Mapping) or item.get("status") != "PASS" for item in cells):
        raise C3AEvidenceError("data guard contains a failed cell")


def snapshot_market() -> dict[str, list[dict[str, Any]]]:
    payload: dict[str, list[dict[str, Any]]] = {}
    for pair in PAIR_ORDER:
        path = discover_candle_file(DATA_DIR, pair, "4h")
        rows = [dict(row) for row in load_candles(path)]
        if not rows:
            raise C3AEvidenceError(f"no C3A rows for {pair}")
        payload[pair] = rows
        write_json(RESULTS / "input_candles" / f"{pair.replace('/', '_')}_4h.json", rows)
    market = prepare_market(payload)
    if market.index.max().isoformat() >= "2024-10-01T00:00:00+00:00":
        raise C3AEvidenceError("retained market crosses the C3A boundary")
    return payload


def cell_slug(label: str) -> str:
    return label.replace(".", "_")


def write_pointer(directory: Path, result_path: Path) -> None:
    write_json(
        directory / ".last_result.json",
        {"latest": result_path.name, "sha256": sha256_file(result_path)},
    )


def versions() -> dict[str, str]:
    result = {"python": platform.python_version(), "platform": platform.platform()}
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
        "stage": "C3A",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_ref_sha,
        "file_count": len(files),
        "files": files,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def main() -> int:
    source_sha = exact_sha("C3A_SOURCE_SHA")
    merge_ref_sha = exact_sha("C3A_MERGE_REF_SHA")
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    RESULTS.mkdir(parents=True)

    config = read_json(CONFIG_PATH)
    if not isinstance(config, Mapping):
        raise C3AEvidenceError("C3A config must be an object")
    validate_config(config)
    expected_contracts = tuple(path.relative_to(ROOT) for path in CONTRACT_PATHS)
    if tuple(Path(path) for path in config.get("contract_paths", [])) != expected_contracts:
        raise C3AEvidenceError("C3A contract path drift")

    boundary = read_json(BOUNDARY_PATH)
    coverage = read_json(COVERAGE_PATH)
    if not isinstance(boundary, Mapping) or not isinstance(coverage, Mapping):
        raise C3AEvidenceError("C3A guard reports must be objects")
    verify_guard(boundary, source_sha)
    verify_guard(coverage, source_sha)

    contracts = []
    for path in CONTRACT_PATHS:
        if not path.is_file():
            raise C3AEvidenceError(f"required frozen document missing: {path}")
        contracts.append({"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)})
    write_json(RESULTS / "contracts.json", contracts)
    write_json(RESULTS / "config.json", config)
    write_json(RESULTS / "versions.json", versions())
    write_json(RESULTS / "boundary.json", boundary)
    write_json(RESULTS / "coverage.json", coverage)

    candles = snapshot_market()
    market = prepare_market(candles)
    screen = run_screen(market, config)
    policy_rows = screen["policy_rows"]
    comparator_rows = screen["comparator_rows"]
    if len(policy_rows) != 27 or len(comparator_rows) != 36:
        raise C3AEvidenceError("C3A authoritative row-count invariant failed")

    for row in policy_rows:
        directory = (
            RESULTS
            / "cells"
            / row["policy_id"]
            / row["window_id"]
            / cell_slug(row["cost_label"])
        )
        result_path = directory / "result.json"
        write_json(result_path, row)
        write_pointer(directory, result_path)
    for row in comparator_rows:
        directory = (
            RESULTS
            / "comparators"
            / row["comparator_id"]
            / row["window_id"]
            / cell_slug(row["cost_label"])
        )
        result_path = directory / "result.json"
        write_json(result_path, row)
        write_pointer(directory, result_path)

    pointers = list(RESULTS.rglob(".last_result.json"))
    exports = [path for path in RESULTS.rglob("result.json") if path.is_file()]
    if len(pointers) != 63 or len(exports) != 63:
        raise C3AEvidenceError("C3A must retain exactly 63 pointers and 63 exports")

    write_json(RESULTS / "policy_rows.json", policy_rows)
    write_json(RESULTS / "comparator_rows.json", comparator_rows)
    write_json(RESULTS / "policy_aggregates.json", screen["policy_aggregates"])
    write_json(RESULTS / "comparator_aggregates.json", screen["comparator_aggregates"])
    write_json(RESULTS / "decision.json", screen["decision"])
    write_json(
        RESULTS / "run_summary.json",
        {
            "schema_version": 1,
            "stage": "C3A",
            "status": "PASS",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "economic_result": screen["decision"]["economic_result"],
            "selected_policy": screen["decision"]["selected_policy"],
            "policy_row_count": 27,
            "comparator_row_count": 36,
            "result_pointer_count": 63,
            "result_export_count": 63,
            "policy_aggregate_count": 9,
            "comparator_aggregate_count": 12,
            "contract_documents": contracts,
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
            "errors": [],
        },
    )
    write_json(RESULTS / "manifest.json", build_manifest(source_sha, merge_ref_sha))
    print(
        f"C3A evidence PASS: {screen['decision']['economic_result']} / "
        f"selected={screen['decision']['selected_policy']} / 27 policy rows / "
        "36 comparator rows / C3B_CLOSED / HOLDOUT_CLOSED / LIVE FORBIDDEN"
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
                "stage": "C3A",
                "status": "EVIDENCE_FAILURE",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "confirmation_opened": False,
                "holdout_state": "HOLDOUT_CLOSED",
                "live": "FORBIDDEN",
            },
        )
        print(f"C3A evidence failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
