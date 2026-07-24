"""Physically separate reviewer for the C6A execution-venue preflight.

This reviewer imports no producer, transport, parser, or network code. It reads
only retained JSON evidence, validates the durable invocation and venue
contracts, and reconciles producer and independent probe verdicts.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


VENUE_STAGE = "C6A_SOURCE_AUTHORITY_EXECUTION_VENUE_PREFLIGHT"
INVOCATION_STAGE = "C6A_SOURCE_AUTHORITY_EXECUTION_VENUE_INVOCATION"
CATEGORY_PROBE_STAGE = "C6A_GLOBAL_SOURCE_SCOPE_PROBE"
CATEGORY_PROBE_URL = "https://www.okx.com/help/category/announcements"
SCOPE_FAILURE = "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
EXECUTION_FAILURE = "FAIL_SOURCE_SCOPE_PROBE_EXECUTION"
ALLOWED_EXECUTION_MODES = {"LOCAL_USER_CONTROLLED", "SELF_HOSTED_RUNNER"}
EXPECTED_CANDIDATES = {
    "control-atos-minimal-a",
    "control-atos-minimal-b",
    "browser-neutral-en-a",
    "browser-neutral-en-b",
    "browser-en-us-a",
    "browser-en-us-b",
    "browser-en-gb-a",
    "browser-en-gb-b",
}
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MERGE_REF_RE = re.compile(r"^refs/pull/[1-9][0-9]*/merge@[0-9a-f]{40}$")
_INVOCATION_ID_RE = re.compile(r"^[0-9a-f]{32}$")


def _load_object(path: Path, errors: list[str]) -> dict[str, Any]:
    if not path.is_file():
        errors.append(f"{path.name} missing")
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        errors.append(f"{path.name} unreadable: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{path.name} root is not an object")
        return {}
    return value


def _is_global_category_url(url: Any) -> bool:
    parsed = urlparse(str(url))
    return bool(
        parsed.scheme == "https"
        and (parsed.hostname or "").lower() == "www.okx.com"
        and parsed.path.rstrip("/") == "/help/category/announcements"
        and not parsed.query
        and not parsed.fragment
        and not parsed.username
        and not parsed.password
    )


def review_venue_preflight(
    root: Path,
    *,
    expected_implementation_sha: str,
    expected_source_commit_sha: str,
    expected_validated_pr_merge_ref: str | None,
) -> dict[str, Any]:
    errors: list[str] = []
    invocation_path = root / "invocation_record.json"
    invocation = _load_object(invocation_path, errors)
    attestation = _load_object(root / "venue_attestation.json", errors)
    result = _load_object(root / "probe_result.json", errors)
    probe_review = _load_object(root / "independent_review.json", errors)

    if _SHA_RE.fullmatch(expected_implementation_sha) is None:
        errors.append("expected implementation SHA format invalid")
    if _SHA_RE.fullmatch(expected_source_commit_sha) is None:
        errors.append("expected source commit SHA format invalid")
    if (
        expected_validated_pr_merge_ref is not None
        and _MERGE_REF_RE.fullmatch(expected_validated_pr_merge_ref) is None
    ):
        errors.append("expected validated PR merge-ref format invalid")

    if invocation.get("stage") != INVOCATION_STAGE or invocation.get("status") != "STARTED":
        errors.append("invocation record identity drift")
    invocation_id = invocation.get("invocation_id")
    if not isinstance(invocation_id, str) or _INVOCATION_ID_RE.fullmatch(invocation_id) is None:
        errors.append("invocation id invalid")
    if invocation.get("output_name") != root.name:
        errors.append("invocation output-name mismatch")
    if invocation.get("implementation_sha") != expected_implementation_sha:
        errors.append("invocation implementation SHA mismatch")
    if invocation.get("source_commit_sha") != expected_source_commit_sha:
        errors.append("invocation source commit SHA mismatch")
    if invocation.get("validated_pr_merge_ref") != expected_validated_pr_merge_ref:
        errors.append("invocation validated PR merge-ref mismatch")

    if attestation.get("stage") != VENUE_STAGE:
        errors.append("venue stage drift")
    if attestation.get("status") != "PREPARED_NOT_AUTHORIZED":
        errors.append("venue status drift")
    mode = attestation.get("execution_mode")
    if mode not in ALLOWED_EXECUTION_MODES:
        errors.append("venue execution mode is not allowed")
    if not isinstance(attestation.get("venue_label"), str) or not attestation.get("venue_label", "").strip():
        errors.append("venue label missing")
    if attestation.get("implementation_sha") != expected_implementation_sha:
        errors.append("venue implementation SHA mismatch")
    if attestation.get("source_commit_sha") != expected_source_commit_sha:
        errors.append("venue source commit SHA mismatch")
    if attestation.get("validated_pr_merge_ref") != expected_validated_pr_merge_ref:
        errors.append("venue validated PR merge-ref mismatch")
    if attestation.get("invocation_id") != invocation_id:
        errors.append("venue invocation id mismatch")
    if invocation_path.is_file():
        observed_invocation_sha = hashlib.sha256(invocation_path.read_bytes()).hexdigest()
        if attestation.get("invocation_record_sha256") != observed_invocation_sha:
            errors.append("venue invocation-record digest mismatch")
    if attestation.get("proxy_environment_keys_present") != []:
        errors.append("venue proxy environment state is not clean")
    if attestation.get("cookie_or_auth_environment_keys_present") != []:
        errors.append("venue cookie/auth environment state is not clean")
    if attestation.get("probe_url") != CATEGORY_PROBE_URL:
        errors.append("venue probe URL drift")

    github_actions = attestation.get("github_actions")
    runner_environment = attestation.get("runner_environment")
    if mode == "LOCAL_USER_CONTROLLED" and github_actions is not False:
        errors.append("local venue unexpectedly reports GitHub Actions")
    if mode == "SELF_HOSTED_RUNNER" and not (
        github_actions is True and str(runner_environment).casefold() == "self-hosted"
    ):
        errors.append("self-hosted venue identity is inconsistent")

    for payload_name, payload in (("invocation", invocation), ("venue", attestation)):
        for key in (
            "article_expansion_authorized",
            "third_full_capture_authorized",
            "implementation_authorized",
            "economic_data_access_authorized",
        ):
            if payload.get(key) is not False:
                errors.append(f"{payload_name} improperly authorizes {key}")
        if payload.get("paper_state") != "PAPER_CLOSED":
            errors.append(f"{payload_name} paper-state drift")
        if payload.get("shadow_state") != "SHADOW_CLOSED":
            errors.append(f"{payload_name} shadow-state drift")
        if payload.get("live_state") != "LIVE_FORBIDDEN":
            errors.append(f"{payload_name} live-state drift")

    if result.get("stage") != CATEGORY_PROBE_STAGE or result.get("probe_url") != CATEGORY_PROBE_URL:
        errors.append("category-probe identity drift")
    rows = result.get("candidate_results")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        rows = []
        errors.append("category-probe candidate results missing")
    observed_ids = {
        str(row.get("candidate_id", ""))
        for row in rows
        if isinstance(row, Mapping)
    }
    if observed_ids != EXPECTED_CANDIDATES or len(rows) != len(EXPECTED_CANDIDATES):
        errors.append("category-probe candidate coverage mismatch")

    if probe_review.get("status") != "PASS":
        errors.append("category-probe independent review did not pass")
    recomputed_status = probe_review.get("probe_status_recomputed")
    recomputed_result = probe_review.get("probe_result_recomputed")
    if result.get("status") != recomputed_status:
        errors.append("category-probe producer/reviewer status mismatch")
    if result.get("result") != recomputed_result:
        errors.append("category-probe producer/reviewer result mismatch")

    if recomputed_status == "PASS" and recomputed_result == "PASS":
        venue_status = "ACCEPTED_FOR_BOUNDED_PREFLIGHT"
    elif recomputed_status == "FAIL" and recomputed_result == SCOPE_FAILURE:
        venue_status = "ACCEPTED_FOR_BOUNDED_PREFLIGHT"
    elif recomputed_status == "ERROR" and recomputed_result == EXECUTION_FAILURE:
        venue_status = "REJECTED_EXECUTION_FAILURE"
    else:
        venue_status = "REJECTED"
        errors.append("category-probe status/result combination is invalid")

    execution_rows = [
        row
        for row in rows
        if isinstance(row, Mapping) and row.get("execution_status") == "FAIL"
    ]
    if recomputed_status == "ERROR" and not execution_rows:
        errors.append("execution-failure verdict lacks failed candidate evidence")
    if recomputed_status != "ERROR" and execution_rows:
        errors.append("failed candidate evidence exists without execution-failure verdict")

    passing_profiles = probe_review.get("reproducible_passing_profiles")
    if result.get("reproducible_passing_profiles") != passing_profiles:
        errors.append("category-probe passing-profile mismatch")
    if recomputed_status == "PASS":
        passing_rows = [
            row
            for row in rows
            if isinstance(row, Mapping) and row.get("scope_status") == "PASS"
        ]
        if not passing_rows or not all(_is_global_category_url(row.get("final_url")) for row in passing_rows):
            errors.append("category-probe PASS lacks locale-neutral GLOBAL final URLs")

    for payload_name, payload in (
        ("probe result", result),
        ("probe independent review", probe_review),
    ):
        if payload.get("implementation_authorized") is not False:
            errors.append(f"{payload_name} improperly authorizes implementation")
        if payload.get("economic_data_access_authorized") is not False:
            errors.append(f"{payload_name} improperly authorizes economic data access")
        if payload.get("third_full_capture_authorized") is not False:
            errors.append(f"{payload_name} improperly authorizes third full capture")
        if payload.get("live_state") != "LIVE_FORBIDDEN":
            errors.append(f"{payload_name} live-state drift")

    return {
        "schema_version": 2,
        "stage": f"{VENUE_STAGE}_INDEPENDENT_REVIEW",
        "status": "PASS" if not errors else "FAIL",
        "venue_status_recomputed": venue_status if not errors else "REJECTED",
        "probe_status_recomputed": recomputed_status,
        "probe_result_recomputed": recomputed_result,
        "errors": errors,
        "article_expansion_authorized": False,
        "third_full_capture_authorized": False,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
