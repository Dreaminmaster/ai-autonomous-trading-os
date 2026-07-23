"""Physically separate read-only recomputation for C6A source authority.

This module deliberately imports no production gate, capture, decoder, or
packaging module.  It independently verifies exact-decimal transition math,
continuous coverage, query-inventory identity, retained source bytes, catalog
completeness, decision priority, and recursive manifest coverage.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import parse_qsl, urlparse


SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
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
    ("ETH-USDT-SWAP", "2024-04-18T06:00:00+00:00", "2024-04-18T08:00:00+00:00"),
    ("BTC-USDT-SWAP", "2024-04-25T06:00:00+00:00", "2024-04-25T08:00:00+00:00"),
    ("ETH-USDT-SWAP", "2025-01-09T06:00:00+00:00", "2025-01-09T10:00:00+00:00"),
    ("BTC-USDT-SWAP", "2025-01-22T06:00:00+00:00", "2025-01-22T08:00:00+00:00"),
}
FORBIDDEN_MARKERS = (
    "/api/v5/market/history-candles",
    "/api/v5/market/history-mark-price-candles",
    "/api/v5/public/funding-rate-history",
    "/api/v5/trade/",
    "/api/v5/account/",
    "/api/v5/asset/",
    "/api/v5/broker/",
)
PROHIBITED_QUERY_KEYS = {
    "apikey",
    "api_key",
    "secret",
    "passphrase",
    "signature",
    "sign",
    "token",
    "authorization",
}


def _canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
        "utf-8"
    )


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


def _safe_file(root: Path, relative: Any) -> tuple[Path | None, str | None]:
    if not isinstance(relative, str) or not relative:
        return None, "file path missing"
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        return None, f"path traversal: {relative}"
    if not path.is_file():
        return None, f"file missing: {relative}"
    return path, None


def recompute_transition(proof: Mapping[str, Any]) -> list[str]:
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
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    authority_start = _timestamp(AUTHORITY_START_TEXT)
    authority_end = _timestamp(AUTHORITY_END_TEXT)
    identity = {
        "BTC-USDT": ("SPOT", "BTC", "USDT", None, None),
        "ETH-USDT": ("SPOT", "ETH", "USDT", None, None),
        "BTC-USDT-SWAP": ("SWAP", "BTC", "USDT", "USDT", "BTC"),
        "ETH-USDT-SWAP": ("SWAP", "ETH", "USDT", "USDT", "ETH"),
    }
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
                expected = identity[instrument]
                observed = (
                    row.get("inst_type"),
                    row.get("base_ccy"),
                    row.get("quote_ccy"),
                    row.get("settle_ccy"),
                    row.get("ct_val_ccy"),
                )
                if observed != expected or row.get("listing_state") != "live":
                    errors.append(f"identity mismatch for {instrument}")
                if row.get("authority_mode") == "TRANSITION_SAFE_INTERSECTION":
                    key = (instrument, start.isoformat(), end.isoformat())
                    if key not in FROZEN_WINDOWS:
                        errors.append(f"unfrozen transition for {instrument}")
                for field in ("lot_sz", "min_sz", "tick_sz"):
                    _decimal(row[field])
                if instrument.endswith("-SWAP"):
                    _decimal(row["ct_val"])
                source_ids = row.get("source_ids")
                if not isinstance(source_ids, Sequence) or isinstance(source_ids, (str, bytes)) or not source_ids:
                    errors.append(f"source IDs missing for {instrument}")
                rows.append(
                    {
                        "instrument": instrument,
                        "state_id": row.get("state_id"),
                        "authority_mode": row.get("authority_mode"),
                        "interval_start": start.isoformat(),
                        "interval_end_exclusive": end.isoformat(),
                        "source_coverage_status": "PASS",
                        "overlap_count": 0,
                        "contradiction_count": 0,
                        "uncovered_duration_seconds": 0,
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


def verify_query_inventory(payload: Mapping[str, Any], *, expected_sha256: str) -> list[str]:
    errors: list[str] = []
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    if not SHA256_RE.fullmatch(expected_sha256) or digest != expected_sha256:
        errors.append("query inventory SHA-256 mismatch")
    if payload.get("authenticated") is not False or payload.get("economic_endpoints_forbidden") is not True:
        errors.append("query inventory does not explicitly forbid authenticated/economic access")
    if tuple(payload.get("instruments", ())) != INSTRUMENTS:
        errors.append("query inventory instrument scope mismatch")
    if payload.get("authority_start") != AUTHORITY_START_TEXT or payload.get(
        "authority_end_exclusive"
    ) != AUTHORITY_END_TEXT:
        errors.append("query inventory time boundary mismatch")
    requests = payload.get("requests")
    if not isinstance(requests, Sequence) or isinstance(requests, (str, bytes)) or not requests:
        return errors + ["query inventory requests missing"]
    seen: set[str] = set()
    for row in requests:
        if not isinstance(row, Mapping):
            errors.append("query inventory request is not an object")
            continue
        request_id = str(row.get("request_id", ""))
        url = str(row.get("url", ""))
        if not request_id or request_id in seen:
            errors.append("query inventory request ID missing or duplicated")
        seen.add(request_id)
        parsed = urlparse(url.replace("{page}", "1"))
        if parsed.scheme != "https" or not parsed.hostname:
            errors.append(f"query inventory URL is not HTTPS: {request_id}")
            continue
        query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        if query_keys & PROHIBITED_QUERY_KEYS:
            errors.append(f"query inventory credential parameter: {request_id}")
        if any(marker in parsed.path.lower() for marker in FORBIDDEN_MARKERS):
            errors.append(f"query inventory forbidden endpoint: {request_id}")
        if row.get("method") != "GET":
            errors.append(f"query inventory non-GET request: {request_id}")
    return errors


def verify_source_inventory(
    root: Path, source_inventory: Mapping[str, Any]
) -> tuple[set[str], list[str]]:
    errors: list[str] = []
    eligible_ids: set[str] = set()
    rows = source_inventory.get("sources")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return eligible_ids, ["source inventory sources missing"]
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            errors.append("source inventory row is not an object")
            continue
        source_id = str(row.get("source_id", ""))
        if not source_id or source_id in seen:
            errors.append("source inventory ID missing or duplicated")
            continue
        seen.add(source_id)
        official = urlparse(str(row.get("canonical_official_url", "")))
        if official.scheme != "https" or not official.hostname or not (
            official.hostname == "okx.com" or official.hostname.endswith(".okx.com")
        ):
            errors.append(f"source canonical URL is not official OKX: {source_id}")
        retrieval = urlparse(str(row.get("retrieval_url", "")))
        if retrieval.scheme != "https" or not retrieval.hostname:
            errors.append(f"source retrieval URL is not HTTPS: {source_id}")
        for prefix in ("raw", "decoded"):
            path, error = _safe_file(root, row.get(f"{prefix}_path"))
            if error:
                errors.append(f"{source_id} {error}")
                continue
            assert path is not None
            data = path.read_bytes()
            size = row.get(f"{prefix}_size")
            digest = str(row.get(f"{prefix}_sha256", ""))
            if type(size) is not int or size != len(data):
                errors.append(f"{source_id} {prefix} size mismatch")
            if not SHA256_RE.fullmatch(digest) or hashlib.sha256(data).hexdigest() != digest:
                errors.append(f"{source_id} {prefix} SHA-256 mismatch")
        eligible = row.get("eligible")
        rejection = row.get("rejection_reason")
        if eligible is True and rejection in (None, ""):
            eligible_ids.add(source_id)
        elif eligible is False and isinstance(rejection, str) and rejection:
            pass
        else:
            errors.append(f"source eligibility contract invalid: {source_id}")
    return eligible_ids, errors


def verify_announcement_catalog(catalog: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    pages = catalog.get("pages")
    items = catalog.get("items")
    proof = catalog.get("terminal_page_proof")
    if not isinstance(pages, Sequence) or isinstance(pages, (str, bytes)) or not pages:
        return ["announcement catalog pages missing"]
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        errors.append("announcement catalog items missing")
        items = []
    page_numbers: list[int] = []
    terminal_values: set[int] = set()
    for page in pages:
        if not isinstance(page, Mapping):
            errors.append("announcement catalog page is not an object")
            continue
        number = page.get("page_number")
        terminal = page.get("declared_terminal_page")
        if type(number) is not int or type(terminal) is not int:
            errors.append("announcement catalog page numbers are invalid")
            continue
        page_numbers.append(number)
        terminal_values.add(terminal)
    if len(terminal_values) != 1:
        errors.append("announcement catalog terminal page is inconsistent")
        terminal = None
    else:
        terminal = next(iter(terminal_values))
    if terminal is not None and sorted(page_numbers) != list(range(1, terminal + 1)):
        errors.append("announcement catalog pages are not contiguous from one to terminal")
    if not isinstance(proof, Mapping) or proof.get("status") != "PASS" or proof.get(
        "terminal_page"
    ) != terminal:
        errors.append("announcement catalog terminal-page proof mismatch")
    urls: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            errors.append("announcement catalog item is not an object")
            continue
        url = str(item.get("canonical_url", ""))
        if not url or url in urls:
            errors.append("announcement catalog item URL missing or duplicated")
        urls.add(url)
        if item.get("page_number") not in page_numbers:
            errors.append(f"announcement item lacks valid page provenance: {url}")
    return errors


def verify_manifest(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    entries = manifest.get("files")
    if not isinstance(entries, Sequence) or isinstance(entries, (str, bytes)):
        return ["manifest files missing"]
    seen: set[str] = set()
    for row in entries:
        if not isinstance(row, Mapping):
            errors.append("manifest row is not an object")
            continue
        relative = str(row.get("path", ""))
        if not relative or relative in seen:
            errors.append("manifest path missing or duplicated")
            continue
        seen.add(relative)
        path, error = _safe_file(root, relative)
        if error:
            errors.append(f"manifest {error}")
            continue
        assert path is not None
        data = path.read_bytes()
        if row.get("size") != len(data):
            errors.append(f"manifest size mismatch: {relative}")
        digest = hashlib.sha256(data).hexdigest()
        if row.get("sha256") != digest or not SHA256_RE.fullmatch(str(row.get("sha256", ""))):
            errors.append(f"manifest SHA-256 mismatch: {relative}")
    if manifest.get("file_count") != len(seen):
        errors.append("manifest file_count mismatch")
    return errors


def verify_manifest_complete(
    root: Path, manifest: Mapping[str, Any], *, excluded_paths: Sequence[str] = ("manifest.json",)
) -> list[str]:
    errors = verify_manifest(root, manifest)
    expected = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() not in set(excluded_paths)
    }
    observed = {
        str(row.get("path"))
        for row in manifest.get("files", [])
        if isinstance(row, Mapping)
    }
    if observed != expected:
        errors.append(
            f"manifest recursive coverage mismatch: missing={sorted(expected-observed)} extra={sorted(observed-expected)}"
        )
    return errors


def choose_primary_failure(failures: Sequence[str]) -> str | None:
    unique = set(failures)
    unknown = unique - set(FAILURE_PRIORITY)
    if unknown:
        raise ValueError(f"unknown failure code: {sorted(unknown)}")
    return next((code for code in FAILURE_PRIORITY if code in unique), None)


def review_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Compatibility in-memory review used by focused unit tests."""

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


