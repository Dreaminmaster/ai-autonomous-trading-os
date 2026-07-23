"""Physically separate final reviewer for a C6A source-authority package.

This module intentionally imports no production gate, capture, parser, schema,
or package code.  It recomputes failure codes from retained plain objects and
distinguishes an expected gate FAIL from an independent-review mismatch.
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


DESIGN_AUTHORITY_SHA = "26a7604c34c610562643d7a732d35b39df84c94f"
STAGE = "C6A_SOURCE_AUTHORITY_GATE"
AUTHORITY_START_TEXT = "2023-06-05T00:00:00Z"
AUTHORITY_END_TEXT = "2025-12-29T00:00:00Z"
INSTRUMENTS = (
    "BTC-USDT",
    "ETH-USDT",
    "BTC-USDT-SWAP",
    "ETH-USDT-SWAP",
)
IDENTITIES = {
    "BTC-USDT": ("SPOT", "BTC", "USDT", None, None),
    "ETH-USDT": ("SPOT", "ETH", "USDT", None, None),
    "BTC-USDT-SWAP": ("SWAP", "BTC", "USDT", "USDT", "BTC"),
    "ETH-USDT-SWAP": ("SWAP", "ETH", "USDT", "USDT", "ETH"),
}
FROZEN_WINDOWS = {
    ("ETH-USDT-SWAP", "2024-04-18T06:00:00+00:00", "2024-04-18T08:00:00+00:00"),
    ("BTC-USDT-SWAP", "2024-04-25T06:00:00+00:00", "2024-04-25T08:00:00+00:00"),
    ("ETH-USDT-SWAP", "2025-01-09T06:00:00+00:00", "2025-01-09T10:00:00+00:00"),
    ("BTC-USDT-SWAP", "2025-01-22T06:00:00+00:00", "2025-01-22T08:00:00+00:00"),
}
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
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


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


def _valid(quantity: Decimal, lot: Decimal, minimum: Decimal) -> bool:
    return quantity >= 0 and quantity % lot == 0 and (quantity == 0 or quantity >= minimum)


def _safe_file(root: Path, relative: Any) -> tuple[Path | None, str | None]:
    if not isinstance(relative, str) or not relative:
        return None, "file path missing"
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        return None, f"path traversal: {relative}"
    if not path.is_file():
        return None, f"file missing: {relative}"
    return path, None


def choose_primary_failure(failures: Sequence[str]) -> str | None:
    unknown = set(failures) - set(FAILURE_PRIORITY)
    if unknown:
        raise ValueError(f"unknown failure code: {sorted(unknown)}")
    return next((code for code in FAILURE_PRIORITY if code in set(failures)), None)


def verify_manifest(root: Path, manifest: Mapping[str, Any]) -> list[str]:
    diagnostics: list[str] = []
    rows = manifest.get("files")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ["manifest files missing"]
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            diagnostics.append("manifest row is not an object")
            continue
        relative = str(row.get("path", ""))
        if not relative or relative in seen:
            diagnostics.append("manifest path missing or duplicated")
            continue
        seen.add(relative)
        path, error = _safe_file(root, relative)
        if error:
            diagnostics.append(f"manifest {error}")
            continue
        assert path is not None
        data = path.read_bytes()
        if row.get("size") != len(data):
            diagnostics.append(f"manifest size mismatch: {relative}")
        digest = hashlib.sha256(data).hexdigest()
        if row.get("sha256") != digest or not SHA256_RE.fullmatch(str(row.get("sha256", ""))):
            diagnostics.append(f"manifest SHA-256 mismatch: {relative}")
    if manifest.get("file_count") != len(seen):
        diagnostics.append("manifest file_count mismatch")
    return diagnostics


def verify_manifest_complete(
    root: Path,
    manifest: Mapping[str, Any],
    *,
    excluded_paths: Sequence[str] = ("manifest.json",),
) -> list[str]:
    diagnostics = verify_manifest(root, manifest)
    excluded = set(excluded_paths)
    expected = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() not in excluded
    }
    observed = {
        str(row.get("path"))
        for row in manifest.get("files", [])
        if isinstance(row, Mapping)
    }
    if observed != expected:
        diagnostics.append(
            f"manifest recursive coverage mismatch: missing={sorted(expected-observed)} extra={sorted(observed-expected)}"
        )
    return diagnostics


def _query_failures(payload: Mapping[str, Any], expected_sha256: str) -> tuple[set[str], list[str]]:
    failures: set[str] = set()
    diagnostics: list[str] = []
    digest = hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()
    if digest != expected_sha256 or not SHA256_RE.fullmatch(expected_sha256):
        failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
        diagnostics.append("query inventory SHA-256 mismatch")
    if payload.get("schema_version") != 1 or payload.get("stage") != STAGE:
        failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
    if payload.get("design_authority_sha") != DESIGN_AUTHORITY_SHA:
        failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
    if payload.get("authenticated") is not False or payload.get("economic_endpoints_forbidden") is not True:
        failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
    if tuple(payload.get("instruments", ())) != INSTRUMENTS:
        failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
    if payload.get("authority_start") != AUTHORITY_START_TEXT or payload.get(
        "authority_end_exclusive"
    ) != AUTHORITY_END_TEXT:
        failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
    requests = payload.get("requests")
    if not isinstance(requests, Sequence) or isinstance(requests, (str, bytes)) or not requests:
        failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
        return failures, diagnostics + ["query inventory requests missing"]
    seen: set[str] = set()
    for row in requests:
        if not isinstance(row, Mapping):
            failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
            continue
        request_id = str(row.get("request_id", ""))
        url = str(row.get("url", ""))
        if not request_id or request_id in seen or row.get("method") != "GET":
            failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
        seen.add(request_id)
        parsed = urlparse(url.replace("{page}", "1"))
        query_keys = {key.lower() for key, _ in parse_qsl(parsed.query, keep_blank_values=True)}
        if parsed.scheme != "https" or not parsed.hostname:
            failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
        if query_keys & PROHIBITED_QUERY_KEYS or any(
            marker in parsed.path.lower() for marker in FORBIDDEN_MARKERS
        ):
            failures.add("FAIL_FORBIDDEN_DATA_ACCESS")
        if row.get("request_kind") == "archive_lookup" and "collapse=" in url:
            failures.add("FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED")
    return failures, diagnostics


def _source_failures(
    root: Path, source_inventory: Mapping[str, Any]
) -> tuple[set[str], set[str], list[str]]:
    failures: set[str] = set()
    eligible_ids: set[str] = set()
    diagnostics: list[str] = []
    rows = source_inventory.get("sources")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return {"FAIL_REQUIRED_FIELD_MISSING"}, eligible_ids, ["source inventory sources missing"]
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            failures.add("FAIL_REQUIRED_FIELD_MISSING")
            continue
        source_id = str(row.get("source_id", ""))
        if not source_id or source_id in seen:
            failures.add("FAIL_REQUIRED_FIELD_MISSING")
            continue
        seen.add(source_id)
        official = urlparse(str(row.get("canonical_official_url", "")))
        if official.scheme != "https" or not official.hostname or not (
            official.hostname == "okx.com" or official.hostname.endswith(".okx.com")
        ):
            failures.add("FAIL_SOURCE_NOT_OFFICIAL_OKX")
        retrieval = urlparse(str(row.get("retrieval_url", "")))
        if retrieval.scheme != "https" or not retrieval.hostname:
            failures.add("FAIL_ARCHIVE_DECODING_OR_PROVENANCE")
        if not isinstance(row.get("parser_version"), str) or not row.get("parser_version"):
            failures.add("FAIL_ARCHIVE_DECODING_OR_PROVENANCE")
        for prefix in ("raw", "decoded"):
            path, error = _safe_file(root, row.get(f"{prefix}_path"))
            if error:
                failures.add("FAIL_SOURCE_BYTES_MISSING")
                diagnostics.append(f"{source_id} {error}")
                continue
            assert path is not None
            data = path.read_bytes()
            if row.get(f"{prefix}_size") != len(data):
                failures.add("FAIL_SOURCE_HASH_MISMATCH")
            digest = str(row.get(f"{prefix}_sha256", ""))
            if not SHA256_RE.fullmatch(digest) or hashlib.sha256(data).hexdigest() != digest:
                failures.add("FAIL_SOURCE_HASH_MISMATCH")
        if row.get("eligible") is True and row.get("rejection_reason") in (None, ""):
            eligible_ids.add(source_id)
        elif row.get("eligible") is False and isinstance(row.get("rejection_reason"), str) and row.get(
            "rejection_reason"
        ):
            pass
        else:
            failures.add("FAIL_ARCHIVE_DECODING_OR_PROVENANCE")
    return failures, eligible_ids, diagnostics


def _catalog_failures(catalog: Mapping[str, Any]) -> tuple[set[str], list[str]]:
    failures: set[str] = set()
    diagnostics: list[str] = []
    pages = catalog.get("pages")
    items = catalog.get("items")
    proof = catalog.get("terminal_page_proof")
    if not isinstance(pages, Sequence) or isinstance(pages, (str, bytes)) or not pages:
        return {"FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE"}, ["announcement catalog pages missing"]
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        failures.add("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")
        items = []
    numbers: list[int] = []
    terminals: set[int] = set()
    for page in pages:
        if not isinstance(page, Mapping):
            failures.add("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")
            continue
        number = page.get("page_number")
        terminal = page.get("declared_terminal_page")
        if type(number) is not int or type(terminal) is not int:
            failures.add("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")
            continue
        numbers.append(number)
        terminals.add(terminal)
        for field in ("requested_url", "retrieval_timestamp", "status_code", "raw_path", "raw_sha256"):
            if field not in page:
                failures.add("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")
    terminal = next(iter(terminals)) if len(terminals) == 1 else None
    if terminal is None or sorted(numbers) != list(range(1, terminal + 1)):
        failures.add("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")
    if not isinstance(proof, Mapping) or proof.get("status") != "PASS" or proof.get(
        "terminal_page"
    ) != terminal:
        failures.add("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")
    seen_urls: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping):
            failures.add("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")
            continue
        url = str(item.get("canonical_url", ""))
        if not url or url in seen_urls or item.get("page_number") not in numbers:
            failures.add("FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE")
        seen_urls.add(url)
    return failures, diagnostics


def _state_failures(
    states: Sequence[Mapping[str, Any]], eligible_ids: set[str]
) -> tuple[list[dict[str, Any]], set[str], list[str]]:
    failures: set[str] = set()
    diagnostics: list[str] = []
    rows: list[dict[str, Any]] = []
    authority_start = _timestamp(AUTHORITY_START_TEXT)
    authority_end = _timestamp(AUTHORITY_END_TEXT)
    common_fields = (
        "inst_type",
        "base_ccy",
        "quote_ccy",
        "lot_sz",
        "min_sz",
        "tick_sz",
        "listing_state",
    )
    for instrument in INSTRUMENTS:
        selected = sorted(
            (row for row in states if isinstance(row, Mapping) and row.get("instrument") == instrument),
            key=lambda row: str(row.get("effective_from", "")),
        )
        if not selected:
            failures.add("FAIL_REQUIRED_FIELD_MISSING")
            failures.add("FAIL_UNCOVERED_INTERVAL")
            continue
        previous_end = authority_start
        for state in selected:
            try:
                start = _timestamp(state["effective_from"])
                end = _timestamp(state["effective_to"])
                if start < previous_end:
                    failures.add("FAIL_AMBIGUOUS_OR_CONTRADICTORY_STATE")
                if start > previous_end:
                    failures.add("FAIL_UNCOVERED_INTERVAL")
                if end <= start:
                    failures.add("FAIL_INTERVAL_BOUNDARY_UNPROVEN")
                if state.get("contradiction") is not False:
                    failures.add("FAIL_AMBIGUOUS_OR_CONTRADICTORY_STATE")
                observed_identity = (
                    state.get("inst_type"),
                    state.get("base_ccy"),
                    state.get("quote_ccy"),
                    state.get("settle_ccy"),
                    state.get("ct_val_ccy"),
                )
                if observed_identity != IDENTITIES[instrument] or state.get("listing_state") != "live":
                    failures.add("FAIL_REQUIRED_FIELD_MISSING")
                required_fields = list(common_fields)
                if instrument.endswith("-SWAP"):
                    required_fields.extend(("settle_ccy", "ct_val", "ct_val_ccy"))
                for field in required_fields:
                    if state.get(field) in (None, ""):
                        failures.add("FAIL_REQUIRED_FIELD_MISSING")
                for field in ("lot_sz", "min_sz", "tick_sz"):
                    _decimal(state[field])
                if instrument.endswith("-SWAP"):
                    _decimal(state["ct_val"])
                source_ids_raw = state.get("source_ids")
                if not isinstance(source_ids_raw, Sequence) or isinstance(source_ids_raw, (str, bytes)) or not source_ids_raw:
                    failures.add("FAIL_REQUIRED_FIELD_MISSING")
                    source_ids: set[str] = set()
                else:
                    source_ids = {str(value) for value in source_ids_raw}
                    if source_ids - eligible_ids:
                        failures.add("FAIL_SOURCE_NOT_OFFICIAL_OKX")
                if not isinstance(state.get("derivation_rule_id"), str) or not state.get(
                    "derivation_rule_id"
                ):
                    failures.add("FAIL_REQUIRED_FIELD_MISSING")
                field_sources = state.get("field_source_ids")
                boundary_sources = state.get("boundary_source_ids")
                if not isinstance(field_sources, Mapping) or not isinstance(boundary_sources, Mapping):
                    failures.add("FAIL_REQUIRED_FIELD_MISSING")
                else:
                    for field in required_fields:
                        ids = field_sources.get(field)
                        if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)) or not ids or set(
                            str(value) for value in ids
                        ) - source_ids:
                            failures.add("FAIL_REQUIRED_FIELD_MISSING")
                    for boundary in ("effective_from", "effective_to"):
                        ids = boundary_sources.get(boundary)
                        if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)) or not ids or set(
                            str(value) for value in ids
                        ) - source_ids:
                            failures.add("FAIL_INTERVAL_BOUNDARY_UNPROVEN")
                if state.get("authority_mode") == "TRANSITION_SAFE_INTERSECTION":
                    key = (instrument, start.isoformat(), end.isoformat())
                    if key not in FROZEN_WINDOWS:
                        failures.add("FAIL_NEW_UNFROZEN_TRANSITION")
                rows.append(
                    {
                        "instrument": instrument,
                        "state_id": state.get("state_id"),
                        "authority_mode": state.get("authority_mode"),
                        "interval_start": start.isoformat(),
                        "interval_end_exclusive": min(end, authority_end).isoformat(),
                        "source_coverage_status": "PASS",
                        "overlap_count": 0,
                        "contradiction_count": 0,
                        "uncovered_duration_seconds": 0,
                        "required_fields_present": True,
                        "modeled_timestamp_outside_authority": False,
                    }
                )
                previous_end = min(end, authority_end)
                if previous_end == authority_end:
                    break
            except (KeyError, TypeError, ValueError) as exc:
                failures.add("FAIL_REQUIRED_FIELD_MISSING")
                diagnostics.append(f"malformed state for {instrument}: {exc}")
        if previous_end != authority_end:
            failures.add("FAIL_UNCOVERED_INTERVAL")
    return rows, failures, diagnostics


def _transition_failures(
    proofs: Sequence[Mapping[str, Any]], eligible_ids: set[str]
) -> tuple[set[str], list[str]]:
    failures: set[str] = set()
    diagnostics: list[str] = []
    if len(proofs) != len(FROZEN_WINDOWS):
        failures.add("FAIL_TRANSITION_WINDOW_UNPROVEN")
    seen: set[tuple[str, str, str]] = set()
    unchanged_fields = (
        "inst_type",
        "base_ccy",
        "quote_ccy",
        "settle_ccy",
        "ct_val",
        "ct_val_ccy",
        "tick_sz",
        "listing_state",
    )
    for proof in proofs:
        if not isinstance(proof, Mapping):
            failures.add("FAIL_TRANSITION_WINDOW_UNPROVEN")
            continue
        try:
            instrument = str(proof["instrument"])
            start = _timestamp(proof["window_start"]).isoformat()
            end = _timestamp(proof["window_end_exclusive"]).isoformat()
            key = (instrument, start, end)
            if key in seen:
                failures.add("FAIL_AMBIGUOUS_OR_CONTRADICTORY_STATE")
            seen.add(key)
            if key not in FROZEN_WINDOWS:
                failures.add("FAIL_NEW_UNFROZEN_TRANSITION")
            old_lot = _decimal(proof["old_lot"])
            new_lot = _decimal(proof["new_lot"])
            old_min = _decimal(proof["old_min"])
            new_min = _decimal(proof["new_min"])
            reported_lot = _decimal(proof["transition_lot"])
            reported_min = _decimal(proof["transition_min"])
            coarse = max(old_lot, new_lot)
            fine = min(old_lot, new_lot)
            if coarse / fine != (coarse / fine).to_integral_value():
                failures.add("FAIL_TRANSITION_INCREMENT_NOT_NESTED")
            expected_min = (max(old_min, new_min) / coarse).to_integral_value(
                rounding=ROUND_CEILING
            ) * coarse
            if reported_lot != coarse or reported_min != expected_min:
                failures.add("FAIL_TRANSITION_INTERSECTION_INVALID")
            if not _valid(reported_min, old_lot, old_min) or not _valid(
                reported_min, new_lot, new_min
            ):
                failures.add("FAIL_TRANSITION_INTERSECTION_INVALID")
            source_ids = set()
            for field in ("old_source_ids", "new_source_ids"):
                values = proof.get(field)
                if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
                    failures.add("FAIL_TRANSITION_WINDOW_UNPROVEN")
                else:
                    source_ids.update(str(value) for value in values)
            window_source = str(proof.get("official_window_source_id", ""))
            if not window_source:
                failures.add("FAIL_TRANSITION_WINDOW_UNPROVEN")
            source_ids.add(window_source)
            if source_ids - eligible_ids:
                failures.add("FAIL_SOURCE_NOT_OFFICIAL_OKX")
            unchanged = proof.get("unchanged_field_proof")
            if not isinstance(unchanged, Mapping):
                failures.add("FAIL_TRANSITION_FIELDS_CHANGED")
            else:
                for field in unchanged_fields:
                    values = unchanged.get(field)
                    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or not values:
                        failures.add("FAIL_TRANSITION_FIELDS_CHANGED")
            cases = proof.get("boundary_cases")
            if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)) or not cases:
                failures.add("FAIL_TRANSITION_INTERSECTION_INVALID")
            else:
                for row in cases:
                    if not isinstance(row, Mapping):
                        failures.add("FAIL_TRANSITION_INTERSECTION_INVALID")
                        continue
                    quantity = _decimal(row.get("quantity"), positive=False)
                    admitted = _valid(quantity, reported_lot, reported_min)
                    valid_old = _valid(quantity, old_lot, old_min)
                    valid_new = _valid(quantity, new_lot, new_min)
                    if row.get("admitted_by_intersection") is not admitted or row.get(
                        "valid_old"
                    ) is not valid_old or row.get("valid_new") is not valid_new:
                        failures.add("FAIL_TRANSITION_INTERSECTION_INVALID")
                    if admitted and not (valid_old and valid_new):
                        failures.add("FAIL_TRANSITION_INTERSECTION_INVALID")
        except (KeyError, TypeError, ValueError) as exc:
            failures.add("FAIL_TRANSITION_WINDOW_UNPROVEN")
            diagnostics.append(f"malformed transition proof: {exc}")
    if seen != FROZEN_WINDOWS:
        failures.add("FAIL_TRANSITION_WINDOW_UNPROVEN")
    return failures, diagnostics


def _artifact_hash_diagnostics(root: Path, gate_result: Mapping[str, Any]) -> list[str]:
    diagnostics: list[str] = []
    recorded = gate_result.get("artifact_hashes")
    if not isinstance(recorded, Mapping):
        return ["gate artifact_hashes missing"]
    excluded = {"gate_result.json", "independent_review.json", "manifest.json"}
    expected = {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path.relative_to(root).as_posix() not in excluded
    }
    observed = {str(path): str(digest) for path, digest in recorded.items()}
    if observed != expected:
        diagnostics.append("gate artifact_hashes do not match retained evidence")
    return diagnostics


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
    """Recompute the gate result while treating a correct expected FAIL as PASS."""

    diagnostics: list[str] = []
    recomputed: set[str] = set()
    query_failures, query_diagnostics = _query_failures(
        query_inventory, str(gate_result.get("query_inventory_sha256", ""))
    )
    recomputed.update(query_failures)
    diagnostics.extend(query_diagnostics)
    source_failures, eligible_ids, source_diagnostics = _source_failures(root, source_inventory)
    recomputed.update(source_failures)
    diagnostics.extend(source_diagnostics)
    catalog_failures, catalog_diagnostics = _catalog_failures(announcement_catalog)
    recomputed.update(catalog_failures)
    diagnostics.extend(catalog_diagnostics)
    recomputed_coverage, state_failures, state_diagnostics = _state_failures(
        list(metadata_states), eligible_ids
    )
    recomputed.update(state_failures)
    diagnostics.extend(state_diagnostics)
    transition_failures, transition_diagnostics = _transition_failures(
        list(transition_proofs), eligible_ids
    )
    recomputed.update(transition_failures)
    diagnostics.extend(transition_diagnostics)

    if list(coverage_matrix) != recomputed_coverage:
        diagnostics.append("coverage matrix does not match independent recomputation")
    manifest_diagnostics = verify_manifest_complete(
        root,
        preliminary_manifest,
        excluded_paths=("manifest.json", "independent_review.json"),
    )
    if manifest_diagnostics:
        recomputed.add("FAIL_MANIFEST_INCOMPLETE")
        diagnostics.extend(manifest_diagnostics)
    diagnostics.extend(_artifact_hash_diagnostics(root, gate_result))

    if gate_result.get("unsupported_projection_count", 0):
        recomputed.add("FAIL_UNSUPPORTED_BACKWARD_PROJECTION")
    if gate_result.get("forbidden_access_count", 0):
        recomputed.add("FAIL_FORBIDDEN_DATA_ACCESS")
    if gate_result.get("newly_discovered_transition_count", 0):
        recomputed.add("FAIL_NEW_UNFROZEN_TRANSITION")

    recorded = [str(item) for item in failures]
    try:
        recorded_primary = choose_primary_failure(recorded)
        recomputed_primary = choose_primary_failure(tuple(recomputed))
    except ValueError as exc:
        diagnostics.append(str(exc))
        recorded_primary = "FAIL_INDEPENDENT_REVIEW_MISMATCH"
        recomputed_primary = "FAIL_INDEPENDENT_REVIEW_MISMATCH"
    if set(recorded) != recomputed:
        diagnostics.append(
            f"recorded failure set mismatch: recorded={sorted(set(recorded))} recomputed={sorted(recomputed)}"
        )
    expected_status = "PASS" if recorded_primary is None else "FAIL"
    expected_result = "PASS" if recorded_primary is None else recorded_primary
    if gate_result.get("status") != expected_status or gate_result.get("result") != expected_result:
        diagnostics.append("preliminary gate result does not match recorded failure priority")
    if recorded_primary != recomputed_primary:
        diagnostics.append("recomputed primary failure does not match recorded primary failure")
    if gate_result.get("authoritative") is not False:
        diagnostics.append("preliminary gate result improperly claims authority")
    if gate_result.get("implementation_authorized") is not False or gate_result.get(
        "economic_data_access_authorized"
    ) is not False:
        diagnostics.append("gate result improperly authorizes downstream work")
    if not COMMIT_RE.fullmatch(str(gate_result.get("source_commit_sha", ""))):
        diagnostics.append("gate source commit SHA is invalid")

    statistics = {
        "source_object_count": len(source_inventory.get("sources", [])),
        "eligible_source_object_count": len(eligible_ids),
        "catalog_page_count": len(announcement_catalog.get("pages", [])),
        "catalog_item_count": len(announcement_catalog.get("items", [])),
        "metadata_state_count": len(metadata_states),
        "coverage_interval_count": len(coverage_matrix),
        "transition_proof_count": len(transition_proofs),
    }
    for field, value in statistics.items():
        if gate_result.get(field) != value:
            diagnostics.append(f"gate statistic mismatch: {field}")

    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GATE_INDEPENDENT_PACKAGE_REVIEW",
        "status": "PASS" if not diagnostics else "FAIL",
        "gate_status_recomputed": "PASS" if recomputed_primary is None else "FAIL",
        "gate_result_recomputed": "PASS" if recomputed_primary is None else recomputed_primary,
        "recorded_failures": sorted(set(recorded)),
        "recomputed_failures": sorted(recomputed),
        "query_inventory_sha256": hashlib.sha256(_canonical_json_bytes(query_inventory)).hexdigest(),
        "eligible_source_count": len(eligible_ids),
        "coverage_row_count": len(recomputed_coverage),
        "transition_proof_count": len(transition_proofs),
        "errors": diagnostics,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }
