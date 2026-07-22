"""Validator for the final frozen C6A authoritative execution contract."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from atos.c6a_contract import C6AError

EXPECTED_ORDER = (
    "program_guard",
    "execution_guard",
    "source_plan_preflight",
    "source_inventory",
    "public_capture",
    "canonical_preparation",
    "economic_screen",
    "evidence_shape_preflight",
    "independent_finalizer",
    "decision_margin_guard",
    "evidence_packager",
)
EXPECTED_ENTRYPOINTS = {
    "program_guard": "scripts/c6a_program_guard.py",
    "execution_guard": "scripts/c6a_execution_guard_v2.py",
    "source_plan_preflight": "scripts/c6a_source_plan_preflight.py",
    "source_inventory": "scripts/c6a_authoritative_source_inventory_v3.py",
    "public_capture": "scripts/c6a_capture_authoritative.py",
    "canonical_preparation": "scripts/c6a_prepare_public_data.py",
    "economic_screen": "scripts/run_c6a_screen_authoritative.py",
    "evidence_shape_preflight": "scripts/c6a_finalizer_preflight.py",
    "independent_finalizer": "scripts/c6a_strict_finalizer.py",
    "decision_margin_guard": "scripts/c6a_decision_margin_guard.py",
    "evidence_packager": "scripts/c6a_pack_authoritative_evidence_v2.py",
}
EXPECTED_SCAFFOLDS = (
    "scripts/c6a_capture_public_data.py",
    "scripts/c6a_finalizer.py",
    "scripts/c6a_pack_final_evidence.py",
    "scripts/c6a_pack_authoritative_evidence.py",
    "scripts/c6a_authoritative_source_inventory.py",
    "scripts/run_c6a_screen.py",
)


def canonical_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")
    ).hexdigest()


def validate_execution_contract_v2(
    payload: Mapping[str, Any], *, implementation_root: Path | None = None
) -> str:
    if (
        payload.get("schema_version") != 2
        or payload.get("stage") != "C6A"
        or payload.get("status") != "IMPLEMENTATION_PENDING"
    ):
        raise C6AError("C6A execution-contract V2 identity drift")
    if payload.get("required_design_main_sha") != "071e45218e299367f3bef18832d931df7d278ace":
        raise C6AError("C6A execution-contract V2 design SHA drift")
    entrypoints = payload.get("authoritative_entrypoints")
    if not isinstance(entrypoints, Mapping) or dict(entrypoints) != EXPECTED_ENTRYPOINTS:
        raise C6AError("C6A execution-contract V2 entrypoint map drift")
    order = payload.get("required_order")
    if not isinstance(order, list) or tuple(order) != EXPECTED_ORDER:
        raise C6AError("C6A execution-contract V2 order drift")
    scaffolds = payload.get("non_authoritative_scaffolds")
    if not isinstance(scaffolds, list) or tuple(scaffolds) != EXPECTED_SCAFFOLDS:
        raise C6AError("C6A execution-contract V2 scaffold set drift")
    overlap = set(EXPECTED_ENTRYPOINTS.values()) & set(EXPECTED_SCAFFOLDS)
    if overlap:
        raise C6AError(f"C6A execution-contract V2 role overlap: {sorted(overlap)}")
    if implementation_root is not None:
        root = implementation_root.resolve()
        for role, relative in EXPECTED_ENTRYPOINTS.items():
            path = (root / relative).resolve()
            try:
                path.relative_to(root)
            except ValueError as exc:
                raise C6AError(
                    f"C6A authoritative entrypoint escapes implementation: {role}"
                ) from exc
            if not path.is_file() or path.is_symlink():
                raise C6AError(
                    f"C6A authoritative entrypoint missing or unsafe: {role}"
                )
        for relative in EXPECTED_SCAFFOLDS:
            path = (root / relative).resolve()
            if not path.is_file() or path.is_symlink():
                raise C6AError(f"C6A declared scaffold missing or unsafe: {relative}")
    if (
        payload.get("economic_result_run") is not False
        or payload.get("confirmation_opened") is not False
        or payload.get("c6b_state") != "C6B_CLOSED"
        or payload.get("c5b_state") != "C5B_CLOSED_AND_UNTOUCHED"
        or payload.get("holdout_state") != "HOLDOUT_CLOSED"
        or payload.get("paper_state") != "PAPER_CLOSED"
        or payload.get("shadow_state") != "SHADOW_CLOSED"
        or payload.get("live") != "FORBIDDEN"
    ):
        raise C6AError("C6A execution-contract V2 safety-state drift")
    return canonical_sha256(payload)
