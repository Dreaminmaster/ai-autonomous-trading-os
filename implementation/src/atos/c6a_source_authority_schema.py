"""Canonical output-schema validators for the C6A source-authority gate.

These checks sit between evidence evaluation and packaging.  They prevent a
mathematically plausible state from entering the canonical artifact unless each
field and interval boundary is tied to retained source IDs exactly as required
by the merged design contract.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from atos.c6a_source_authority import SourceAuthorityError


COMMON_STATE_FIELDS = (
    "inst_type",
    "base_ccy",
    "quote_ccy",
    "lot_sz",
    "min_sz",
    "tick_sz",
    "listing_state",
)
SWAP_STATE_FIELDS = ("settle_ccy", "ct_val", "ct_val_ccy")
TRANSITION_UNCHANGED_FIELDS = (
    "inst_type",
    "base_ccy",
    "quote_ccy",
    "settle_ccy",
    "ct_val",
    "ct_val_ccy",
    "tick_sz",
    "listing_state",
)


def _nonempty_string(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SourceAuthorityError(f"{label} must be a non-empty string")
    return value


def _source_id_list(value: Any, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or not value:
        raise SourceAuthorityError(f"{label} must be a non-empty source-ID list")
    result = tuple(_nonempty_string(item, label=label) for item in value)
    if len(result) != len(set(result)):
        raise SourceAuthorityError(f"{label} contains duplicate source IDs")
    return result


def validate_metadata_state_records(states: Sequence[Mapping[str, Any]]) -> None:
    for index, state in enumerate(states):
        if not isinstance(state, Mapping):
            raise SourceAuthorityError(f"metadata state {index} is not an object")
        instrument = _nonempty_string(state.get("instrument"), label=f"metadata state {index} instrument")
        source_ids = set(_source_id_list(state.get("source_ids"), label=f"metadata state {index} source_ids"))
        _nonempty_string(
            state.get("derivation_rule_id"),
            label=f"metadata state {index} derivation_rule_id",
        )
        if state.get("contradiction") is not False:
            raise SourceAuthorityError(f"metadata state {index} is contradictory")

        required_fields = list(COMMON_STATE_FIELDS)
        if instrument.endswith("-SWAP"):
            required_fields.extend(SWAP_STATE_FIELDS)
        field_sources = state.get("field_source_ids")
        if not isinstance(field_sources, Mapping):
            raise SourceAuthorityError(f"metadata state {index} field_source_ids must be an object")
        for field in required_fields:
            if field not in state or state.get(field) in (None, ""):
                raise SourceAuthorityError(
                    f"metadata state {index} required field is missing: {field}"
                )
            ids = set(
                _source_id_list(
                    field_sources.get(field),
                    label=f"metadata state {index} field_source_ids.{field}",
                )
            )
            if not ids.issubset(source_ids):
                raise SourceAuthorityError(
                    f"metadata state {index} field provenance escapes source_ids: {field}"
                )

        boundary_sources = state.get("boundary_source_ids")
        if not isinstance(boundary_sources, Mapping):
            raise SourceAuthorityError(
                f"metadata state {index} boundary_source_ids must be an object"
            )
        for boundary in ("effective_from", "effective_to"):
            if boundary not in state or state.get(boundary) in (None, ""):
                raise SourceAuthorityError(
                    f"metadata state {index} interval boundary is missing: {boundary}"
                )
            ids = set(
                _source_id_list(
                    boundary_sources.get(boundary),
                    label=f"metadata state {index} boundary_source_ids.{boundary}",
                )
            )
            if not ids.issubset(source_ids):
                raise SourceAuthorityError(
                    f"metadata state {index} boundary provenance escapes source_ids: {boundary}"
                )


def validate_transition_proof_records(proofs: Sequence[Mapping[str, Any]]) -> None:
    for index, proof in enumerate(proofs):
        if not isinstance(proof, Mapping):
            raise SourceAuthorityError(f"transition proof {index} is not an object")
        for field in (
            "instrument",
            "window_start",
            "window_end_exclusive",
            "old_state_id",
            "new_state_id",
            "official_window_source_id",
            "old_lot",
            "new_lot",
            "old_min",
            "new_min",
            "transition_lot",
            "transition_min",
        ):
            _nonempty_string(proof.get(field), label=f"transition proof {index} {field}")
        old_sources = set(
            _source_id_list(proof.get("old_source_ids"), label=f"transition proof {index} old_source_ids")
        )
        new_sources = set(
            _source_id_list(proof.get("new_source_ids"), label=f"transition proof {index} new_source_ids")
        )
        official_window_source = str(proof["official_window_source_id"])
        unchanged = proof.get("unchanged_field_proof")
        if not isinstance(unchanged, Mapping):
            raise SourceAuthorityError(
                f"transition proof {index} unchanged_field_proof must be an object"
            )
        permitted = old_sources | new_sources | {official_window_source}
        for field in TRANSITION_UNCHANGED_FIELDS:
            ids = set(
                _source_id_list(
                    unchanged.get(field),
                    label=f"transition proof {index} unchanged_field_proof.{field}",
                )
            )
            if not ids.issubset(permitted):
                raise SourceAuthorityError(
                    f"transition proof {index} unchanged-field provenance is unbound: {field}"
                )
        cases = proof.get("boundary_cases")
        if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)) or not cases:
            raise SourceAuthorityError(f"transition proof {index} boundary cases are missing")
        if proof.get("status") != "PASS":
            raise SourceAuthorityError(f"transition proof {index} is not PASS")


def validate_coverage_records(rows: Sequence[Mapping[str, Any]]) -> None:
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise SourceAuthorityError(f"coverage row {index} is not an object")
        if row.get("required_fields_present") is not True:
            raise SourceAuthorityError(f"coverage row {index} lacks required-field proof")
        if row.get("modeled_timestamp_outside_authority") is not False:
            raise SourceAuthorityError(f"coverage row {index} permits an unauthorised timestamp")
        if row.get("source_coverage_status") != "PASS":
            raise SourceAuthorityError(f"coverage row {index} source coverage is not PASS")
        for field in (
            "overlap_count",
            "contradiction_count",
            "uncovered_duration_seconds",
        ):
            if type(row.get(field)) is not int or row[field] != 0:
                raise SourceAuthorityError(f"coverage row {index} has non-zero {field}")


def artifact_statistics(
    *,
    source_inventory: Mapping[str, Any],
    announcement_catalog: Mapping[str, Any],
    metadata_states: Sequence[Mapping[str, Any]],
    transition_proofs: Sequence[Mapping[str, Any]],
    coverage_matrix: Sequence[Mapping[str, Any]],
) -> dict[str, int]:
    sources = source_inventory.get("sources", [])
    pages = announcement_catalog.get("pages", [])
    items = announcement_catalog.get("items", [])
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
        raise SourceAuthorityError("source inventory sources must be a list")
    if not isinstance(pages, Sequence) or isinstance(pages, (str, bytes)):
        raise SourceAuthorityError("announcement catalog pages must be a list")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise SourceAuthorityError("announcement catalog items must be a list")
    return {
        "source_object_count": len(sources),
        "eligible_source_object_count": sum(
            isinstance(row, Mapping) and row.get("eligible") is True for row in sources
        ),
        "catalog_page_count": len(pages),
        "catalog_item_count": len(items),
        "metadata_state_count": len(metadata_states),
        "coverage_interval_count": len(coverage_matrix),
        "transition_proof_count": len(transition_proofs),
        "uncovered_interval_count": sum(
            isinstance(row, Mapping) and row.get("uncovered_duration_seconds", 0) != 0
            for row in coverage_matrix
        ),
        "uncovered_duration_seconds": sum(
            int(row.get("uncovered_duration_seconds", 0))
            for row in coverage_matrix
            if isinstance(row, Mapping)
            and type(row.get("uncovered_duration_seconds", 0)) is int
        ),
        "ambiguous_interval_count": sum(
            int(row.get("overlap_count", 0))
            for row in coverage_matrix
            if isinstance(row, Mapping) and type(row.get("overlap_count", 0)) is int
        ),
        "contradiction_count": sum(
            int(row.get("contradiction_count", 0))
            for row in coverage_matrix
            if isinstance(row, Mapping) and type(row.get("contradiction_count", 0)) is int
        ),
    }
