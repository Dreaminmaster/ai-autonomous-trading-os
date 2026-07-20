#!/usr/bin/env python3
"""Snapshot the exact C5A source set into authoritative evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path

IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
RESULTS = IMPL / "freqtrade_data/backtest_results/c5a_derivatives_crowding_regime"
SNAPSHOT_ROOT = RESULTS / "source_snapshot"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

SOURCE_PATHS = (
    "docs/architecture/phase-c/c5a-derivatives-crowding-regime/C5A_DERIVATIVES_CROWDING_REGIME_CONTRACT_V1.md",
    "docs/architecture/phase-c/c5a-derivatives-crowding-regime/C5A_PSR_AND_AGGREGATION_CLARIFICATION_V1.md",
    "docs/architecture/phase-c/c5a-derivatives-crowding-regime/C5A_SIZING_TURNOVER_AND_ACCOUNTING_CLARIFICATION_V1.md",
    "docs/architecture/phase-c/c5a-derivatives-crowding-regime/C5A_PROGRAM_HOLDOUT_RECLASSIFICATION_V1.md",
    "implementation/config/c5a_derivatives_crowding_regime.json",
    "implementation/src/atos/c5a_contract.py",
    "implementation/src/atos/c5a_policy.py",
    "implementation/src/atos/c5a_simulation.py",
    "implementation/src/atos/c5a_metrics.py",
    "implementation/src/atos/c5a_derivatives_crowding.py",
    "implementation/scripts/c5a_download_public_data.py",
    "implementation/scripts/c5a_data_guard.py",
    "implementation/scripts/c5a_program_guard.py",
    "implementation/scripts/c5a_program_evidence_extension.py",
    "implementation/scripts/c5a_program_finalizer_extension.py",
    "implementation/scripts/c5a_evidence.py",
    "implementation/scripts/c5a_reference_contract.py",
    "implementation/scripts/c5a_reference_policy.py",
    "implementation/scripts/c5a_reference_simulation.py",
    "implementation/scripts/c5a_reference_recompute.py",
    "implementation/scripts/c5a_source_inventory.py",
    "implementation/scripts/c5a_finalizer.py",
    "implementation/scripts/complete_c5a_manifest.py",
    "implementation/scripts/run_c5a_finalization.py",
    "implementation/tests/test_c5a_derivatives_crowding.py",
    "implementation/tests/test_c5a_data_guard.py",
    "implementation/tests/test_c5a_program_guard.py",
    "implementation/tests/test_c5a_reference_equivalence.py",
    "implementation/tests/test_c5a_evidence_contract.py",
    "implementation/pyproject.toml",
)


class C5ASourceInventoryError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _exact_sha() -> str:
    value = os.environ.get("C5A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C5ASourceInventoryError("C5A_SOURCE_SHA must be an exact lowercase SHA")
    return value


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    source_sha = _exact_sha()
    if len(SOURCE_PATHS) != len(set(SOURCE_PATHS)):
        raise C5ASourceInventoryError("duplicate C5A source path")
    if SNAPSHOT_ROOT.exists():
        shutil.rmtree(SNAPSHOT_ROOT)
    files = []
    snapshots = []
    for relative in SOURCE_PATHS:
        source = ROOT / relative
        if not source.is_file():
            raise C5ASourceInventoryError(f"required C5A source missing: {relative}")
        digest = _sha(source)
        target = SNAPSHOT_ROOT / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        if _sha(target) != digest:
            raise C5ASourceInventoryError(f"snapshot hash mismatch: {relative}")
        files.append({"path": relative, "size": source.stat().st_size, "sha256": digest})
        snapshots.append(
            {
                "source_path": relative,
                "snapshot_path": str(target.relative_to(RESULTS)),
                "size": target.stat().st_size,
                "sha256": digest,
            }
        )
    common = {
        "schema_version": 1,
        "stage": "C5A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }
    _write(
        RESULTS / "source_inventory.json",
        {**common, "file_count": len(files), "files": files},
    )
    _write(
        RESULTS / "source_snapshot_index.json",
        {**common, "snapshot_count": len(snapshots), "snapshots": snapshots},
    )
    print(f"C5A source inventory PASS: {len(files)} files and snapshots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
