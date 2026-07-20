#!/usr/bin/env python3
"""Capture and snapshot the exact effective C4A implementation source set."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
RESULTS = IMPL / "freqtrade_data/backtest_results/c4a_large_liquid_cross_sectional_momentum"
INVENTORY_PATH = RESULTS / "source_inventory.json"
SNAPSHOT_ROOT = RESULTS / "source_snapshot"
SNAPSHOT_INDEX_PATH = RESULTS / "source_snapshot_index.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SOURCE_PATHS = (
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_LARGE_LIQUID_CROSS_SECTIONAL_MOMENTUM_CONTRACT_V1.md",
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_UNIVERSE_AND_MULTIPLE_TESTING_ADDENDUM_V1.md",
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_WEEKLY_BOUNDARY_CLARIFICATION_V1.md",
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_DSR_AND_UNIVERSE_SCOPE_CLARIFICATION_V1.md",
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_ACCOUNTING_AND_CONTRIBUTION_CLARIFICATION_V1.md",
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_EXPOSURE_ERRATUM_V1.md",
    "implementation/config/c4a_large_liquid_cross_sectional_momentum.json",
    "implementation/src/atos/c4a_cross_sectional_momentum.py",
    "implementation/src/atos/c4a_cross_sectional_runtime.py",
    "implementation/scripts/c4a_contract_guard.py",
    "implementation/scripts/c4a_data_guard.py",
    "implementation/scripts/c4a_evidence.py",
    "implementation/scripts/c4a_evidence_postprocess.py",
    "implementation/scripts/c4a_reference_recompute.py",
    "implementation/scripts/c4a_reference_runtime.py",
    "implementation/scripts/c4a_source_inventory.py",
    "implementation/scripts/c4a_finalizer_core.py",
    "implementation/scripts/c4a_finalizer_extensions.py",
    "implementation/scripts/finalize_c4a_evidence.py",
    "implementation/scripts/complete_c4a_manifest.py",
    "implementation/tests/conftest.py",
    "implementation/tests/test_c4a_cross_sectional_momentum.py",
    "implementation/tests/test_c4a_guards.py",
    "implementation/tests/test_c4a_reference_equivalence.py",
    "implementation/tests/test_c4a_evidence_contract.py",
    "implementation/pyproject.toml",
)


class C4ASourceInventoryError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C4ASourceInventoryError(f"unable to hash {path}: {exc}") from exc


def exact_sha() -> str:
    value = os.environ.get("C4A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C4ASourceInventoryError("C4A_SOURCE_SHA must be an exact lowercase 40-character SHA")
    return value


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def build_inventory(source_sha: str) -> tuple[dict, dict]:
    if len(SOURCE_PATHS) != len(set(SOURCE_PATHS)):
        raise C4ASourceInventoryError("C4A source inventory contains duplicate paths")
    if SNAPSHOT_ROOT.exists():
        shutil.rmtree(SNAPSHOT_ROOT)
    files = []
    snapshots = []
    for relative in SOURCE_PATHS:
        source = ROOT / relative
        if not source.is_file():
            raise C4ASourceInventoryError(f"required C4A source missing: {relative}")
        digest = sha256_file(source)
        target = SNAPSHOT_ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        snapshot_digest = sha256_file(target)
        if snapshot_digest != digest:
            raise C4ASourceInventoryError(f"source snapshot hash mismatch: {relative}")
        files.append({"path": relative, "size": source.stat().st_size, "sha256": digest})
        snapshots.append(
            {
                "source_path": relative,
                "snapshot_path": str(target.relative_to(RESULTS)),
                "size": target.stat().st_size,
                "sha256": snapshot_digest,
            }
        )
    common = {
        "schema_version": 1,
        "stage": "C4A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    inventory = {**common, "file_count": len(files), "files": files}
    snapshot_index = {**common, "snapshot_count": len(snapshots), "snapshots": snapshots}
    return inventory, snapshot_index


def main() -> int:
    inventory, snapshots = build_inventory(exact_sha())
    write_json(INVENTORY_PATH, inventory)
    write_json(SNAPSHOT_INDEX_PATH, snapshots)
    print(
        f"C4A source inventory PASS: {inventory['file_count']} exact files / "
        f"{snapshots['snapshot_count']} retained snapshots"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
