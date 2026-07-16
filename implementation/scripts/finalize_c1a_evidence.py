#!/usr/bin/env python3
"""Independently rebind and verify the retained C1A evidence package."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from atos.c1a_family_screen import evaluate_screen, validate_config


IMPL = Path(__file__).resolve().parents[1]
os.chdir(IMPL)
CONFIG_PATH = Path("config/c1a_strategy_family_screen.json")
RESULTS = Path("freqtrade_data/backtest_results/c1a_family_screen")
MANIFEST_PATH = RESULTS / "c1a_family_screen_manifest.json"
REPORT_PATH = RESULTS / "c1a_family_screen_report.json"
FINAL_PATH = RESULTS / "c1a_final_evidence.json"


class C1AFinalizationError(RuntimeError):
    """Raised when C1A retained evidence cannot be independently reproduced."""


def sha256_file(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise C1AFinalizationError(f"unreadable file {path}: {exc}") from exc


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C1AFinalizationError(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise C1AFinalizationError(f"{label} must contain an object")
    return payload


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def verify_hash_rows(rows: Any, label: str, checks: list[str]) -> None:
    if not isinstance(rows, list) or not rows:
        raise C1AFinalizationError(f"{label} must be a non-empty list")
    seen: set[str] = set()
    for index, item in enumerate(rows):
        if not isinstance(item, Mapping):
            raise C1AFinalizationError(f"{label}[{index}] must be an object")
        path_value = item.get("path")
        digest = item.get("sha256")
        if not isinstance(path_value, str) or not path_value:
            raise C1AFinalizationError(f"{label}[{index}] missing path")
        if path_value in seen:
            raise C1AFinalizationError(f"{label} duplicate path {path_value}")
        seen.add(path_value)
        if not isinstance(digest, str) or len(digest) != 64:
            raise C1AFinalizationError(f"{label}[{index}] invalid SHA-256")
        if sha256_file(path_value) != digest:
            raise C1AFinalizationError(f"{label}[{index}] hash mismatch: {path_value}")
        checks.append(f"hash:{path_value}")


def stable_decision(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": payload.get("schema_version"),
        "stage": payload.get("stage"),
        "status": payload.get("status"),
        "selected_family": payload.get("selected_family"),
        "confirmation_opened": payload.get("confirmation_opened"),
        "holdout_state": payload.get("holdout_state"),
        "live": payload.get("live"),
        "family_decisions": payload.get("family_decisions"),
        "eligible_ranking": payload.get("eligible_ranking"),
    }


def main() -> int:
    source_sha = os.environ.get("C1A_SOURCE_SHA", "")
    workflow_sha = os.environ.get("GITHUB_SHA", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    checks: list[str] = []
    try:
        if len(source_sha) != 40:
            raise C1AFinalizationError("C1A_SOURCE_SHA must be an exact commit SHA")
        manifest = read_json(MANIFEST_PATH, "C1A manifest")
        report = read_json(REPORT_PATH, "C1A report")
        config = read_json(CONFIG_PATH, "C1A config")
        validate_config(config)
        checks.append("config:validated")

        if manifest.get("source_head_sha") != source_sha or report.get("source_head_sha") != source_sha:
            raise C1AFinalizationError("source SHA binding mismatch")
        checks.append("source_sha:bound")
        if manifest.get("workflow_sha") != workflow_sha or report.get("workflow_sha") != workflow_sha:
            raise C1AFinalizationError("workflow SHA binding mismatch")
        checks.append("workflow_sha:bound")
        if str(manifest.get("github_run_id")) != str(run_id) or str(report.get("github_run_id")) != str(run_id):
            raise C1AFinalizationError("workflow run ID binding mismatch")
        checks.append("run_id:bound")
        if manifest.get("required_base_sha") != config.get("required_base_sha"):
            raise C1AFinalizationError("base SHA binding mismatch")
        checks.append("base_sha:bound")

        for payload, label in ((manifest, "manifest"), (report, "report")):
            if payload.get("status") not in {"SELECTED", "REJECTED"}:
                raise C1AFinalizationError(f"{label} lacks a valid economic classification")
            if payload.get("confirmation_opened") is not False:
                raise C1AFinalizationError(f"{label} opened confirmation")
            if payload.get("holdout_state") != "HOLDOUT_CLOSED":
                raise C1AFinalizationError(f"{label} opened holdout")
            if payload.get("live") != "FORBIDDEN":
                raise C1AFinalizationError(f"{label} changed live safety")
        checks.extend(["classification:valid", "confirmation:closed", "holdout:closed", "live:forbidden"])
        if manifest.get("selected_family") != report.get("selected_family"):
            raise C1AFinalizationError("selected family mismatch")
        if manifest.get("report_sha256") != sha256_file(REPORT_PATH):
            raise C1AFinalizationError("manifest report hash mismatch")
        checks.append("report:hash_bound")

        verify_hash_rows(manifest.get("source_files"), "source_files", checks)
        verify_hash_rows(manifest.get("retained_result_files"), "retained_result_files", checks)

        data_evidence = manifest.get("data_evidence")
        if not isinstance(data_evidence, Mapping):
            raise C1AFinalizationError("data_evidence missing")
        for prefix in ("boundary", "coverage"):
            path_value = data_evidence.get(f"{prefix}_path")
            digest = data_evidence.get(f"{prefix}_sha256")
            if not isinstance(path_value, str) or sha256_file(path_value) != digest:
                raise C1AFinalizationError(f"{prefix} evidence hash mismatch")
            payload = read_json(Path(path_value), f"{prefix} evidence")
            if payload.get("status") != "PASS" or payload.get("source_head_sha") != source_sha:
                raise C1AFinalizationError(f"{prefix} evidence binding failed")
            if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
                raise C1AFinalizationError(f"{prefix} evidence safety state failed")
            checks.append(f"data:{prefix}")

        recursive = manifest.get("recursive_analysis")
        if not isinstance(recursive, Mapping):
            raise C1AFinalizationError("recursive evidence missing")
        recursive_path = recursive.get("path")
        if not isinstance(recursive_path, str) or sha256_file(recursive_path) != recursive.get("sha256"):
            raise C1AFinalizationError("recursive report hash mismatch")
        recursive_payload = read_json(Path(recursive_path), "recursive report")
        cells = recursive_payload.get("cells")
        if recursive_payload.get("status") != "PASS" or not isinstance(cells, list) or len(cells) != 9:
            raise C1AFinalizationError("recursive report incomplete")
        if any(not isinstance(cell, Mapping) or cell.get("result", {}).get("status") != "PASS" for cell in cells):
            raise C1AFinalizationError("recursive cell did not pass")
        checks.append("recursive:9_cells_pass")

        rows = report.get("rows")
        if not isinstance(rows, list) or len(rows) != 27:
            raise C1AFinalizationError("report must retain exactly 27 screen rows")
        keys = {(row.get("family_id"), row.get("window_id"), row.get("cost_multiplier")) for row in rows if isinstance(row, Mapping)}
        if len(keys) != 27:
            raise C1AFinalizationError("screen row key coverage mismatch")
        for index, row in enumerate(rows):
            if not isinstance(row, Mapping):
                raise C1AFinalizationError(f"row[{index}] must be an object")
            for path_key, hash_key in (
                ("export_path", "export_sha256"),
                ("command_path", "command_sha256"),
                ("log_path", "log_sha256"),
            ):
                path_value = row.get(path_key)
                if not isinstance(path_value, str) or sha256_file(path_value) != row.get(hash_key):
                    raise C1AFinalizationError(f"row[{index}] {path_key} hash mismatch")
            command = read_json(Path(row["command_path"]), f"row[{index}] command")
            if command.get("returncode") != 0:
                raise C1AFinalizationError(f"row[{index}] command did not pass")
            checks.append(f"row:{index}:bound")

        recomputed = evaluate_screen(rows, config)
        if stable_decision(recomputed) != stable_decision(report):
            raise C1AFinalizationError("independent gate recomputation mismatch")
        checks.append("gate:independently_recomputed")

        final = {
            "schema_version": 1,
            "status": "PASS",
            "stage": "C1A",
            "source_head_sha": source_sha,
            "workflow_sha": workflow_sha,
            "github_run_id": run_id,
            "manifest_path": str(MANIFEST_PATH),
            "manifest_sha256": sha256_file(MANIFEST_PATH),
            "report_path": str(REPORT_PATH),
            "report_sha256": sha256_file(REPORT_PATH),
            "economic_status": report["status"],
            "selected_family": report["selected_family"],
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
            "checks_passed": len(checks),
            "checks": checks,
            "errors": [],
        }
        write_json(FINAL_PATH, final)
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "status": "FAIL",
            "stage": "C1A",
            "source_head_sha": source_sha,
            "workflow_sha": workflow_sha,
            "github_run_id": run_id,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "checks_passed": len(checks),
            "checks": checks,
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        }
        FINAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        write_json(FINAL_PATH, failure)
        print(f"C1A finalization FAIL: {type(exc).__name__}: {exc}")
        raise
    print(
        f"C1A finalization PASS: {final['checks_passed']} checks, "
        f"economic_status={final['economic_status']}, confirmation_opened=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
