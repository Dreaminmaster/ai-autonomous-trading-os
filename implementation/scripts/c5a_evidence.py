#!/usr/bin/env python3
"""Execute C5A on sealed public inputs and retain primitive evidence."""
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

from atos.c5a_derivatives_crowding import (
    EXPECTED_CONFIG_CANONICAL_SHA256,
    SPOT_INSTRUMENTS,
    SWAP_INSTRUMENTS,
    canonical_sha256,
    run_screen,
    validate_config,
)

IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
CONFIG_PATH = IMPL / "config/c5a_derivatives_crowding_regime.json"
INPUT_ROOT = IMPL / "freqtrade_data/c5a_public_input/sealed"
RUNTIME_ROOT = IMPL / "freqtrade_data/c5a_runtime"
BOUNDARY_PATH = RUNTIME_ROOT / "c5a_data_boundary.json"
COVERAGE_PATH = RUNTIME_ROOT / "c5a_data_coverage.json"
RESULTS = IMPL / "freqtrade_data/backtest_results/c5a_derivatives_crowding_regime"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class C5AEvidenceError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C5AEvidenceError(f"unable to hash {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    temporary.replace(path)


def write_jsonl(path: Path, rows: list[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(dict(row), sort_keys=True, default=str) + "\n")
    temporary.replace(path)


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C5AEvidenceError(f"invalid JSON {path}: {exc}") from exc


def exact_sha(name: str) -> str:
    value = os.environ.get(name, "")
    if not SHA_RE.fullmatch(value):
        raise C5AEvidenceError(f"{name} must be an exact lowercase 40-character SHA")
    return value


def _verify_guard(payload: Mapping[str, Any], source_sha: str, *, mode: str) -> None:
    if payload.get("stage") != "C5A" or payload.get("status") != "PASS":
        raise C5AEvidenceError(f"C5A {mode} guard is not PASS")
    if payload.get("source_head_sha") != source_sha:
        raise C5AEvidenceError(f"C5A {mode} guard source SHA mismatch")
    if payload.get("config_canonical_sha256") != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C5AEvidenceError(f"C5A {mode} guard config hash mismatch")
    if payload.get("economic_boundary_exclusive") not in {
        "2026-01-05T00:00:00Z",
        "2026-01-05T00:00:00+00:00",
    }:
        raise C5AEvidenceError(f"C5A {mode} boundary drift")
    if payload.get("confirmation_opened") is not False:
        raise C5AEvidenceError("C5B unexpectedly opened")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C5AEvidenceError(f"C5A {mode} safety-state drift")
    if int(payload.get("cell_count", -1)) != 9:
        raise C5AEvidenceError(f"C5A {mode} public-series count mismatch")


def load_datasets(*, snapshot: bool = True) -> dict[str, Any]:
    datasets: dict[str, Any] = {"spot": {}, "swap": {}, "mark": {}}
    for spot in SPOT_INSTRUMENTS:
        path = INPUT_ROOT / "spot" / f"{spot}.json"
        rows = read_json(path)
        if not isinstance(rows, list) or len(rows) != 2940:
            raise C5AEvidenceError(f"invalid sealed spot input: {spot}")
        datasets["spot"][spot] = rows
        if snapshot:
            write_json(RESULTS / "input_public" / "spot" / f"{spot}.json", rows)
    for swap in SWAP_INSTRUMENTS:
        for section in ("swap", "mark"):
            path = INPUT_ROOT / section / f"{swap}.json"
            rows = read_json(path)
            if not isinstance(rows, list) or len(rows) != 2940:
                raise C5AEvidenceError(f"invalid sealed {section} input: {swap}")
            datasets[section][swap] = rows
            if snapshot:
                write_json(RESULTS / "input_public" / section / f"{swap}.json", rows)
    return datasets


def _cell_slug(label: str) -> str:
    return label.replace(".", "_")


def _pointer(directory: Path, result: Path) -> None:
    write_json(
        directory / ".last_result.json",
        {"latest": result.name, "sha256": sha256_file(result)},
    )


def versions() -> dict[str, str]:
    payload = {"python": platform.python_version(), "platform": platform.platform()}
    for package in ("numpy", "scipy", "pytest", "freqtrade"):
        try:
            payload[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            payload[package] = "NOT_INSTALLED"
    return payload


def evidence_views(screen: Mapping[str, Any]) -> dict[str, Any]:
    decisions: list[dict[str, Any]] = []
    signals: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    weekly: list[dict[str, Any]] = []
    for cell in screen["policy_rows"]:
        cell_key = {
            "policy_id": cell["policy_id"],
            "window_id": cell["window_id"],
            "cost_label": cell["cost_label"],
        }
        for item in cell["decisions"]:
            decision = {**cell_key, **dict(item)}
            decisions.append(decision)
            rows = item.get("rows")
            if not isinstance(rows, list) or len(rows) != 3:
                raise C5AEvidenceError("every C5A decision must retain three asset signal rows")
            for row in rows:
                signals.append(
                    {
                        **cell_key,
                        "execution_time": item["execution_time"],
                        "signal_time": item["signal_time"],
                        **dict(row),
                    }
                )
        for event in cell["events"]:
            ledger.append({**cell_key, **dict(event)})
        for bucket in cell["weekly_buckets"]:
            weekly.append({**cell_key, **dict(bucket)})
    if len(decisions) != 156:
        raise C5AEvidenceError(f"C5A decision count mismatch: {len(decisions)}")
    if len(signals) != 468:
        raise C5AEvidenceError(f"C5A signal row count mismatch: {len(signals)}")
    if len(weekly) != 156:
        raise C5AEvidenceError(f"C5A weekly bucket count mismatch: {len(weekly)}")
    return {
        "decisions": decisions,
        "signals": signals,
        "ledger": ledger,
        "weekly": weekly,
    }


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
        "stage": "C5A",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_ref_sha,
        "file_count": len(files),
        "files": files,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def main() -> int:
    source_sha = exact_sha("C5A_SOURCE_SHA")
    merge_ref_sha = exact_sha("C5A_MERGE_REF_SHA")
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    RESULTS.mkdir(parents=True)

    config = read_json(CONFIG_PATH)
    if not isinstance(config, Mapping):
        raise C5AEvidenceError("C5A config must be an object")
    validate_config(config)
    if canonical_sha256(config) != EXPECTED_CONFIG_CANONICAL_SHA256:
        raise C5AEvidenceError("C5A retained config hash mismatch")
    boundary = read_json(BOUNDARY_PATH)
    coverage = read_json(COVERAGE_PATH)
    if not isinstance(boundary, Mapping) or not isinstance(coverage, Mapping):
        raise C5AEvidenceError("C5A guard reports must be objects")
    _verify_guard(boundary, source_sha, mode="boundary")
    _verify_guard(coverage, source_sha, mode="coverage")

    contracts = []
    for relative in config["contract_paths"]:
        path = ROOT / str(relative)
        if not path.is_file():
            raise C5AEvidenceError(f"missing frozen C5A contract: {relative}")
        contracts.append({"path": str(relative), "sha256": sha256_file(path)})
    if len(contracts) != 4:
        raise C5AEvidenceError("C5A requires exactly four normative design documents")

    write_json(RESULTS / "config.json", config)
    write_json(RESULTS / "contracts.json", contracts)
    write_json(RESULTS / "versions.json", versions())
    write_json(RESULTS / "boundary.json", boundary)
    write_json(RESULTS / "coverage.json", coverage)
    datasets = load_datasets(snapshot=True)
    screen = run_screen(datasets, config)

    for row in screen["policy_rows"]:
        directory = (
            RESULTS
            / "cells"
            / str(row["policy_id"])
            / str(row["window_id"])
            / _cell_slug(str(row["cost_label"]))
        )
        result = directory / "result.json"
        write_json(result, row)
        _pointer(directory, result)
    for row in screen["comparator_rows"]:
        directory = (
            RESULTS
            / "comparators"
            / str(row["comparator_id"])
            / str(row["window_id"])
            / _cell_slug(str(row["cost_label"]))
        )
        result = directory / "result.json"
        write_json(result, row)
        _pointer(directory, result)

    pointers = list(RESULTS.rglob(".last_result.json"))
    exports = [path for path in RESULTS.rglob("result.json") if path.is_file()]
    if len(pointers) != 30 or len(exports) != 30:
        raise C5AEvidenceError("C5A requires exactly 30 pointers and 30 exports")

    views = evidence_views(screen)
    write_json(RESULTS / "calibration.json", screen["calibration"])
    write_json(RESULTS / "calibration_hashes.json", screen["calibration"]["hashes"])
    write_json(RESULTS / "policy_rows.json", screen["policy_rows"])
    write_json(RESULTS / "comparator_rows.json", screen["comparator_rows"])
    write_json(RESULTS / "policy_aggregates.json", screen["policy_aggregates"])
    write_json(RESULTS / "comparator_aggregates.json", screen["comparator_aggregates"])
    write_json(RESULTS / "decision.json", screen["decision"])
    write_jsonl(RESULTS / "decisions.jsonl", views["decisions"])
    write_jsonl(RESULTS / "per_asset_signals.jsonl", views["signals"])
    write_jsonl(RESULTS / "rebalance_ledger.jsonl", views["ledger"])
    write_jsonl(RESULTS / "weekly_buckets.jsonl", views["weekly"])
    write_json(
        RESULTS / "run_summary.json",
        {
            "schema_version": 1,
            "stage": "C5A",
            "status": "PASS",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "economic_result": screen["decision"]["economic_result"],
            "selected_policy": screen["decision"]["selected_policy"],
            "public_series_count": 9,
            "rows_per_public_series": 2940,
            "calibration_row_count": 117,
            "calibration_observations_per_asset_field": 39,
            "policy_row_count": 12,
            "comparator_row_count": 18,
            "result_pointer_count": 30,
            "result_export_count": 30,
            "policy_aggregate_count": 6,
            "comparator_aggregate_count": 9,
            "decision_count": len(views["decisions"]),
            "per_asset_signal_row_count": len(views["signals"]),
            "rebalance_ledger_entry_count": len(views["ledger"]),
            "weekly_bucket_count": len(views["weekly"]),
            "weekly_psr_observations": 26,
            "selectable_candidate_count": 1,
            "ablation_selectable": False,
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live": "FORBIDDEN",
            "errors": [],
        },
    )
    write_json(RESULTS / "manifest.json", build_manifest(source_sha, merge_ref_sha))
    print(
        f"C5A evidence PASS: {screen['decision']['economic_result']} / "
        f"selected={screen['decision']['selected_policy']} / "
        "12 policy cells / 18 comparator cells / C5B_CLOSED / LIVE_FORBIDDEN"
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
                "stage": "C5A",
                "status": "EVIDENCE_FAILURE",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "confirmation_opened": False,
                "holdout_state": "HOLDOUT_CLOSED",
                "live": "FORBIDDEN",
            },
        )
        print(f"C5A evidence failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