def review_package(
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
    """Independently review every retained input and canonical derived object."""

    errors: list[str] = []
    expected_query_sha = str(gate_result.get("query_inventory_sha256", ""))
    errors.extend(verify_query_inventory(query_inventory, expected_sha256=expected_query_sha))
    eligible_ids, source_errors = verify_source_inventory(root, source_inventory)
    errors.extend(source_errors)
    errors.extend(verify_announcement_catalog(announcement_catalog))

    states = list(metadata_states)
    recomputed_coverage, coverage_errors = recompute_coverage(states)
    errors.extend(coverage_errors)
    if list(coverage_matrix) != recomputed_coverage:
        errors.append("coverage matrix does not match independent recomputation")
    for state in states:
        source_ids = state.get("source_ids") if isinstance(state, Mapping) else None
        if isinstance(source_ids, Sequence) and not isinstance(source_ids, (str, bytes)):
            missing = {str(value) for value in source_ids} - eligible_ids
            if missing:
                errors.append(f"metadata state references ineligible or missing sources: {sorted(missing)}")

    proofs = list(transition_proofs)
    if len(proofs) != len(FROZEN_WINDOWS):
        errors.append("transition proof set is incomplete")
    for proof in proofs:
        if isinstance(proof, Mapping):
            errors.extend(recompute_transition(proof))
        else:
            errors.append("transition proof is not an object")

    recorded = [str(item) for item in failures]
    try:
        expected_primary = choose_primary_failure(recorded)
    except ValueError as exc:
        errors.append(str(exc))
        expected_primary = "FAIL_INDEPENDENT_REVIEW_MISMATCH"
    expected_status = "PASS" if expected_primary is None else "FAIL"
    expected_result = "PASS" if expected_primary is None else expected_primary
    if gate_result.get("status") != expected_status or gate_result.get("result") != expected_result:
        errors.append("gate result does not match frozen failure priority")
    if gate_result.get("authoritative") is not False:
        errors.append("preliminary gate result improperly claims authority")
    if gate_result.get("implementation_authorized") is not False or gate_result.get(
        "economic_data_access_authorized"
    ) is not False:
        errors.append("gate result improperly authorizes downstream work")
    if not COMMIT_RE.fullmatch(str(gate_result.get("source_commit_sha", ""))):
        errors.append("gate source commit SHA is invalid")

    errors.extend(
        verify_manifest_complete(
            root,
            preliminary_manifest,
            excluded_paths=("manifest.json", "independent_review.json"),
        )
    )
    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GATE_INDEPENDENT_PACKAGE_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "query_inventory_sha256": hashlib.sha256(_canonical_json_bytes(query_inventory)).hexdigest(),
        "eligible_source_count": len(eligible_ids),
        "coverage_row_count": len(recomputed_coverage),
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
