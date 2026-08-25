"""Exact clean-checkout binding for the one-shot C12A authority run."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

EXACT_SHA = re.compile(r"[0-9a-f]{40}")
Runner = Callable[..., subprocess.CompletedProcess[str]]


class C12AHistoricalRunGuardError(RuntimeError):
    """Raised unless C12A authority uses its exact clean implementation SHA."""


def validate_checkout_binding(
    value: Mapping[str, Any], *, implementation_sha: str
) -> dict[str, Any]:
    expected = {
        "schema_version": 1,
        "stage": "C12A_HISTORICAL_CHECKOUT_BINDING",
        "implementation_sha": implementation_sha,
        "observed_head_sha": implementation_sha,
        "tracked_worktree_clean": True,
    }
    if not EXACT_SHA.fullmatch(implementation_sha) or dict(value) != expected:
        raise C12AHistoricalRunGuardError(
            "C12A checkout binding is dirty or SHA-mismatched"
        )
    return expected


def verify_checkout_binding(
    implementation_sha: str,
    *,
    repository_root: Path,
    runner: Runner = subprocess.run,
) -> dict[str, Any]:
    if not EXACT_SHA.fullmatch(implementation_sha):
        raise C12AHistoricalRunGuardError("implementation SHA must be exact")
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
        raise C12AHistoricalRunGuardError(
            "unable to verify the C12A Git checkout"
        ) from exc
    if head != implementation_sha or status:
        raise C12AHistoricalRunGuardError(
            "C12A authority requires its exact clean implementation checkout"
        )
    return validate_checkout_binding(
        {
            "schema_version": 1,
            "stage": "C12A_HISTORICAL_CHECKOUT_BINDING",
            "implementation_sha": implementation_sha,
            "observed_head_sha": head,
            "tracked_worktree_clean": True,
        },
        implementation_sha=implementation_sha,
    )


__all__ = [
    "C12AHistoricalRunGuardError",
    "validate_checkout_binding",
    "verify_checkout_binding",
]
