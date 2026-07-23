"""Strict execution boundary for the one-shot C6A source-authority attempt.

The attempt module is intentionally transport-agnostic for focused offline
unit tests.  The executable path temporarily binds its capture callable to the
strict transport wrapper, restores the original binding in ``finally``, and
therefore cannot run an archive request through the weaker primitive.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import atos.c6a_source_authority_attempt as attempt
from atos.c6a_source_authority_transport import strict_capture_request


def run_strict_source_authority_attempt(
    *,
    inventory_path: Path,
    output_root: Path,
    source_commit_sha: str,
    pr_merge_ref: str | None,
) -> dict[str, Any]:
    original = attempt.capture_request
    attempt.capture_request = strict_capture_request
    try:
        return attempt.run_source_authority_attempt(
            inventory_path=inventory_path,
            output_root=output_root,
            source_commit_sha=source_commit_sha,
            pr_merge_ref=pr_merge_ref,
        )
    finally:
        attempt.capture_request = original
