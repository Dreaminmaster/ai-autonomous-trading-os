"""Canonical artifact finalization for the C6A source-authority gate.

The output root may already contain retained raw/decoded source bytes,
transcripts, and logs. Canonical derived files are added without overwriting
those inputs. A physically separate module reviews the complete preliminary
package; only then is the authoritative fail-closed decision written and the
complete recursive manifest verified.
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
from atos.c6a_source_authority_review import (
    choose_primary_failure,
    review_package,
    verify_manifest_complete,
)
from atos.c6a_source_authority_schema import (
    artifact_statistics,
    validate_coverage_records,
    validate_metadata_state_records,
    validate_transition_proof_records,
)


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
EVIDENCE_HASH_EXCLUSIONS = (
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


def _prepare_output_root(output_root: Path) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    collisions = [name for name in CANONICAL_OUTPUTS if (output_root / name).exists()]
    if collisions:
        raise SourceAuthorityError(
            f"canonical artifact output already exists and will not be overwritten: {collisions}"
        )


def _evidence_hashes(root: Path) -> dict[str, str]:
    manifest = build_recursive_manifest(root, excluded_paths=EVIDENCE_HASH_EXCLUSIONS)
    return {str(row["path"]): str(row["sha256"]) for row in manifest["files"]}


def _finalize_decision(
    preliminary: Mapping[str, Any],
    *,
    failures: Sequence[str],
    independent: Mapping[str, Any],
) -> dict[str, Any]:
    independent_status = str(independent.get("status", "FAIL"))
    final_failures = list(failures)
    if independent_status != "PASS":
        final_failures.append("FAIL_INDEPENDENT_REVIEW_MISMATCH")
    primary = choose_primary_failure(final_failures)
    unique: list[str] = []
    for code in final_failures:
        if code not in unique:
            unique.append(code)
    final = dict(preliminary)
    final.update(
        {
            "status": "PASS" if primary is None else "FAIL",
            "result": "PASS" if primary is None else primary,
            "secondary_failures": [code for code in unique if code != primary],
            "authoritative": True,
            "integrity_state": (
                "FINAL_PACKAGE_AND_INDEPENDENT_REVIEW_VERIFIED"
                if independent_status == "PASS"
                else "FINAL_PACKAGE_VERIFIED_INDEPENDENT_REVIEW_FAILED"
            ),
            "independent_review_status": independent_status,
            "independent_review_sha256": sha256_bytes(canonical_json_bytes(independent)),
            "implementation_authorized": False,
            "economic_data_access_authorized": False,
            "live_state": "LIVE_FORBIDDEN",
        }
    )
    return final


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
    """Finalize an immutable package containing retained and derived evidence."""

    _prepare_output_root(output_root)
    states = _as_list(metadata_states, label="metadata_states")
    proofs = _as_list(transition_proofs, label="transition_proofs")
    coverage = _as_list(coverage_matrix, label="coverage_matrix")
    failure_list = [str(item) for item in _as_list(failures, label="failures")]
    preliminary = _as_object(gate_result, label="gate_result")
    if preliminary.get("authoritative") is not False:
        raise SourceAuthorityError("packaging requires a non-authoritative preliminary gate result")
    if preliminary.get("implementation_authorized") is not False or preliminary.get(
        "economic_data_access_authorized"
    ) is not False:
        raise SourceAuthorityError("preliminary gate result improperly authorizes downstream work")

    query = _as_object(query_inventory, label="query_inventory")
    sources = _as_object(source_inventory, label="source_inventory")
    catalog = _as_object(announcement_catalog, label="announcement_catalog")
    validate_metadata_state_records(states)
    validate_transition_proof_records(proofs)
    validate_coverage_records(coverage)

    atomic_write_json(output_root / "query_inventory.json", query)
    atomic_write_json(output_root / "source_inventory.json", sources)
    atomic_write_json(output_root / "announcement_catalog.json", catalog)
    atomic_write_json(output_root / "metadata_states.json", {"states": states})
    atomic_write_json(output_root / "transition_proofs.json", {"proofs": proofs})
    atomic_write_json(output_root / "coverage_matrix.json", {"rows": coverage})

    statistics = artifact_statistics(
        source_inventory=sources,
        announcement_catalog=catalog,
        metadata_states=states,
        transition_proofs=proofs,
        coverage_matrix=coverage,
    )
    preliminary.update(statistics)
    preliminary.update(
        {
            "query_inventory_sha256": sha256_bytes(canonical_json_bytes(query)),
            "artifact_hash_scope": "ALL_RETAINED_AND_DERIVED_FILES_EXCEPT_GATE_REVIEW_MANIFEST",
            "artifact_hash_exclusions": list(EVIDENCE_HASH_EXCLUSIONS),
        }
    )
    atomic_write_json(output_root / "gate_result.json", preliminary)
    preliminary["artifact_hashes"] = _evidence_hashes(output_root)
    atomic_write_json(output_root / "gate_result.json", preliminary)

    preliminary_manifest = build_recursive_manifest(
        output_root,
        excluded_paths=("manifest.json", "independent_review.json"),
    )
    independent = review_package(
        output_root,
        query_inventory=query,
        source_inventory=sources,
        announcement_catalog=catalog,
        metadata_states=states,
        transition_proofs=proofs,
        coverage_matrix=coverage,
        failures=failure_list,
        gate_result=preliminary,
        preliminary_manifest=preliminary_manifest,
    )
    final_decision = _finalize_decision(
        preliminary,
        failures=failure_list,
        independent=independent,
    )
    atomic_write_json(output_root / "gate_result.json", final_decision)
    atomic_write_json(output_root / "independent_review.json", independent)

    final_manifest = build_recursive_manifest(output_root, excluded_paths=("manifest.json",))
    expected_canonical = set(CANONICAL_OUTPUTS) - {"manifest.json"}
    observed = {row["path"] for row in final_manifest["files"]}
    missing_canonical = expected_canonical - observed
    if missing_canonical:
        raise SourceAuthorityError(
            f"canonical artifact files missing from final manifest: {sorted(missing_canonical)}"
        )
    atomic_write_json(output_root / "manifest.json", final_manifest)
    manifest_errors = verify_manifest_complete(
        output_root,
        final_manifest,
        excluded_paths=("manifest.json",),
    )
    if manifest_errors:
        raise SourceAuthorityError(f"final manifest verification failed: {manifest_errors}")
    if final_decision["status"] == "PASS" and independent.get("status") != "PASS":
        raise SourceAuthorityError("gate PASS is forbidden when independent review fails")

    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GATE_PACKAGE",
        "gate_status": final_decision["status"],
        "gate_result": final_decision["result"],
        "independent_review_status": independent.get("status"),
        "manifest_status": "PASS",
        "manifest_file_count": final_manifest["file_count"],
        "query_inventory_sha256": sha256_bytes(canonical_json_bytes(query)),
        "retained_noncanonical_file_count": len(observed - expected_canonical),
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }
