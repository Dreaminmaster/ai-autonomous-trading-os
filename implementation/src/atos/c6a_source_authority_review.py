"""Physically separate read-only recomputation for C6A source authority.

This module deliberately does not import ``atos.c6a_source_authority``.  It
recomputes exact-decimal transition arithmetic, interval coverage, hashes, and
the final fail-closed decision from plain JSON-compatible inputs.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import Any, Mapping, Sequence


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
INSTRUMENTS = (
    "BTC-USDT",
    "ETH-USDT",
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
)
AUTHORITY_START_TEXT = "2023-06-05T00:00:00Z"
AUTHORITY_END_TEXT = "2025-12-29T00:00:00Z"
FAILURE_PRIORITY = (
    "FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED",
    "FAIL_FORBIDDEN_DATA_ACCESS",
    "FAIL_SOURCE_BYTES_MISSING",
    "FAIL_SOURCE_HASH_MISMATCH",
    "FAIL_SOURCE_NOT_OFFICIAL_OKX",
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
FROZEN_WINDOWS = {
    (
        "ETH-USDT-SWAP",
        "2024-04-18T06:00:00+00:00",
        "2024-04-18T08:00:00+00:00",
    ),
    (
        "BTC-USDT-SWAP",
        "2024-04-25T06:00:00+00:00",
        "2024-04-25T08:00:00+00:00",
    ),
    (
        "ETH-USDT-SWAP",
        "2025-01-09T06:00:00+00:00",
        "2025-01-09T10:00:00+00:00",
    ),
    (
        "BTC-USDT-SWAP",
        "2025-01-22T06:00:00+00:00",
        "2025-01-22T08:00:00+00:00",
    ),
}


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty string")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    result = datetime.fromisoformat(text)
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be explicit UTC")
    return result.astimezone(timezone.utc)


def _decimal(value: Any, *, positive: bool = True) -> Decimal:
    if not isinstance(value, str) or not value or value != value.strip() or "e" in value.lower():
        raise ValueError("exact decimal string required")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("invalid decimal") from exc
    if not result.is_finite() or result < 0 or (positive and result <= 0):
        raise ValueError("invalid decimal range")
    return result


def _multiple(quantity: Decimal, increment: Decimal) -> bool:
    return quantity % increment == 0


def _valid(quantity: Decimal, lot: Decimal, minimum: Decimal) -> bool:
    return quantity >= 0 and _multiple(quantity, lot) and (quantity == 0 or quantity >= minimum)


def recompute_transition(proof: Mapping[str, Any]) -> list[str]:
    """Recompute the mathematical intersection without production imports."""

    errors: list[str] = []
    try:
        instrument = str(proof["instrument"])
        start = _timestamp(proof["window_start"]).isoformat()
        end = _timestamp(proof["window_end_exclusive"]).isoformat()
        if (instrument, start, end) not in FROZEN_WINDOWS:
            errors.append("transition window is not frozen")
        old_lot = _decimal(proof["old_lot"])
        new_lot = _decimal(proof["new_lot"])
        old_min = _decimal(proof["old_min"])
        new_min = _decimal(proof["new_min"])
        reported_lot = _decimal(proof["transition_lot"])
        reported_min = _decimal(proof["transition_min"])
        coarse = max(old_lot, new_lot)
        fine = min(old_lot, new_lot)
        ratio = coarse / fine
        if ratio != ratio.to_integral_value():
            errors.append("transition increments are not nested")
        expected_min = (max(old_min, new_min) / coarse).to_integral_value(
            rounding=ROUND_CEILING
        ) * coarse
        if reported_lot != coarse:
            errors.append("transition lot mismatch")
        if reported_min != expected_min:
            errors.append("transition minimum mismatch")
        if not _valid(reported_min, old_lot, old_min):
            errors.append("transition minimum invalid under old state")
        if not _valid(reported_min, new_lot, new_min):
            errors.append("transition minimum invalid under new state")
        cases = proof.get("boundary_cases")
        if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)) or not cases:
            errors.append("transition boundary cases missing")
        else:
            for row in cases:
                if not isinstance(row, Mapping):
                    errors.append("transition boundary case is not an object")
                    continue
                quantity = _decimal(row.get("quantity"), positive=False)
                admitted = _valid(quantity, reported_lot, reported_min)
                valid_old = _valid(quantity, old_lot, old_min)
                valid_new = _valid(quantity, new_lot, new_min)
                if row.get("admitted_by_intersection") is not admitted:
                    errors.append("transition boundary admission mismatch")
                if row.get("valid_old") is not valid_old or row.get("valid_new") is not valid_new:
                    errors.append("transition boundary state mismatch")
                if admitted and not (valid_old and valid_new):
                    errors.append("intersection admits an invalid quantity")
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"transition proof malformed: {exc}")
    return errors


def recompute_coverage(states: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Independently require one exact state at every bounded timestamp."""

    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    authority_start = _timestamp(AUTHORITY_START_TEXT)
    authority_end = _timestamp(AUTHORITY_END_TEXT)
    for instrument in INSTRUMENTS:
        selected = sorted(
            (row for row in states if row.get("instrument") == instrument),
            key=lambda row: str(row.get("effective_from", "")),
        )
        if not selected:
            errors.append(f"missing states for {instrument}")
            continue
        previous_end = authority_start
        for row in selected:
            try:
                start = _timestamp(row["effective_from"])
                open_ended = row.get("open_ended") is True
                end = authority_end if open_ended else _timestamp(row["effective_to"])
                end = min(end, authority_end)
                if start < previous_end:
                    errors.append(f"overlap for {instrument}")
                elif start > previous_end:
                    errors.append(f"gap for {instrument}")
                if end <= start:
                    errors.append(f"invalid interval for {instrument}")
                if row.get("contradiction") is not False:
                    errors.append(f"contradictory state for {instrument}")
                if row.get("authority_mode") == "TRANSITION_SAFE_INTERSECTION":
                    key = (instrument, start.isoformat(), end.isoformat())
                    if key not in FROZEN_WINDOWS:
                        errors.append(f"unfrozen transition for {instrument}")
                for field in ("lot_sz", "min_sz", "tick_sz"):
                    _decimal(row[field])
                if instrument.endswith("-SWAP"):
                    _decimal(row["ct_val"])
                    for field in ("settle_ccy", "ct_val_ccy"):
                        if not isinstance(row.get(field), str) or not row[field]:
                            errors.append(f"missing {field} for {instrument}")
                rows.append(
                    {
                        "instrument": instrument,
                        "state_id": row.get("state_id"),
                        "interval_start": start.isoformat(),
                        "interval_end_exclusive": end.isoformat(),
                    }
                )
                previous_end = end
                if previous_end == authority_end:
                    break
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"malformed state for {instrument}: {exc}")
        if previous_end != authority_end:
            errors.append(f"incomplete authority coverage for {instrument}")
    return rows, errors


