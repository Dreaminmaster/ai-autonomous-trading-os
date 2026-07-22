#!/usr/bin/env python3
"""Inventory and snapshot every effective C6A source before economic execution."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Iterable, Mapping

IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_runtime/c6a_source_inventory.json"
DEFAULT_SNAPSHOT = IMPL / "freqtrade_data/c6a_source_snapshot"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DESIGN_FILES = (
    "docs/architecture/phase-c/c6a-market-neutral-funding-carry/C6A_MARKET_NEUTRAL_FUNDING_CARRY_CONTRACT_V1.md",
    "docs/architecture/phase-c/c6a-market-neutral-funding-carry/C6A_ACCOUNTING_MARGIN_AND_STATISTICS_ADDENDUM_V1.md",
    "docs/architecture/phase-c/c6a-market-neutral-funding-carry/C6A_FUNDING_INTERVAL_AND_HISTORY_CLARIFICATION_V1.md",
    "docs/architecture/phase-c/c6a-market-neutral-funding-carry/C6A_TERMINAL_AND_METADATA_CLARIFICATION_V1.md",
)
EXACT_IMPLEMENTATION_FILES = (
    "implementation/config/c6a_market_neutral_funding_carry.json",
    "implementation/scripts/run_c6a_screen.py",
)


class C6ASourceInventoryError(RuntimeError):
    pass


def _exact_sha() -> str:
    value = os.environ.get("C6A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C6ASourceInventoryError(
            "C6A_SOURCE_SHA must be an exact lowercase 40-character SHA"
        )
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_effective_sources(root: Path = ROOT) -> tuple[str, ...]:
    root = root.resolve()
    paths: set[str] = {*DESIGN_FILES, *EXACT_IMPLEMENTATION_FILES}
    patterns = (
        "implementation/src/atos/c6a_*.py",
        "implementation/scripts/c6a_*.py",
        "implementation/tests/test_c6a_*.py",
        "implementation/tests/test_run_c6a_screen.py",
    )
    for pattern in patterns:
        for path in root.glob(pattern):
            if path.is_file() and not path.is_symlink():
                paths.add(path.relative_to(root).as_posix())
    missing = [relative for relative in paths if not (root / relative).is_file()]
    if missing:
        raise C6ASourceInventoryError(f"C6A effective source missing: {sorted(missing)}")
    workflows = sorted(
        path.relative_to(root).as_posix()
        for path in (root / ".github/workflows").glob("*c6a*")
        if path.is_file()
    )
    if workflows:
        raise C6ASourceInventoryError(
            f"temporary C6A workflow is not permitted in implementation source: {workflows}"
        )
    values = tuple(sorted(paths))
    if len(values) < 20:
        raise C6ASourceInventoryError(
            f"C6A effective-source inventory unexpectedly small: {len(values)}"
        )
    return values


def build_inventory(
    *, root: Path = ROOT, source_sha: str, paths: Iterable[str] | None = None
) -> dict:
    root = root.resolve()
    selected = tuple(paths) if paths is not None else discover_effective_sources(root)
    if tuple(sorted(selected)) != selected or len(set(selected)) != len(selected):
        raise C6ASourceInventoryError("C6A source paths must be sorted and unique")
    files = []
    for relative in selected:
        path = (root / relative).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise C6ASourceInventoryError(f"C6A source escapes repository: {relative}") from exc
        if not path.is_file() or path.is_symlink():
            raise C6ASourceInventoryError(f"C6A source missing or unsafe: {relative}")
        files.append(
            {
                "path": relative,
                "size": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "file_count": len(files),
        "files": files,
        "temporary_authoritative_workflow_present": False,
        "economic_result_run": False,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def snapshot_sources(
    inventory: Mapping, *, root: Path = ROOT, destination: Path
) -> list[dict]:
    root = root.resolve()
    if inventory.get("status") != "PASS":
        raise C6ASourceInventoryError("C6A inventory is not PASS")
    files = inventory.get("files")
    if not isinstance(files, list) or len(files) != inventory.get("file_count"):
        raise C6ASourceInventoryError("C6A inventory file list/count mismatch")
    if destination.exists():
        raise C6ASourceInventoryError(f"refusing to overwrite source snapshot: {destination}")
    copied: list[dict] = []
    try:
        for row in files:
            relative = str(row.get("path", ""))
            source = (root / relative).resolve()
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            observed = _sha256(target)
            if observed != row.get("sha256") or target.stat().st_size != row.get("size"):
                raise C6ASourceInventoryError(f"C6A source snapshot mismatch: {relative}")
            copied.append(
                {
                    "path": relative,
                    "size": target.stat().st_size,
                    "sha256": observed,
                    "status": "PASS",
                }
            )
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return copied


def _write(path: Path, payload: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    args = parser.parse_args(argv)
    source_sha = _exact_sha()
    inventory = build_inventory(source_sha=source_sha)
    copied = snapshot_sources(inventory, destination=args.snapshot)
    inventory["snapshot_file_count"] = len(copied)
    inventory["snapshots"] = copied
    _write(args.output, inventory)
    print(
        "C6A source inventory PASS: "
        f"{inventory['file_count']} files / exact SHA {source_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
