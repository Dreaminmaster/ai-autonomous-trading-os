"""Strict execution boundary for the one-shot C6A source-authority attempt.

The executable path binds the attempt's transport to the strict redirect guard
and to the committed rate-limit policy.  The original binding is restored in
``finally`` so focused offline tests remain isolated.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import atos.c6a_source_authority_attempt as attempt
from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_transport import strict_capture_request


def _paced_capture(inventory_path: Path) -> Callable[..., Any]:
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    policy = payload.get("rate_limit_policy") if isinstance(payload, dict) else None
    if not isinstance(policy, dict):
        raise SourceAuthorityError("query inventory rate-limit policy is required")
    minimum = policy.get("minimum_interval_seconds")
    maximum_per_minute = policy.get("maximum_requests_per_minute")
    if type(minimum) not in (int, float) or minimum < 0:
        raise SourceAuthorityError("minimum request interval must be non-negative")
    if type(maximum_per_minute) is not int or maximum_per_minute < 1 or maximum_per_minute > 60:
        raise SourceAuthorityError("maximum requests per minute must be an integer from 1 to 60")
    interval = max(float(minimum), 60.0 / maximum_per_minute)
    last_started: float | None = None

    def capture(*args: Any, **kwargs: Any) -> Any:
        nonlocal last_started
        now = time.monotonic()
        if last_started is not None:
            remaining = interval - (now - last_started)
            if remaining > 0:
                time.sleep(remaining)
        last_started = time.monotonic()
        return strict_capture_request(*args, **kwargs)

    return capture


def run_strict_source_authority_attempt(
    *,
    inventory_path: Path,
    output_root: Path,
    source_commit_sha: str,
    pr_merge_ref: str | None,
) -> dict[str, Any]:
    original = attempt.capture_request
    attempt.capture_request = _paced_capture(inventory_path)
    try:
        return attempt.run_source_authority_attempt(
            inventory_path=inventory_path,
            output_root=output_root,
            source_commit_sha=source_commit_sha,
            pr_merge_ref=pr_merge_ref,
        )
    finally:
        attempt.capture_request = original