def verify_manifest(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    """Verify path safety, size, and SHA-256 for every indexed artifact file."""

    errors: list[str] = []
    entries = manifest.get("files")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return ["manifest files missing"]
    seen: set[str] = set()
    resolved_root = root.resolve()
    for row in entries:
        if not isinstance(row, Mapping):
            errors.append("manifest row is not an object")
            continue
        relative = str(row.get("path", ""))
        if not relative or relative in seen:
            errors.append("manifest path missing or duplicated")
            continue
        seen.add(relative)
        path = (root / relative).resolve()
        if not path.is_relative_to(resolved_root):
            errors.append(f"manifest path traversal: {relative}")
            continue
        if not path.is_file():
            errors.append(f"manifest file missing: {relative}")
            continue
        data = path.read_bytes()
        if row.get("size") != len(data):
            errors.append(f"manifest size mismatch: {relative}")
        digest = hashlib.sha256(data).hexdigest()
        if row.get("sha256") != digest or not SHA256_RE.fullmatch(str(row.get("sha256", ""))):
            errors.append(f"manifest SHA-256 mismatch: {relative}")
    return errors


def choose_primary_failure(failures: Sequence[str]) -> str | None:
    unique = set(failures)
    unknown = unique - set(FAILURE_PRIORITY)
    if unknown:
        raise ValueError(f"unknown failure code: {sorted(unknown)}")
    return next((code for code in FAILURE_PRIORITY if code in unique), None)


def review_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Review a plain in-memory gate package and return a deterministic report."""

    errors: list[str] = []
    states = payload.get("metadata_states")
    if not isinstance(states, Sequence) or isinstance(states, (str, bytes)):
        errors.append("metadata_states missing")
        states = []
    coverage_rows, coverage_errors = recompute_coverage(states)
    errors.extend(coverage_errors)

    proofs = payload.get("transition_proofs")
    if not isinstance(proofs, Sequence) or isinstance(proofs, (str, bytes)):
        errors.append("transition_proofs missing")
        proofs = []
    for proof in proofs:
        if isinstance(proof, Mapping):
            errors.extend(recompute_transition(proof))
        else:
            errors.append("transition proof is not an object")

    recorded_failures = payload.get("failures", [])
    if not isinstance(recorded_failures, Sequence) or isinstance(recorded_failures, (str, bytes)):
        errors.append("failures is not a list")
        recorded_failures = []
    try:
        expected_primary = choose_primary_failure([str(item) for item in recorded_failures])
    except ValueError as exc:
        errors.append(str(exc))
        expected_primary = "FAIL_INDEPENDENT_REVIEW_MISMATCH"

    gate = payload.get("gate_result")
    if not isinstance(gate, Mapping):
        errors.append("gate_result missing")
        gate = {}
    expected_status = "PASS" if expected_primary is None else "FAIL"
    expected_result = "PASS" if expected_primary is None else expected_primary
    if gate.get("status") != expected_status or gate.get("result") != expected_result:
        errors.append("gate result does not match frozen failure priority")
    if gate.get("implementation_authorized") is not False:
        errors.append("gate result improperly authorizes implementation")
    if gate.get("economic_data_access_authorized") is not False:
        errors.append("gate result improperly authorizes economic access")

    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GATE_INDEPENDENT_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "coverage_row_count": len(coverage_rows),
        "transition_proof_count": len(proofs),
        "errors": errors,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }


def load_json(path: Path) -> Mapping[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON root must be an object: {path}")
    return value
