"""Execution-venue preflight for C6A GLOBAL source-authority work.

The module prepares a bounded local/self-hosted venue attestation, enforces a
durable one-start invocation record, runs only the reviewed announcements-
category scope probe, and retains evidence without authorizing downstream work.
"""
from __future__ import annotations

import hashlib
import os
import platform
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import atos.c6a_source_scope_category_execution as category
import atos.c6a_source_scope_probe as probe
from atos.c6a_source_authority import SourceAuthorityError


VENUE_STAGE = "C6A_SOURCE_AUTHORITY_EXECUTION_VENUE_PREFLIGHT"
INVOCATION_STAGE = "C6A_SOURCE_AUTHORITY_EXECUTION_VENUE_INVOCATION"
INVOCATION_RECORD_FILENAME = "invocation_record.json"
ALLOWED_EXECUTION_MODES = ("LOCAL_USER_CONTROLLED", "SELF_HOSTED_RUNNER")
FORBIDDEN_PROXY_ENVIRONMENT_KEYS = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
FORBIDDEN_STATE_ENVIRONMENT_KEYS = (
    "COOKIE",
    "COOKIES",
    "AUTHORIZATION",
    "PROXY_AUTHORIZATION",
    "cookie",
    "cookies",
    "authorization",
    "proxy_authorization",
)
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_MERGE_REF_RE = re.compile(r"^refs/pull/[1-9][0-9]*/merge@[0-9a-f]{40}$")


def _present_nonempty(environ: Mapping[str, str], keys: Sequence[str]) -> list[str]:
    return sorted(key for key in keys if str(environ.get(key, "")).strip())


def invocation_marker_path(output_root: Path) -> Path:
    return output_root.parent / f".{output_root.name}.invocation-started.json"


def begin_invocation(
    output_root: Path,
    *,
    venue_label: str,
    execution_mode: str,
    implementation_sha: str,
    source_commit_sha: str,
    validated_pr_merge_ref: str | None,
) -> dict[str, Any]:
    """Create an adjacent O_EXCL marker before any output or network activity."""

    if output_root.exists():
        raise SourceAuthorityError(f"execution output already exists: {output_root}")
    marker = invocation_marker_path(output_root)
    payload = {
        "schema_version": 1,
        "stage": INVOCATION_STAGE,
        "status": "STARTED",
        "invocation_id": uuid.uuid4().hex,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "output_name": output_root.name,
        "venue_label": venue_label,
        "execution_mode": execution_mode,
        "implementation_sha": implementation_sha,
        "source_commit_sha": source_commit_sha,
        "validated_pr_merge_ref": validated_pr_merge_ref,
        "article_expansion_authorized": False,
        "third_full_capture_authorized": False,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }
    data = probe.canonical_json_bytes(payload)
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SourceAuthorityError(
            f"execution invocation marker already exists; repeated start rejected: {marker}"
        ) from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        raise
    output_root.mkdir(parents=True, exist_ok=False)
    probe.atomic_write_bytes(output_root / INVOCATION_RECORD_FILENAME, data)
    return payload


