"""Independent reconciliation of retained C6A attempt diagnostics and scope.

This module derives transport/parser failure codes from retained diagnostic
fields, verifies that the producer recorded the same code, combines them with
the physically separate package review, and separately invokes a reviewer that
recomputes GLOBAL source scope from retained bytes rather than trusting the
production verdict.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import atos.c6a_source_authority_independent as independent
from atos.c6a_source_authority_scope_independent import review_global_scope


FAILURE_PRIORITY = (
    "FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED",
    "FAIL_FORBIDDEN_DATA_ACCESS",
    "FAIL_SOURCE_BYTES_MISSING",
    "FAIL_SOURCE_HASH_MISMATCH",
    "FAIL_SOURCE_NOT_OFFICIAL_OKX",
    "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT",
    "FAIL_ARCHIVE_DECODING_OR_PROVENANCE",
    "FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE",
    "FAIL_REQUIRED_FIELD_MISSING",
    "FAIL_INTERVAL_BOUNDARY_UNPROVEN",
    "FAIL_UNCOVERED_INTERVAL",
    "FAIL_AMBIGUOUS_OR_CONTRADICTORY_STATE",
    "FAIL_UNSUPPORTED_BACKWARD_PROJECTION",
    "FAIL_TRANSITION_WINDOW_UNPROVEN",
    "FAIL_TRANSITION_FIELDS_CHANGED",
    "FAIL_TRANSITION_INCREMENT_NOT_NESTED",
    "FAIL_TRANSITION_INTERSECTION_INVALID",
    "FAIL_NEW_UNFROZEN_TRANSITION",
    "FAIL_MANIFEST_INCOMPLETE",
    "FAIL_INDEPENDENT_REVIEW_MISMATCH",
)

_RECONCILED_ERROR_PREFIX = "recorded failure set mismatch:"
_RECONCILED_PRIMARY_ERROR = "recomputed primary failure does not match recorded primary failure"
_STRUCTURED_CATALOG_STAGES = {"announcement_catalog_deduplication"}
_SCOPE_MARKERS = (
    "fail_source_authority_scope_drift",
    "source authority scope drift",
    "regional locale path",
    "regional path",
    "global category evidence",
)


def choose_primary_failure(failures: Sequence[str]) -> str | None:
    unknown = set(failures) - set(FAILURE_PRIORITY)
    if unknown:
        raise ValueError(f"unknown failure code: {sorted(unknown)}")
    values = set(failures)
    return next((code for code in FAILURE_PRIORITY if code in values), None)


def _derive_event_failure(event: Mapping[str, Any]) -> str:
    message = str(event.get("error", "")).casefold()
    stage = str(event.get("stage", ""))
    request_kind = str(event.get("request_kind", ""))
    if any(marker in message for marker in _SCOPE_MARKERS):
        return "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
    if "forbidden" in message or "credential" in message:
        return "FAIL_FORBIDDEN_DATA_ACCESS"
    if request_kind == "archive_lookup" or stage in {"archive_index", "archive_memento"}:
        return "FAIL_ARCHIVE_DECODING_OR_PROVENANCE"
    if (
        request_kind == "announcement_catalog"
        or stage == "announcement_catalog"
        or stage in _STRUCTURED_CATALOG_STAGES
    ):
        return "FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE"
    if request_kind == "announcement_article" or stage in {
        "known_transition_notice",
        "selected_announcement_article",
    }:
        return "FAIL_TRANSITION_WINDOW_UNPROVEN"
    return "FAIL_REQUIRED_FIELD_MISSING"


def review_attempt_diagnostics(root: Path) -> dict[str, Any]:
    """Independently derive failure codes from the retained attempt log."""

    path = root / "diagnostics" / "attempt_log.json"
    if not path.exists():
        return {
            "schema_version": 1,
            "stage": "C6A_SOURCE_AUTHORITY_ATTEMPT_DIAGNOSTICS_REVIEW",
            "status": "PASS",
            "log_present": False,
            "event_count": 0,
            "recomputed_failures": [],
            "errors": [],
            "implementation_authorized": False,
            "economic_data_access_authorized": False,
            "live_state": "LIVE_FORBIDDEN",
        }

    errors: list[str] = []
    failures: set[str] = set()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {
            "schema_version": 1,
            "stage": "C6A_SOURCE_AUTHORITY_ATTEMPT_DIAGNOSTICS_REVIEW",
            "status": "FAIL",
            "log_present": True,
            "event_count": 0,
            "recomputed_failures": [],
            "errors": [f"attempt log is unreadable: {exc}"],
            "implementation_authorized": False,
            "economic_data_access_authorized": False,
            "live_state": "LIVE_FORBIDDEN",
        }

    events = payload.get("events") if isinstance(payload, Mapping) else None
    if not isinstance(events, Sequence) or isinstance(events, (str, bytes)):
        events = []
        errors.append("attempt log events missing")

    for index, event in enumerate(events):
        if not isinstance(event, Mapping):
            errors.append(f"attempt event {index} is not an object")
            continue
        stage = str(event.get("stage", ""))
        request_kind = str(event.get("request_kind", ""))
        derived = _derive_event_failure(event)
        failures.add(derived)
        recorded = str(event.get("failure_code", ""))
        if recorded != derived:
            errors.append(
                f"attempt event {index} failure mismatch: recorded={recorded!r} derived={derived!r}"
            )
        if not stage:
            errors.append(f"attempt event {index} lacks stage")
        if stage in _STRUCTURED_CATALOG_STAGES:
            duplicates = event.get("duplicate_urls")
            if not isinstance(duplicates, Sequence) or isinstance(duplicates, (str, bytes)) or not duplicates:
                errors.append(f"attempt event {index} lacks duplicate URL evidence")
        else:
            if not request_kind:
                errors.append(f"attempt event {index} lacks request_kind")
            if not str(event.get("error_type", "")) or not str(event.get("error", "")):
                errors.append(f"attempt event {index} lacks retained error identity")

    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_ATTEMPT_DIAGNOSTICS_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "log_present": True,
        "event_count": len(events),
        "recomputed_failures": sorted(failures),
        "errors": errors,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }


def review_package_with_attempt_diagnostics(
    root: Path,
    *,
    query_inventory: Mapping[str, Any],
    source_inventory: Mapping[str, Any],
    announcement_catalog: Mapping[str, Any],
    metadata_states: Sequence[Mapping[str, Any]],
    transition_proofs: Sequence[Mapping[str, Any]],
    coverage_matrix: Sequence[Mapping[str, Any]],
    failures: Sequence[str],
    gate_result: Mapping[str, Any],
    preliminary_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    """Run base review, diagnostic review, and independent GLOBAL scope review."""

    result = dict(
        independent.review_package(
            root,
            query_inventory=query_inventory,
            source_inventory=source_inventory,
            announcement_catalog=announcement_catalog,
            metadata_states=metadata_states,
            transition_proofs=transition_proofs,
            coverage_matrix=coverage_matrix,
            failures=failures,
            gate_result=gate_result,
            preliminary_manifest=preliminary_manifest,
        )
    )
    attempt_review = review_attempt_diagnostics(root)
    scope_review = review_global_scope(
        root,
        query_inventory=query_inventory,
        source_inventory=source_inventory,
        announcement_catalog=announcement_catalog,
    )
    result["attempt_diagnostics_review"] = attempt_review
    result["source_scope_review"] = scope_review

    errors = [
        str(error)
        for error in result.get("errors", [])
        if not str(error).startswith(_RECONCILED_ERROR_PREFIX)
        and str(error) != _RECONCILED_PRIMARY_ERROR
    ]
    errors.extend(str(error) for error in attempt_review.get("errors", []))
    errors.extend(str(error) for error in scope_review.get("errors", []))

    recorded = {str(code) for code in failures}
    recomputed = {str(code) for code in result.get("recomputed_failures", [])}
    recomputed.update(str(code) for code in attempt_review.get("recomputed_failures", []))
    recomputed.update(str(code) for code in scope_review.get("recomputed_failures", []))

    try:
        recorded_primary = choose_primary_failure(tuple(recorded))
        recomputed_primary = choose_primary_failure(tuple(recomputed))
    except ValueError as exc:
        errors.append(str(exc))
        recorded_primary = "FAIL_INDEPENDENT_REVIEW_MISMATCH"
        recomputed_primary = "FAIL_INDEPENDENT_REVIEW_MISMATCH"

    if recorded != recomputed:
        errors.append(
            f"recorded failure set mismatch: recorded={sorted(recorded)} recomputed={sorted(recomputed)}"
        )
    if recorded_primary != recomputed_primary:
        errors.append(_RECONCILED_PRIMARY_ERROR)

    result.update(
        {
            "status": "PASS" if not errors else "FAIL",
            "gate_status_recomputed": "PASS" if recomputed_primary is None else "FAIL",
            "gate_result_recomputed": "PASS" if recomputed_primary is None else recomputed_primary,
            "recorded_failures": sorted(recorded),
            "recomputed_failures": sorted(recomputed),
            "errors": errors,
            "implementation_authorized": False,
            "economic_data_access_authorized": False,
            "live_state": "LIVE_FORBIDDEN",
        }
    )
    return result
