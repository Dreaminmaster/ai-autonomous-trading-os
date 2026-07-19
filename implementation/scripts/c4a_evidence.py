#!/usr/bin/env python3
"""Run the preregistered C4A screen and retain reproducible primitive evidence."""
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

from atos.c4a_cross_sectional_runtime import (
    CANDIDATE_PAIRS,
    COMPARATORS,
    COST_LABELS,
    POLICIES,
    prepare_market,
    run_screen,
    validate_config,
)
from atos.profitability_diagnostics import discover_candle_file, load_candles

IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
CONFIG_PATH = IMPL / "config/c4a_large_liquid_cross_sectional_momentum.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RUNTIME = IMPL / "freqtrade_data/c4a_runtime"
BOUNDARY_PATH = RUNTIME / "c4a_data_boundary.json"
COVERAGE_PATH = RUNTIME / "c4a_data_coverage.json"
CONTRACT_GUARD_PATH = RUNTIME / "c4a_contract_guard.json"
RESULTS = IMPL / "freqtrade_data/backtest_results/c4a_large_liquid_cross_sectional_momentum"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class C4AEvidenceError(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    try:
        return sha256_bytes(path.read_bytes())
    except OSError as exc:
        raise C4AEvidenceError(f"unable to hash {path}: {exc}") from exc


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
        raise C4AEvidenceError(f"invalid JSON {path}: {exc}") from exc


def exact_sha(name: str) -> str:
    value = os.environ.get(name, "")
    if not SHA_RE.fullmatch(value):
        raise C4AEvidenceError(f"{name} must be an exact lowercase 40-character SHA")
    return value


def verify_guard(report: Mapping[str, Any], source_sha: str) -> None:
    if report.get("stage") != "C4A" or report.get("status") != "PASS":
        raise C4AEvidenceError("guard identity or status mismatch")
    if report.get("source_head_sha") != source_sha:
        raise C4AEvidenceError("guard source SHA mismatch")
    if report.get("economic_boundary_exclusive") not in (
        "2024-10-01T00:00:00+00:00",
        "2024-10-01T00:00:00Z",
    ):
        raise C4AEvidenceError("guard boundary drift")
    if report.get("holdout_state") != "HOLDOUT_CLOSED" or report.get("live") != "FORBIDDEN":
        raise C4AEvidenceError("guard safety drift")
    cells = report.get("cells")
    if not isinstance(cells, list) or len(cells) != 12:
        raise C4AEvidenceError("guard cell count mismatch")
    if any(not isinstance(item, Mapping) or item.get("status") != "PASS" for item in cells):
        raise C4AEvidenceError("guard contains a failed cell")


def verify_contract_guard(report: Mapping[str, Any], source_sha: str) -> None:
    if report.get("stage") != "C4A" or report.get("status") != "PASS":
        raise C4AEvidenceError("contract guard identity/status mismatch")
    if report.get("source_head_sha") != source_sha:
        raise C4AEvidenceError("contract guard source mismatch")
    if report.get("config_canonical_sha256") != (
        "14e7b96d1167afad6b23c1bc6302e7f9b86ad291f956944ba8f546908402fa92"
    ):
        raise C4AEvidenceError("contract guard config hash drift")
    if report.get("confirmation_opened") is not False:
        raise C4AEvidenceError("C4B unexpectedly opened")
    if report.get("holdout_state") != "HOLDOUT_CLOSED" or report.get("live") != "FORBIDDEN":
        raise C4AEvidenceError("contract guard safety drift")


def snapshot_market() -> dict[str, list[dict[str, Any]]]:
    payload: dict[str, list[dict[str, Any]]] = {}
    for pair in CANDIDATE_PAIRS:
        path = discover_candle_file(DATA_DIR, pair, "4h")
        rows = [dict(row) for row in load_candles(path)]
        if len(rows) != 2376:
            raise C4AEvidenceError(f"unexpected retained C4A rows for {pair}: {len(rows)}")
        payload[pair] = rows
        write_json(
            RESULTS / "input_candles" / f"{pair.replace('/', '_')}_4h.json",
            rows,
        )
    market = prepare_market(payload)
    if len(market) != 2376:
        raise C4AEvidenceError("aligned retained market row-count mismatch")
    if market.index.max().isoformat() >= "2024-10-01T00:00:00+00:00":
        raise C4AEvidenceError("retained market crosses the C4A boundary")
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
        "stage": "C4A",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_ref_sha,
        "file_count": len(files),
        "files": files,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def evidence_views(screen: Mapping[str, Any]) -> dict[str, Any]:
    policy_rows = screen["policy_rows"]
    expected_rows = [row for row in policy_rows if row["cost_label"] == "1.0x"]
    schedule: list[dict[str, Any]] = []
    signal_rows: list[dict[str, Any]] = []
    rebalance_rows: list[dict[str, Any]] = []
    for row in expected_rows:
        for snapshot in row["signals"]:
            schedule.append(
                {
                    "policy_id": row["policy_id"],
                    "window_id": row["window_id"],
                    "execution_time": snapshot["execution_time"],
                    "signal_time": snapshot["signal_time"],
                    "forced_cash": bool(snapshot.get("forced_cash", False)),
                    "risk_on": bool(snapshot["risk_on"]),
                    "breadth": snapshot.get("breadth"),
                    "chosen_pairs": list(snapshot["chosen_pairs"]),
                }
            )
            rows = snapshot.get("rows")
            if not isinstance(rows, list) or len(rows) != 8:
                raise C4AEvidenceError("every expected-cost decision must retain eight signal rows")
            for item in rows:
                signal_rows.append(
                    {
                        "policy_id": row["policy_id"],
                        "window_id": row["window_id"],
                        "execution_time": snapshot["execution_time"],
                        "signal_time": snapshot["signal_time"],
                        "forced_cash": bool(snapshot.get("forced_cash", False)),
                        **dict(item),
                    }
                )
    for row in policy_rows:
        for event in row["events"]:
            if event.get("kind") in {"SCHEDULED_REBALANCE", "FORCED_CASH", "TERMINAL_LIQUIDATION"}:
                rebalance_rows.append(
                    {
                        "policy_id": row["policy_id"],
                        "window_id": row["window_id"],
                        "cost_label": row["cost_label"],
                        **dict(event),
                    }
                )
    if len(schedule) != 120:
        raise C4AEvidenceError(f"weekly schedule count mismatch: {len(schedule)}")
    if len(signal_rows) != 960:
        raise C4AEvidenceError(f"weekly signal row count mismatch: {len(signal_rows)}")
    expected_aggregates = [
        row for row in screen["policy_aggregates"] if row["cost_label"] == "1.0x"
    ]
    if len(expected_aggregates) != 3:
        raise C4AEvidenceError("expected-cost aggregate count mismatch")
    weekly_dsr = {
        row["policy_id"]: list(row["full_week_returns"])
        for row in expected_aggregates
    }
    if any(len(values) != 39 for values in weekly_dsr.values()):
        raise C4AEvidenceError("weekly DSR observation count mismatch")
    multiple_testing = {
        "schema_version": 1,
        "stage": "C4A",
        "trial_count": 3,
        "trial_policy_order": list(POLICIES),
        "within_stage_only": True,
        "policies": [
            {
                "policy_id": row["policy_id"],
                "weekly_mean": row["weekly_mean"],
                "weekly_std": row["weekly_std"],
                "sr_weekly_raw": row["sr_weekly_raw"],
                "sr_weekly_annualized": row["sr_weekly_annualized"],
                "skewness": row["skewness"],
                "ordinary_kurtosis": row["ordinary_kurtosis"],
                "sigma_sr_raw": row["sigma_sr_raw"],
                "sr_star_raw": row["sr_star_raw"],
                "dsr_radicand": row["dsr_radicand"],
                "dsr_z_score": row["dsr_z_score"],
                "within_stage_dsr_probability": row["within_stage_dsr_probability"],
            }
            for row in expected_aggregates
        ],
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    return {
        "schedule": schedule,
        "signals": signal_rows,
        "rebalances": rebalance_rows,
        "weekly_dsr": weekly_dsr,
        "multiple_testing": multiple_testing,
    }


def main() -> int:
    source_sha = exact_sha("C4A_SOURCE_SHA")
    merge_ref_sha = exact_sha("C4A_MERGE_REF_SHA")
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    RESULTS.mkdir(parents=True)

    config = read_json(CONFIG_PATH)
    if not isinstance(config, Mapping):
        raise C4AEvidenceError("C4A config must be an object")
    validate_config(config)
    contract_paths = tuple(ROOT / Path(path) for path in config["contract_paths"])

    boundary = read_json(BOUNDARY_PATH)
    coverage = read_json(COVERAGE_PATH)
    contract_guard = read_json(CONTRACT_GUARD_PATH)
    if not isinstance(boundary, Mapping) or not isinstance(coverage, Mapping):
        raise C4AEvidenceError("C4A data guard reports must be objects")
    if not isinstance(contract_guard, Mapping):
        raise C4AEvidenceError("C4A contract guard report must be an object")
    verify_guard(boundary, source_sha)
    verify_guard(coverage, source_sha)
    verify_contract_guard(contract_guard, source_sha)

    contracts = []
    for path in contract_paths:
        if not path.is_file():
            raise C4AEvidenceError(f"required frozen document missing: {path}")
        contracts.append({"path": str(path.relative_to(ROOT)), "sha256": sha256_file(path)})
    if len(contracts) != 6:
        raise C4AEvidenceError("C4A requires exactly six normative contract documents")
    write_json(RESULTS / "contracts.json", contracts)
    write_json(RESULTS / "config.json", config)
    write_json(RESULTS / "versions.json", versions())
    write_json(RESULTS / "boundary.json", boundary)
    write_json(RESULTS / "coverage.json", coverage)
    write_json(RESULTS / "contract_guard.json", contract_guard)

    candles = snapshot_market()
    screen = run_screen(candles, config)
    policy_rows = screen["policy_rows"]
    comparator_rows = screen["comparator_rows"]
    if len(policy_rows) != 27 or len(comparator_rows) != 36:
        raise C4AEvidenceError("C4A authoritative row-count invariant failed")

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
        raise C4AEvidenceError("C4A must retain exactly 63 pointers and 63 exports")

    views = evidence_views(screen)
    write_json(RESULTS / "candidate_universe.json", screen["universe"]["candidates"])
    write_json(RESULTS / "selected_universe.json", screen["universe"]["selected_pairs"])
    write_json(RESULTS / "weekly_schedule.json", views["schedule"])
    write_jsonl(RESULTS / "weekly_signals.jsonl", views["signals"])
    write_jsonl(RESULTS / "rebalance_ledger.jsonl", views["rebalances"])
    write_json(RESULTS / "weekly_dsr_returns.json", views["weekly_dsr"])
    write_json(RESULTS / "multiple_testing.json", views["multiple_testing"])
    write_json(RESULTS / "policy_rows.json", policy_rows)
    write_json(RESULTS / "comparator_rows.json", comparator_rows)
    write_json(RESULTS / "policy_aggregates.json", screen["policy_aggregates"])
    write_json(RESULTS / "comparator_aggregates.json", screen["comparator_aggregates"])
    write_json(RESULTS / "decision.json", screen["decision"])
    write_json(
        RESULTS / "run_summary.json",
        {
            "schema_version": 1,
            "stage": "C4A",
            "status": "PASS",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "economic_result": screen["decision"]["economic_result"],
            "selected_policy": screen["decision"]["selected_policy"],
            "candidate_pair_count": 12,
            "selected_universe_count": 8,
            "policy_row_count": 27,
            "comparator_row_count": 36,
            "result_pointer_count": 63,
            "result_export_count": 63,
            "policy_aggregate_count": 9,
            "comparator_aggregate_count": 12,
            "weekly_schedule_count": 120,
            "weekly_signal_row_count": 960,
            "dsr_observations_per_policy": 39,
            "contract_documents": contracts,
            "fixed_incumbent_universe": True,
            "within_stage_dsr_only": True,
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
            "errors": [],
        },
    )
    write_json(RESULTS / "manifest.json", build_manifest(source_sha, merge_ref_sha))
    print(
        f"C4A evidence PASS: {screen['decision']['economic_result']} / "
        f"selected={screen['decision']['selected_policy']} / 27 policy rows / "
        "36 comparator rows / 63 pointers / C4B_CLOSED / HOLDOUT_CLOSED / LIVE_FORBIDDEN"
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
                "stage": "C4A",
                "status": "EVIDENCE_FAILURE",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "confirmation_opened": False,
                "holdout_state": "HOLDOUT_CLOSED",
                "live": "FORBIDDEN",
            },
        )
        print(f"C4A evidence failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
