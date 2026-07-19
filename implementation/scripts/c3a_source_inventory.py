#!/usr/bin/env python3
"""Capture the exact effective C3A implementation source inventory."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path


IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
RESULTS = IMPL / "freqtrade_data/backtest_results/c3a_residual_mean_reversion"
OUTPUT = RESULTS / "source_inventory.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
SOURCE_PATHS = (
    "docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_RESIDUAL_MEAN_REVERSION_CONTRACT_V1.md",
    "docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_EXECUTION_ACCOUNTING_ADDENDUM_V1.md",
    "docs/architecture/phase-c/c3a-residual-mean-reversion/C3A_COOLDOWN_CLARIFICATION_V1.md",
    "implementation/config/c3a_residual_mean_reversion.json",
    "implementation/src/atos/c3a_residual_reversion.py",
    "implementation/scripts/c3a_contract_guard.py",
    "implementation/scripts/c3a_data_guard.py",
    "implementation/scripts/c3a_evidence.py",
    "implementation/scripts/c3a_reference_recompute.py",
    "implementation/scripts/c3a_source_inventory.py",
    "implementation/scripts/finalize_c3a_evidence.py",
    "implementation/scripts/complete_c3a_manifest.py",
    "implementation/tests/test_c3a_contract_guard.py",
    "implementation/tests/test_c3a_residual_reversion.py",
    "implementation/tests/test_c3a_data_guard.py",
    "implementation/tests/test_c3a_evidence_contract.py",
    "implementation/pyproject.toml",
)


class C3ASourceInventoryError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C3ASourceInventoryError(f"unable to hash {path}: {exc}") from exc


def exact_sha() -> str:
    value = os.environ.get("C3A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C3ASourceInventoryError("C3A_SOURCE_SHA must be an exact lowercase 40-character SHA")
    return value


def build_inventory(source_sha: str) -> dict:
    if len(SOURCE_PATHS) != len(set(SOURCE_PATHS)):
        raise C3ASourceInventoryError("C3A source inventory contains duplicate paths")
    files = []
    for relative in SOURCE_PATHS:
        path = ROOT / relative
        if not path.is_file():
            raise C3ASourceInventoryError(f"required C3A source missing: {relative}")
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "schema_version": 1,
        "stage": "C3A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "file_count": len(files),
        "files": files,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def main() -> int:
    payload = build_inventory(exact_sha())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(OUTPUT)
    print(f"C3A source inventory PASS: {payload['file_count']} exact files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
