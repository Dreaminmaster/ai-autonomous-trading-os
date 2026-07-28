"""Exact-checkout guard for authoritative C7A capture and evaluation runs."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

EXACT_SHA = re.compile(r"[0-9a-f]{40}")
Runner = Callable[..., subprocess.CompletedProcess[str]]


class C7AHistoricalRunGuardError(RuntimeError):
    """Raised when the running checkout cannot be bound to an exact clean SHA."""


def validate_checkout_binding(
    value: Mapping[str, Any], *, implementation_sha: str
) -> dict[str, Any]:
    """Validate the retained exact-checkout attestation schema."""
    expected = {
        "schema_version": 1,
        "stage": "C7A_HISTORICAL_CHECKOUT_BINDING",
        "implementation_sha": implementation_sha,
        "observed_head_sha": implementation_sha,
        "tracked_worktree_clean": True,
    }
    if dict(value) != expected:
        raise C7AHistoricalRunGuardError(
            "historical checkout binding is missing, dirty, or SHA-mismatched"
        )
    return expected


def verify_checkout_binding(
    implementation_sha: str,
    *,
    repository_root: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    """Fail closed unless HEAD equals the claim and tracked files are clean."""
    if not EXACT_SHA.fullmatch(implementation_sha):
        raise C7AHistoricalRunGuardError("implementation SHA must be exact")
    root = Path(repository_root).resolve()
    try:
        head = runner(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
        status = runner(
            [
                "git",
                "-C",
                str(root),
                "status",
                "--porcelain=v1",
                "--untracked-files=no",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise C7AHistoricalRunGuardError(
            "unable to verify the authoritative Git checkout"
        ) from exc
    if head != implementation_sha:
        raise C7AHistoricalRunGuardError(
            f"checkout HEAD {head!r} does not match implementation SHA"
        )
    if status:
        raise C7AHistoricalRunGuardError(
            "authoritative historical run requires a clean tracked worktree"
        )
    return validate_checkout_binding(
        {
            "schema_version": 1,
            "stage": "C7A_HISTORICAL_CHECKOUT_BINDING",
            "implementation_sha": implementation_sha,
            "observed_head_sha": head,
            "tracked_worktree_clean": True,
        },
        implementation_sha=implementation_sha,
    )
