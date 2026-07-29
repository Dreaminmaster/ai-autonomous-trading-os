"""Exact clean-checkout binding for one-shot C8A authority runs."""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

EXACT_SHA = re.compile(r"[0-9a-f]{40}")
Runner = Callable[..., subprocess.CompletedProcess[str]]


class C8AHistoricalRunGuardError(RuntimeError):
    """Raised unless the run is bound to an exact clean implementation SHA."""


def validate_checkout_binding(
    value: Mapping[str, Any], *, implementation_sha: str
) -> dict[str, Any]:
    expected = {
        "schema_version": 1,
        "stage": "C8A_HISTORICAL_CHECKOUT_BINDING",
        "implementation_sha": implementation_sha,
        "observed_head_sha": implementation_sha,
        "tracked_worktree_clean": True,
    }
    if dict(value) != expected:
        raise C8AHistoricalRunGuardError(
            "C8A checkout binding is dirty or SHA-mismatched"
        )
    return expected


def verify_checkout_binding(
    implementation_sha: str, *, repository_root: Path, runner: Runner = subprocess.run
) -> dict[str, Any]:
    if not EXACT_SHA.fullmatch(implementation_sha):
        raise C8AHistoricalRunGuardError("implementation SHA must be exact")
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
        raise C8AHistoricalRunGuardError(
            "unable to verify the C8A Git checkout"
        ) from exc
    if head != implementation_sha or status:
        raise C8AHistoricalRunGuardError(
            "C8A authority run requires its exact clean implementation checkout"
        )
    return validate_checkout_binding(
        {
            "schema_version": 1,
            "stage": "C8A_HISTORICAL_CHECKOUT_BINDING",
            "implementation_sha": implementation_sha,
            "observed_head_sha": head,
            "tracked_worktree_clean": True,
        },
        implementation_sha=implementation_sha,
    )
