"""Execution-venue preflight for C6A GLOBAL source-authority work.

GitHub-hosted runners deterministically resolve both tested locale-neutral OKX
Help Center entry points to the US regional Help Center.  This module prepares a
bounded local/self-hosted venue attestation, runs only the already-reviewed
announcements-category scope probe, and retains the venue evidence alongside the
existing producer and independent probe outputs.

It does not run the full source-authority capture and cannot authorize economic,
paper, shadow, private-API, or live work.
"""
from __future__ import annotations

import os
import platform
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import atos.c6a_source_scope_category_execution as category
import atos.c6a_source_scope_probe as probe
from atos.c6a_source_authority import SourceAuthorityError


VENUE_STAGE = "C6A_SOURCE_AUTHORITY_EXECUTION_VENUE_PREFLIGHT"
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
)


def _present_nonempty(environ: Mapping[str, str], keys: Sequence[str]) -> list[str]:
    return sorted(key for key in keys if str(environ.get(key, "")).strip())


def build_venue_attestation(
    *,
    venue_label: str,
    execution_mode: str,
    implementation_sha: str,
    source_commit_sha: str,
    validated_pr_merge_ref: str | None,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    """Build a privacy-minimal, fail-closed execution-venue attestation."""

    label = venue_label.strip()
    if not label:
        raise SourceAuthorityError("execution venue label is required")
    if execution_mode not in ALLOWED_EXECUTION_MODES:
        raise SourceAuthorityError(f"unsupported execution venue mode: {execution_mode}")
    if len(implementation_sha) != 40 or len(source_commit_sha) != 40:
        raise SourceAuthorityError("execution venue SHA identity must use full 40-character SHAs")

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

    return {
        "schema_version": 1,
        "stage": VENUE_STAGE,
        "status": "PREPARED_NOT_AUTHORIZED",
        "venue_label": label,
        "execution_mode": execution_mode,
        "implementation_sha": implementation_sha,
        "source_commit_sha": source_commit_sha,
        "validated_pr_merge_ref": validated_pr_merge_ref,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform_system": platform.system(),
        "platform_release": platform.release(),
        "platform_machine": platform.machine(),
        "github_actions": str(environ.get("GITHUB_ACTIONS", "")).casefold() == "true",
        "runner_environment": environ.get("RUNNER_ENVIRONMENT") or None,
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
    """Run one bounded venue preflight and retain its attestation in the manifest."""

    output_root.mkdir(parents=True, exist_ok=True)
    effective_environment = dict(os.environ if environ is None else environ)
    attestation = build_venue_attestation(
        venue_label=venue_label,
        execution_mode=execution_mode,
        implementation_sha=implementation_sha,
        source_commit_sha=source_commit_sha,
        validated_pr_merge_ref=validated_pr_merge_ref,
        environ=effective_environment,
    )
    probe.atomic_write_json(output_root / "venue_attestation.json", attestation)
    result, review, manifest = category.run_category_scope_probe(
        output_root,
        fetch_candidate=fetch_candidate,
        candidates=candidates,
    )
    return attestation, result, review, manifest
