#!/usr/bin/env python3
"""Capture and verify the exact C1A source set retained with the evidence artifact."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any


IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
RESULTS = IMPL / "freqtrade_data/backtest_results/c1a_family_screen"
INVENTORY = RESULTS / "c1a_source_inventory.json"
SNAPSHOT = RESULTS / "source_snapshot"
SOURCE_PATHS = [
    ".github/workflows/c1a-strategy-family-screen.yml",
    "docs/architecture/phase-c/c1a-family-screen/C1A_STRATEGY_FAMILY_SCREEN_CONTRACT_V1.md",
    "implementation/pyproject.toml",
    "implementation/config/c1a_strategy_family_screen.json",
    "implementation/config/policy.validation.json",
    "implementation/freqtrade_data/config.dryrun.json",
    "implementation/freqtrade_data/strategies/c1a_common.py",
    "implementation/scripts/c0c_development_core.py",
    "implementation/scripts/c1a_data_guard.py",
    "implementation/scripts/c1a_evidence.py",
    "implementation/scripts/c1a_source_inventory.py",
    "implementation/scripts/finalize_c1a_evidence.py",
    "implementation/scripts/run_c0c_development.py",
    "implementation/scripts/setup_freqtrade.sh",
    "implementation/scripts/validate_no_secrets.sh",
    "implementation/src/atos/c0b_export.py",
    "implementation/src/atos/c0c_walk_forward.py",
    "implementation/src/atos/c1a_family_screen.py",
    "implementation/src/atos/profitability_diagnostics.py",
    "implementation/tests/test_c1a_data_guard.py",
    "implementation/tests/test_c1a_evidence_contract.py",
    "implementation/tests/test_c1a_family_screen.py",
    "implementation/tests/test_c1a_strategy_contract.py",
]


class C1ASourceInventoryError(RuntimeError):
    """Raised when retained C1A source cannot be bound exactly."""


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C1ASourceInventoryError(f"unreadable source {path}: {exc}") from exc


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C1ASourceInventoryError(f"invalid source inventory: {exc}") from exc
    if not isinstance(payload, dict):
        raise C1ASourceInventoryError("source inventory must contain an object")
    return payload


def source_sha() -> str:
    value = os.environ.get("C1A_SOURCE_SHA", "")
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise C1ASourceInventoryError("C1A_SOURCE_SHA must be an exact lowercase commit SHA")
    return value


def capture() -> dict[str, Any]:
    exact_source = source_sha()
    if SNAPSHOT.exists():
        shutil.rmtree(SNAPSHOT)
    entries = []
    for relative in SOURCE_PATHS:
        source = ROOT / relative
        if not source.is_file():
            raise C1ASourceInventoryError(f"required source missing: {relative}")
        snapshot = SNAPSHOT / relative
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, snapshot)
        source_digest = sha256_file(source)
        snapshot_digest = sha256_file(snapshot)
        if source_digest != snapshot_digest:
            raise C1ASourceInventoryError(f"source snapshot mismatch: {relative}")
        entries.append(
            {
                "path": relative,
                "source_sha256": source_digest,
                "snapshot_path": str(snapshot.relative_to(IMPL)),
                "snapshot_sha256": snapshot_digest,
            }
        )
    payload = {
        "schema_version": 1,
        "status": "PASS",
        "stage": "C1A",
        "source_head_sha": exact_source,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "files": entries,
    }
    write_json(INVENTORY, payload)
    return payload


def verify() -> dict[str, Any]:
    exact_source = source_sha()
    payload = read_json(INVENTORY)
    if payload.get("status") != "PASS" or payload.get("stage") != "C1A":
        raise C1ASourceInventoryError("source inventory status/stage mismatch")
    if payload.get("source_head_sha") != exact_source:
        raise C1ASourceInventoryError("source inventory commit binding mismatch")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C1ASourceInventoryError("source inventory safety state mismatch")
    rows = payload.get("files")
    if not isinstance(rows, list) or len(rows) != len(SOURCE_PATHS):
        raise C1ASourceInventoryError("source inventory file count mismatch")
    if [row.get("path") for row in rows if isinstance(row, dict)] != SOURCE_PATHS:
        raise C1ASourceInventoryError("source inventory path order mismatch")
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise C1ASourceInventoryError(f"source inventory row {index} is invalid")
        relative = row["path"]
        source = ROOT / relative
        snapshot = IMPL / row.get("snapshot_path", "")
        source_digest = sha256_file(source)
        snapshot_digest = sha256_file(snapshot)
        if source_digest != row.get("source_sha256"):
            raise C1ASourceInventoryError(f"current source hash mismatch: {relative}")
        if snapshot_digest != row.get("snapshot_sha256") or snapshot_digest != source_digest:
            raise C1ASourceInventoryError(f"snapshot hash mismatch: {relative}")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("capture", "verify"))
    args = parser.parse_args()
    payload = capture() if args.mode == "capture" else verify()
    print(
        f"C1A source inventory {args.mode} PASS: {len(payload['files'])} files, "
        "HOLDOUT_CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