def _load_invocation_record(
    output_root: Path,
    *,
    venue_label: str,
    execution_mode: str,
    implementation_sha: str,
    source_commit_sha: str,
    validated_pr_merge_ref: str | None,
) -> tuple[dict[str, Any], str]:
    path = output_root / INVOCATION_RECORD_FILENAME
    if not path.is_file():
        raise SourceAuthorityError("durable invocation record is required before venue preflight")
    data = path.read_bytes()
    try:
        import json

        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise SourceAuthorityError(f"invocation record is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise SourceAuthorityError("invocation record root must be an object")
    expected = {
        "stage": INVOCATION_STAGE,
        "status": "STARTED",
        "output_name": output_root.name,
        "venue_label": venue_label,
        "execution_mode": execution_mode,
        "implementation_sha": implementation_sha,
        "source_commit_sha": source_commit_sha,
        "validated_pr_merge_ref": validated_pr_merge_ref,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise SourceAuthorityError(f"invocation record {key} mismatch")
    invocation_id = value.get("invocation_id")
    if not isinstance(invocation_id, str) or re.fullmatch(r"[0-9a-f]{32}", invocation_id) is None:
        raise SourceAuthorityError("invocation record id is invalid")
    return value, hashlib.sha256(data).hexdigest()


def build_venue_attestation(
    *,
    venue_label: str,
    execution_mode: str,
    implementation_sha: str,
    source_commit_sha: str,
    validated_pr_merge_ref: str | None,
    invocation_record: Mapping[str, Any],
    invocation_record_sha256: str,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Build a privacy-minimal, fail-closed execution-venue attestation."""

    label = venue_label.strip()
    if not label:
        raise SourceAuthorityError("execution venue label is required")
    if execution_mode not in ALLOWED_EXECUTION_MODES:
        raise SourceAuthorityError(f"unsupported execution venue mode: {execution_mode}")
    if _SHA_RE.fullmatch(implementation_sha) is None or _SHA_RE.fullmatch(source_commit_sha) is None:
        raise SourceAuthorityError("execution venue SHA identity must use full lowercase hexadecimal SHAs")
    if validated_pr_merge_ref is not None and _MERGE_REF_RE.fullmatch(validated_pr_merge_ref) is None:
        raise SourceAuthorityError("execution venue validated PR merge-ref format is invalid")

    proxy_keys = _present_nonempty(environ, FORBIDDEN_PROXY_ENVIRONMENT_KEYS)
    state_keys = _present_nonempty(environ, FORBIDDEN_STATE_ENVIRONMENT_KEYS)
    if proxy_keys:
        raise SourceAuthorityError(
            "execution venue contains prohibited proxy environment state: "
            + ",".join(proxy_keys)
        )
    if state_keys:
        raise SourceAuthorityError(
            "execution venue contains prohibited cookie/auth environment state: "
            + ",".join(state_keys)
        )

    github_actions = str(environ.get("GITHUB_ACTIONS", "")).casefold() == "true"
    runner_environment = environ.get("RUNNER_ENVIRONMENT") or None
    if execution_mode == "LOCAL_USER_CONTROLLED" and github_actions:
        raise SourceAuthorityError("LOCAL_USER_CONTROLLED venue cannot run inside GitHub Actions")
    if execution_mode == "SELF_HOSTED_RUNNER" and not (
        github_actions and str(runner_environment).casefold() == "self-hosted"
    ):
        raise SourceAuthorityError(
            "SELF_HOSTED_RUNNER venue requires GitHub Actions RUNNER_ENVIRONMENT=self-hosted"
        )

    return {
        "schema_version": 2,
        "stage": VENUE_STAGE,
        "status": "PREPARED_NOT_AUTHORIZED",
        "venue_label": label,
        "execution_mode": execution_mode,
        "implementation_sha": implementation_sha,
        "source_commit_sha": source_commit_sha,
        "validated_pr_merge_ref": validated_pr_merge_ref,
        "invocation_id": invocation_record["invocation_id"],
        "invocation_record_sha256": invocation_record_sha256,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
        "github_actions": github_actions,
        "runner_environment": runner_environment,
        "proxy_environment_keys_present": proxy_keys,
        "cookie_or_auth_environment_keys_present": state_keys,
        "probe_url": category.CATEGORY_PROBE_URL,
        "article_expansion_authorized": False,
        "third_full_capture_authorized": False,
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live_state": "LIVE_FORBIDDEN",
    }


def run_venue_preflight(
    output_root: Path,
    *,
    venue_label: str,
    execution_mode: str,
    implementation_sha: str,
    source_commit_sha: str,
    validated_pr_merge_ref: str | None,
    environ: Mapping[str, str] | None = None,
    fetch_candidate: Callable[[probe.ProbeCandidate], Mapping[str, Any]] = probe.network_fetch_candidate,
    candidates: Sequence[probe.ProbeCandidate] = probe.CANDIDATES,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Run one bounded venue preflight after a durable invocation record exists."""

    invocation_record, invocation_record_sha256 = _load_invocation_record(
        output_root,
        venue_label=venue_label,
        execution_mode=execution_mode,
        implementation_sha=implementation_sha,
        source_commit_sha=source_commit_sha,
        validated_pr_merge_ref=validated_pr_merge_ref,
    )
    effective_environment = dict(os.environ if environ is None else environ)
    attestation = build_venue_attestation(
        venue_label=venue_label,
        execution_mode=execution_mode,
        implementation_sha=implementation_sha,
        source_commit_sha=source_commit_sha,
        validated_pr_merge_ref=validated_pr_merge_ref,
        invocation_record=invocation_record,
        invocation_record_sha256=invocation_record_sha256,
        environ=effective_environment,
    )
    probe.atomic_write_json(output_root / "venue_attestation.json", attestation)
    result, review, manifest = category.run_category_scope_probe(
        output_root,
        fetch_candidate=fetch_candidate,
        candidates=candidates,
    )
    return attestation, result, review, manifest
