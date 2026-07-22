#!/usr/bin/env python3
"""Authoritative C6A effective-source inventory with one temporary wrapper.

The economic source inventory excludes workflow YAML, but an authoritative run
necessarily executes from a temporary workflow committed on the PR branch.
This wrapper permits exactly one caller-declared C6A workflow, records its hash
as orchestration provenance, and fails if any additional C6A workflow exists.
All effective implementation and design files are still snapshotted and bound
to the exact source SHA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Mapping

from scripts import c6a_source_inventory as base

IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_runtime/c6a_source_inventory.json"
DEFAULT_SNAPSHOT = IMPL / "freqtrade_data/c6a_source_snapshot"


class C6AAuthoritativeInventoryError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def discover_with_temporary_workflow(
    *, root: Path, workflow_path: str
) -> tuple[tuple[str, ...], dict]:
    root = root.resolve()
    declared = (root / workflow_path).resolve()
    try:
        declared.relative_to(root)
    except ValueError as exc:
        raise C6AAuthoritativeInventoryError(
            "declared authoritative workflow escapes repository"
        ) from exc
    if not declared.is_file() or declared.is_symlink():
        raise C6AAuthoritativeInventoryError(
            f"declared authoritative workflow missing or unsafe: {workflow_path}"
        )
    if declared.parent != (root / ".github/workflows").resolve():
        raise C6AAuthoritativeInventoryError(
            "declared authoritative workflow is not under .github/workflows"
        )
    observed = sorted(
        path.relative_to(root).as_posix()
        for path in (root / ".github/workflows").glob("*c6a*")
        if path.is_file()
    )
    if observed != [workflow_path]:
        raise C6AAuthoritativeInventoryError(
            f"expected exactly one declared C6A workflow, observed {observed}"
        )
    paths: set[str] = {*base.DESIGN_FILES, *base.EXACT_IMPLEMENTATION_FILES}
    for pattern in (
        "implementation/src/atos/c6a_*.py",
        "implementation/scripts/c6a_*.py",
        "implementation/tests/test_c6a_*.py",
        "implementation/tests/test_run_c6a_screen.py",
    ):
        for path in root.glob(pattern):
            if path.is_file() and not path.is_symlink():
                paths.add(path.relative_to(root).as_posix())
    missing = sorted(relative for relative in paths if not (root / relative).is_file())
    if missing:
        raise C6AAuthoritativeInventoryError(
            f"C6A effective source missing: {missing}"
        )
    selected = tuple(sorted(paths))
    if len(selected) < 20:
        raise C6AAuthoritativeInventoryError(
            f"C6A effective-source inventory unexpectedly small: {len(selected)}"
        )
    workflow = {
        "path": workflow_path,
        "size": declared.stat().st_size,
        "sha256": _sha256(declared),
        "role": "TEMPORARY_ORCHESTRATION_ONLY",
        "economic_source": False,
        "must_be_removed_before_merge": True,
    }
    return selected, workflow


def build_authoritative_inventory(
    *, root: Path, source_sha: str, workflow_path: str
) -> dict:
    paths, workflow = discover_with_temporary_workflow(
        root=root, workflow_path=workflow_path
    )
    payload = base.build_inventory(
        root=root,
        source_sha=source_sha,
        paths=paths,
    )
    payload["temporary_authoritative_workflow_present"] = True
    payload["temporary_workflow"] = workflow
    payload["workflow_in_economic_source_inventory"] = False
    payload["workflow_removal_required_before_merge"] = True
    return payload


def _write(path: Path, payload: Mapping) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    args = parser.parse_args(argv)
    source_sha = base._exact_sha()
    inventory = build_authoritative_inventory(
        root=ROOT,
        source_sha=source_sha,
        workflow_path=args.workflow_path,
    )
    copied = base.snapshot_sources(
        inventory,
        root=ROOT,
        destination=args.snapshot,
    )
    inventory["snapshot_file_count"] = len(copied)
    inventory["snapshots"] = copied
    _write(args.output, inventory)
    print(
        "C6A authoritative source inventory PASS: "
        f"{inventory['file_count']} economic-source files / one temporary wrapper"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
