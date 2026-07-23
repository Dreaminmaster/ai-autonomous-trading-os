"""Strict execution boundary for C6A source-authority attempts.

The executable path binds the attempt to strict redirect-safe transport,
committed pacing, GLOBAL source-scope validation, scope-aware parsing, complete
failure taxonomy, retained-attempt diagnostic reconciliation, and independent
GLOBAL scope review.  Every binding is restored in ``finally`` so focused
offline tests remain isolated.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import atos.c6a_source_authority as core
import atos.c6a_source_authority_attempt as attempt
import atos.c6a_source_authority_attempt_review as attempt_review
import atos.c6a_source_authority_gate as gate
import atos.c6a_source_authority_independent as independent
import atos.c6a_source_authority_package as package
from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_attempt_review import (
    review_package_with_attempt_diagnostics,
)
from atos.c6a_source_authority_catalog_remediation import (
    parse_announcement_catalog as parse_locale_aware_catalog,
)
from atos.c6a_source_authority_scope import (
    SCOPE_FAILURE,
    extend_failure_priority,
    parse_global_announcement_catalog,
    validate_global_scope_inventory,
)
from atos.c6a_source_authority_transport import strict_capture_request


def _paced_capture(inventory_path: Path) -> Callable[..., Any]:
    payload = json.loads(inventory_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SourceAuthorityError("query inventory root must be an object")
    validate_global_scope_inventory(payload)
    policy = payload.get("rate_limit_policy")
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


def _scope_validated_loader(original: Callable[[Path], Any]) -> Callable[[Path], Any]:
    def load(path: Path) -> Any:
        return validate_global_scope_inventory(original(path))

    return load


def _global_catalog_parser(page_url: str, data: bytes, *, expected_page_size: int = 15) -> dict[str, Any]:
    return parse_global_announcement_catalog(
        page_url,
        data,
        base_parser=parse_locale_aware_catalog,
        expected_page_size=expected_page_size,
    )


def _scope_failure_mapper(
    original: Callable[..., str],
) -> Callable[..., str]:
    def classify(exc: BaseException, *, request_kind: str) -> str:
        message = str(exc).casefold()
        if SCOPE_FAILURE.casefold() in message or "source authority scope drift" in message:
            return SCOPE_FAILURE
        return original(exc, request_kind=request_kind)

    return classify


def run_strict_source_authority_attempt(
    *,
    inventory_path: Path,
    output_root: Path,
    source_commit_sha: str,
    pr_merge_ref: str | None,
) -> dict[str, Any]:
    original_capture = attempt.capture_request
    original_catalog_parser = attempt.parse_announcement_catalog
    original_package_review = package.review_package
    original_loader = attempt.load_frozen_inventory
    original_exception_mapper = attempt._failure_for_exception
    original_priorities = {
        "core": core.FAILURE_PRIORITY,
        "attempt": attempt.FAILURE_PRIORITY,
        "gate": gate.FAILURE_PRIORITY,
        "independent": independent.FAILURE_PRIORITY,
        "attempt_review": attempt_review.FAILURE_PRIORITY,
    }
    extended_priority = extend_failure_priority(core.FAILURE_PRIORITY)

    attempt.capture_request = _paced_capture(inventory_path)
    attempt.parse_announcement_catalog = _global_catalog_parser
    attempt.load_frozen_inventory = _scope_validated_loader(original_loader)
    attempt._failure_for_exception = _scope_failure_mapper(original_exception_mapper)
    package.review_package = review_package_with_attempt_diagnostics
    core.FAILURE_PRIORITY = extended_priority
    attempt.FAILURE_PRIORITY = extended_priority
    gate.FAILURE_PRIORITY = extended_priority
    independent.FAILURE_PRIORITY = extended_priority
    attempt_review.FAILURE_PRIORITY = extended_priority
    try:
        return attempt.run_source_authority_attempt(
            inventory_path=inventory_path,
            output_root=output_root,
            source_commit_sha=source_commit_sha,
            pr_merge_ref=pr_merge_ref,
        )
    finally:
        attempt_review.FAILURE_PRIORITY = original_priorities["attempt_review"]
        independent.FAILURE_PRIORITY = original_priorities["independent"]
        gate.FAILURE_PRIORITY = original_priorities["gate"]
        attempt.FAILURE_PRIORITY = original_priorities["attempt"]
        core.FAILURE_PRIORITY = original_priorities["core"]
        package.review_package = original_package_review
        attempt._failure_for_exception = original_exception_mapper
        attempt.load_frozen_inventory = original_loader
        attempt.parse_announcement_catalog = original_catalog_parser
        attempt.capture_request = original_capture
