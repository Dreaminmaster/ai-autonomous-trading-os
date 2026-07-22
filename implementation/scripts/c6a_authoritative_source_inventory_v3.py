#!/usr/bin/env python3
"""Final C6A authoritative source inventory.

This version binds both reviewed plans into the economic-source snapshot:
- the exact public-acquisition source plan; and
- the exact authoritative execution-entrypoint contract.

It also records exactly one temporary workflow as orchestration-only provenance.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from atos.c6a_execution_contract_v2 import validate_execution_contract_v2
from atos.c6a_source_plan import validate_source_plan
from scripts import c6a_authoritative_source_inventory as workflow_inventory
from scripts import c6a_source_inventory

IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
DEFAULT_PLAN = IMPL / "config/c6a_public_source_plan.json"
DEFAULT_EXECUTION = IMPL / "config/c6a_execution_contract_v2.json"
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_runtime/c6a_source_inventory.json"
DEFAULT_SNAPSHOT = IMPL / "freqtrade_data/c6a_source_snapshot"


class C6AAuthoritativeInventoryV3Error(RuntimeError):
    pass


def _read_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6AAuthoritativeInventoryV3Error(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C6AAuthoritativeInventoryV3Error(f"{label} must be an object")
    return payload


def _relative_file(root: Path, path: Path, label: str) -> str:
    root = root.resolve()
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root).as_posix()
    except ValueError as exc:
        raise C6AAuthoritativeInventoryV3Error(
            f"{label} must be committed inside the repository"
        ) from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise C6AAuthoritativeInventoryV3Error(f"{label} missing or unsafe")
    return relative


def build_inventory_v3(
    *,
    root: Path,
    source_sha: str,
    workflow_path: str,
    plan_path: Path,
    execution_contract_path: Path,
) -> dict[str, Any]:
    root = root.resolve()
    plan_relative = _relative_file(root, plan_path, "C6A source plan")
    execution_relative = _relative_file(
        root, execution_contract_path, "C6A execution contract"
    )
    plan_payload = _read_object(plan_path, "C6A source plan")
    execution_payload = _read_object(
        execution_contract_path, "C6A execution contract"
    )
    source_entries = validate_source_plan(plan_payload)
    execution_digest = validate_execution_contract_v2(
        execution_payload,
        implementation_root=(root / "implementation"),
    )
    paths, workflow = workflow_inventory.discover_with_temporary_workflow(
        root=root,
        workflow_path=workflow_path,
    )
    selected = tuple(sorted({*paths, plan_relative, execution_relative}))
    payload = c6a_source_inventory.build_inventory(
        root=root,
        source_sha=source_sha,
        paths=selected,
    )
    records = {row["path"]: row for row in payload["files"]}
    payload.update(
        {
            "temporary_authoritative_workflow_present": True,
            "temporary_workflow": workflow,
            "workflow_in_economic_source_inventory": False,
            "workflow_removal_required_before_merge": True,
            "source_plan": {
                **records[plan_relative],
                "entry_count": len(source_entries),
                "role": "FROZEN_PUBLIC_ACQUISITION_AUTHORITY",
            },
            "source_plan_in_economic_source_inventory": True,
            "execution_contract": {
                **records[execution_relative],
                "canonical_sha256": execution_digest,
                "role": "FROZEN_AUTHORITATIVE_EXECUTION_AUTHORITY",
            },
            "execution_contract_in_economic_source_inventory": True,
        }
    )
    return payload


def _write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workflow-path", required=True)
    parser.add_argument("--plan", type=Path, default=DEFAULT_PLAN)
    parser.add_argument("--execution-contract", type=Path, default=DEFAULT_EXECUTION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    args = parser.parse_args(argv)
    source_sha = c6a_source_inventory._exact_sha()
    inventory = build_inventory_v3(
        root=ROOT,
        source_sha=source_sha,
        workflow_path=args.workflow_path,
        plan_path=args.plan,
        execution_contract_path=args.execution_contract,
    )
    copied = c6a_source_inventory.snapshot_sources(
        inventory,
        root=ROOT,
        destination=args.snapshot,
    )
    inventory["snapshot_file_count"] = len(copied)
    inventory["snapshots"] = copied
    _write(args.output, inventory)
    print(
        "C6A authoritative source inventory V3 PASS: "
        f"{inventory['file_count']} economic-source files / plans bound"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
