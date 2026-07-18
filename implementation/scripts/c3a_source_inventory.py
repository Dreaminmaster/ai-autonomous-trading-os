#!/usr/bin/env python3
"""Capture and verify every effective C3A source file and retained snapshot."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
RESULTS = IMPL / "freqtrade_data/backtest_results/c3a_residual_mean_reversion"
SNAPSHOT = RESULTS / "source_snapshot"
INVENTORY_PATH = RESULTS / "source_inventory.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SOURCE_PATHS = (
    Path(".github/workflows/c3a-residual-mean-reversion.yml"),
    Path("docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_RESIDUAL_MEAN_REVERSION_CONTRACT_V1.md"),
    Path("docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_EXECUTION_ACCOUNTING_ADDENDUM_V1.md"),
    Path("docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_COOLDOWN_CLARIFICATION_V1.md"),
    Path("docs/architecture/phase-c/c2a-low-turnover-allocation/C2A_LOW_TURNOVER_ALLOCATION_RESULT_V1.md"),
    Path("implementation/config/c3a_residual_mean_reversion.json"),
    Path("implementation/config/c3a_public_data.json"),
    Path("implementation/src/atos/c3a_residual.py"),
    Path("implementation/src/atos/c3a_residual_common.py"),
    Path("implementation/src/atos/c3a_residual_indicators.py"),
    Path("implementation/src/atos/c3a_residual_simulation.py"),
    Path("implementation/src/atos/c3a_residual_decision.py"),
    Path("implementation/scripts/c3a_data_guard.py"),
    Path("implementation/scripts/c3a_evidence.py"),
    Path("implementation/scripts/c3a_source_inventory.py"),
    Path("implementation/scripts/finalize_c3a_evidence.py"),
    Path("implementation/tests/test_c3a_residual.py"),
    Path("implementation/tests/test_c3a_data_guard.py"),
    Path("implementation/tests/test_c3a_evidence_contract.py"),
    Path("implementation/pyproject.toml"),
)


class C3ASourceInventoryError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C3ASourceInventoryError(f"unable to hash {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def exact_source_sha() -> str:
    value = os.environ.get("C3A_SOURCE_SHA", "")
    if not SHA_RE.fullmatch(value):
        raise C3ASourceInventoryError("C3A_SOURCE_SHA must be an exact lowercase SHA")
    return value


def validate_source_paths() -> None:
    if len(SOURCE_PATHS) != len(set(SOURCE_PATHS)):
        raise C3ASourceInventoryError("duplicate C3A effective source path")
    for path in SOURCE_PATHS:
        if path.is_absolute() or ".." in path.parts:
            raise C3ASourceInventoryError(f"unsafe C3A source path: {path}")
        if not (ROOT / path).is_file():
            raise C3ASourceInventoryError(f"missing C3A effective source: {path}")


def capture() -> dict[str, Any]:
    source_sha = exact_source_sha()
    validate_source_paths()
    if SNAPSHOT.exists():
        shutil.rmtree(SNAPSHOT)
    entries: list[dict[str, Any]] = []
    for relative in SOURCE_PATHS:
        source = ROOT / relative
        retained = SNAPSHOT / relative
        retained.parent.mkdir(parents=True, exist_ok=True)
        retained.write_bytes(source.read_bytes())
        source_hash = sha256(source)
        retained_hash = sha256(retained)
        if source_hash != retained_hash:
            raise C3ASourceInventoryError(f"snapshot hash mismatch for {relative}")
        entries.append(
            {
                "path": str(relative),
                "sha256": source_hash,
                "size": source.stat().st_size,
                "snapshot_path": str(retained.relative_to(RESULTS)),
                "snapshot_sha256": retained_hash,
            }
        )
    payload = {
        "schema_version": 1,
        "stage": "C3A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "path_count": len(entries),
        "paths": [str(path) for path in SOURCE_PATHS],
        "entries": entries,
        "confirmation_opened": False,
        "c3b_state": "CLOSED",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    write_json(INVENTORY_PATH, payload)
    return payload


def verify() -> dict[str, Any]:
    source_sha = exact_source_sha()
    validate_source_paths()
    try:
        payload = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C3ASourceInventoryError(f"invalid C3A source inventory: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C3ASourceInventoryError("C3A source inventory must be an object")
    if payload.get("status") != "PASS" or payload.get("source_head_sha") != source_sha:
        raise C3ASourceInventoryError("C3A source inventory status or SHA mismatch")
    expected_paths = [str(path) for path in SOURCE_PATHS]
    if payload.get("paths") != expected_paths or payload.get("path_count") != len(expected_paths):
        raise C3ASourceInventoryError("C3A source inventory path drift")
    entries = payload.get("entries")
    if not isinstance(entries, list) or len(entries) != len(SOURCE_PATHS):
        raise C3ASourceInventoryError("C3A source inventory entry count mismatch")
    for relative, entry in zip(SOURCE_PATHS, entries, strict=True):
        if not isinstance(entry, Mapping) or entry.get("path") != str(relative):
            raise C3ASourceInventoryError("C3A source inventory ordering mismatch")
        source = ROOT / relative
        retained = RESULTS / str(entry.get("snapshot_path", ""))
        if not retained.is_file():
            raise C3ASourceInventoryError(f"missing retained C3A source: {relative}")
        current_hash = sha256(source)
        retained_hash = sha256(retained)
        if entry.get("sha256") != current_hash:
            raise C3ASourceInventoryError(f"current source hash mismatch: {relative}")
        if entry.get("snapshot_sha256") != retained_hash or current_hash != retained_hash:
            raise C3ASourceInventoryError(f"retained source hash mismatch: {relative}")
    if payload.get("confirmation_opened") is not False or payload.get("c3b_state") != "CLOSED":
        raise C3ASourceInventoryError("C3A confirmation state drift")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C3ASourceInventoryError("C3A source inventory safety drift")
    return dict(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("capture", "verify"))
    args = parser.parse_args()
    payload = capture() if args.mode == "capture" else verify()
    print(
        f"C3A source inventory {args.mode} PASS: {payload['path_count']} paths / "
        "C3B CLOSED / HOLDOUT CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
