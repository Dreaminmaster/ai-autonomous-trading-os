"""Preliminary gate orchestration for C6A historical metadata authority.

This module evaluates source and interval evidence but deliberately cannot issue
an authoritative final PASS.  Artifact completeness and physically separate
independent review are established later by ``c6a_source_authority_package``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from atos.c6a_source_authority import (
    FAILURE_PRIORITY,
    FROZEN_TRANSITIONS,
    MetadataState,
    SourceAuthorityError,
    SourceObject,
    build_coverage_matrix,
    gate_result,
    parse_utc_timestamp,
)
from atos.c6a_source_authority_identity import validate_metadata_state_identity


@dataclass(frozen=True)
class GateSnapshot:
    query_inventory_valid: bool
    catalog_complete: bool
    metadata_states: tuple[MetadataState, ...]
    transition_proofs: tuple[Mapping[str, Any], ...]
    source_objects: tuple[SourceObject, ...]
    source_failures: tuple[str, ...] = ()
    forbidden_access_count: int = 0
    unsupported_projection_count: int = 0
    newly_discovered_transition_count: int = 0

    def validate_counts(self) -> None:
        for name, value in (
            ("forbidden_access_count", self.forbidden_access_count),
            ("unsupported_projection_count", self.unsupported_projection_count),
            ("newly_discovered_transition_count", self.newly_discovered_transition_count),
        ):
            if type(value) is not int or value < 0:
                raise SourceAuthorityError(f"{name} must be a non-negative integer")
        unknown = set(self.source_failures) - set(FAILURE_PRIORITY)
        if unknown:
            raise SourceAuthorityError(f"unknown source failure code: {sorted(unknown)}")


def _transition_key(instrument: str, start: Any, end: Any) -> tuple[str, str, str]:
    return (
        instrument,
        parse_utc_timestamp(start).isoformat(),
        parse_utc_timestamp(end).isoformat(),
    )


def required_transition_keys() -> frozenset[tuple[str, str, str]]:
    return frozenset(
        (transition.instrument, transition.start.isoformat(), transition.end.isoformat())
        for transition in FROZEN_TRANSITIONS
    )


def transition_state_keys(states: Sequence[MetadataState]) -> frozenset[tuple[str, str, str]]:
    return frozenset(
        (state.instrument, state.effective_from.isoformat(), state.bounded_end.isoformat())
        for state in states
        if state.authority_mode == "TRANSITION_SAFE_INTERSECTION"
    )


def transition_proof_keys(
    proofs: Sequence[Mapping[str, Any]],
) -> tuple[frozenset[tuple[str, str, str]], list[str]]:
    keys: set[tuple[str, str, str]] = set()
    failures: list[str] = []
    for proof in proofs:
        try:
            key = _transition_key(
                str(proof["instrument"]),
                proof["window_start"],
                proof["window_end_exclusive"],
            )
        except (KeyError, TypeError, SourceAuthorityError):
            failures.append("FAIL_TRANSITION_WINDOW_UNPROVEN")
            continue
        if key in keys:
            failures.append("FAIL_AMBIGUOUS_OR_CONTRADICTORY_STATE")
        keys.add(key)
        if proof.get("status") != "PASS":
            failures.append("FAIL_TRANSITION_INTERSECTION_INVALID")
        for field in (
            "old_state_id",
            "new_state_id",
            "old_lot",
            "new_lot",
            "old_min",
            "new_min",
            "transition_lot",
            "transition_min",
            "boundary_cases",
        ):
            if field not in proof:
                failures.append("FAIL_TRANSITION_WINDOW_UNPROVEN")
                break
    return frozenset(keys), failures


def evaluate_gate_snapshot(
    snapshot: GateSnapshot,
    *,
    source_commit_sha: str,
    query_inventory_sha256: str,
) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], tuple[str, ...]]:
    """Evaluate evidence and return a non-authoritative preliminary decision."""

    snapshot.validate_counts()
    failures: list[str] = list(snapshot.source_failures)
    if not snapshot.query_inventory_valid:
        failures.append("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
    if snapshot.forbidden_access_count:
        failures.append("FAIL_FORBIDDEN_DATA_ACCESS")
    if any(not source.eligible for source in snapshot.source_objects):
        failures.append("FAIL_SOURCE_NOT_OFFICIAL_OKX")
    if not snapshot.catalog_complete:
        failures.append("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")
    if snapshot.unsupported_projection_count:
        failures.append("FAIL_UNSUPPORTED_BACKWARD_PROJECTION")
    if snapshot.newly_discovered_transition_count:
        failures.append("FAIL_NEW_UNFROZEN_TRANSITION")

    try:
        for state in snapshot.metadata_states:
            validate_metadata_state_identity(state)
        coverage = build_coverage_matrix(snapshot.metadata_states)
    except SourceAuthorityError as exc:
        code = str(exc).split(":", 1)[0]
        failures.append(code if code in FAILURE_PRIORITY else "FAIL_REQUIRED_FIELD_MISSING")
        coverage = ()

    required = required_transition_keys()
    state_keys = transition_state_keys(snapshot.metadata_states)
    if state_keys - required:
        failures.append("FAIL_NEW_UNFROZEN_TRANSITION")
    if required - state_keys:
        failures.append("FAIL_TRANSITION_WINDOW_UNPROVEN")

    proof_keys, proof_failures = transition_proof_keys(snapshot.transition_proofs)
    failures.extend(proof_failures)
    if proof_keys - required:
        failures.append("FAIL_NEW_UNFROZEN_TRANSITION")
    if required - proof_keys:
        failures.append("FAIL_TRANSITION_WINDOW_UNPROVEN")

    unique_failures = tuple(code for code in FAILURE_PRIORITY if code in set(failures))
    decision = gate_result(
        source_commit_sha=source_commit_sha,
        query_inventory_sha256=query_inventory_sha256,
        failures=unique_failures,
        source_object_count=len(snapshot.source_objects),
        eligible_source_object_count=sum(source.eligible for source in snapshot.source_objects),
        coverage_rows=len(coverage),
        transition_proof_count=len(snapshot.transition_proofs),
    )
    decision.update(
        {
            "authoritative": False,
            "integrity_state": "PENDING_PACKAGE_AND_INDEPENDENT_REVIEW",
            "uncovered_interval_count": sum(
                code == "FAIL_UNCOVERED_INTERVAL" for code in unique_failures
            ),
            "ambiguous_interval_count": sum(
                code == "FAIL_AMBIGUOUS_OR_CONTRADICTORY_STATE" for code in unique_failures
            ),
            "unsupported_projection_count": snapshot.unsupported_projection_count,
            "forbidden_access_count": snapshot.forbidden_access_count,
            "newly_discovered_transition_count": snapshot.newly_discovered_transition_count,
            "required_transition_count": len(required),
            "observed_transition_state_count": len(state_keys),
            "observed_transition_proof_count": len(proof_keys),
        }
    )
    return decision, coverage, unique_failures


def augment_transition_proof(
    proof: Mapping[str, Any],
    *,
    old_state: MetadataState,
    new_state: MetadataState,
) -> dict[str, Any]:
    """Add primitive exact-decimal fields required by independent review."""

    result = dict(proof)
    result.update(
        {
            "old_lot": old_state.lot_sz,
            "new_lot": new_state.lot_sz,
            "old_min": old_state.min_sz,
            "new_min": new_state.min_sz,
            "old_source_ids": list(old_state.source_ids),
            "new_source_ids": list(new_state.source_ids),
        }
    )
    return result
