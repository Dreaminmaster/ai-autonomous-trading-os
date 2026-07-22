"""Canonical artifact writer for the C6A source-authority gate.

Packaging is deterministic and fail-closed.  The independent report is written
before the final recursive manifest; the final manifest then includes every
other artifact, including that report, while excluding only itself to avoid a
self-hash cycle.  A final read-only manifest verification is mandatory.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_capture import (
    atomic_write_json,
    build_recursive_manifest,
    canonical_json_bytes,
    sha256_bytes,
)
from atos.c6a_source_authority_review import review_payload, verify_manifest


CANONICAL_OUTPUTS = (
    "query_inventory.json",
    "source_inventory.json",
    "announcement_catalog.json",
    "metadata_states.json",
    "transition_proofs.json",
    "coverage_matrix.json",
    "gate_result.json",
    "independent_review.json",
    "manifest.json",
)


def _as_object(value: Mapping[str, Any], *, label: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SourceAuthorityError(f"{label} must be an object")
    return dict(value)


def _as_list(value: Sequence[Any], *, label: str) -> list[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise SourceAuthorityError(f"{label} must be a list")
    return list(value)


def package_gate_artifact(
    output_root: Path,
    *,
    query_inventory: Mapping[str, Any],
    source_inventory: Mapping[str, Any],
    announcement_catalog: Mapping[str, Any],
    metadata_states: Sequence[Mapping[str, Any]],
    transition_proofs: Sequence[Mapping[str, Any]],
    coverage_matrix: Sequence[Mapping[str, Any]],
    gate_result: Mapping[str, Any],
    failures: Sequence[str],
) -> dict[str, Any]:
    """Write and independently verify the complete canonical artifact."""

    if output_root.exists() and any(output_root.iterdir()):
        raise SourceAuthorityError("artifact output directory must be empty")
    output_root.mkdir(parents=True, exist_ok=True)

    states = _as_list(metadata_states, label="metadata_states")
    proofs = _as_list(transition_proofs, label="transition_proofs")
    coverage = _as_list(coverage_matrix, label="coverage_matrix")
    failure_list = _as_list(failures, label="failures")
    decision = _as_object(gate_result, label="gate_result")

    atomic_write_json(output_root / "query_inventory.json", _as_object(query_inventory, label="query_inventory"))
    atomic_write_json(output_root / "source_inventory.json", _as_object(source_inventory, label="source_inventory"))
    atomic_write_json(
        output_root / "announcement_catalog.json",
        _as_object(announcement_catalog, label="announcement_catalog"),
    )
    atomic_write_json(output_root / "metadata_states.json", {"states": states})
    atomic_write_json(output_root / "transition_proofs.json", {"proofs": proofs})
    atomic_write_json(output_root / "coverage_matrix.json", {"rows": coverage})
    atomic_write_json(output_root / "gate_result.json", decision)

    independent = review_payload(
        {
            "metadata_states": states,
            "transition_proofs": proofs,
            "failures": failure_list,
            "gate_result": decision,
        }
    )
    atomic_write_json(output_root / "independent_review.json", independent)

    manifest = build_recursive_manifest(output_root, excluded_paths=("manifest.json",))
    expected_manifest_files = set(CANONICAL_OUTPUTS) - {"manifest.json"}
    observed_manifest_files = {row["path"] for row in manifest["files"]}
    missing = expected_manifest_files - observed_manifest_files
    if missing:
        raise SourceAuthorityError(f"canonical artifact files missing from manifest: {sorted(missing)}")
    atomic_write_json(output_root / "manifest.json", manifest)
    manifest_errors = verify_manifest(output_root, manifest)
    if manifest_errors:
        raise SourceAuthorityError(f"final manifest verification failed: {manifest_errors}")

    final_gate = decision.get("status")
    independent_status = independent.get("status")
    if final_gate == "PASS" and independent_status != "PASS":
        raise SourceAuthorityError("gate PASS is forbidden when independent review fails")

    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GATE_PACKAGE",
        "gate_status": final_gate,
        "independent_review_status": independent_status,
        "manifest_status": "PASS",
        "manifest_file_count": manifest["file_count"],
        "query_inventory_sha256": sha256_bytes(canonical_json_bytes(query_inventory)),
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }
