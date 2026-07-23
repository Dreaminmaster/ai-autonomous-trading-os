"""Strict transport wrapper for the one-shot C6A source capture.

The lower-level capture primitive validates request scope and retained bytes.
This wrapper additionally prevents an archive redirect from escaping the frozen
Wayback host, because an archive lookup's canonical OKX URL is provenance, not
permission to follow an arbitrary third-party redirect.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_capture import CapturedResponse, FrozenRequest, capture_request


def strict_capture_request(
    request: FrozenRequest,
    *,
    output_root: Path,
    timeout_seconds: int,
    max_attempts: int,
    initial_backoff_seconds: int,
    maximum_backoff_seconds: int,
) -> CapturedResponse:
    capture = capture_request(
        request,
        output_root=output_root,
        timeout_seconds=timeout_seconds,
        max_attempts=max_attempts,
        initial_backoff_seconds=initial_backoff_seconds,
        maximum_backoff_seconds=maximum_backoff_seconds,
    )
    if request.request_kind == "archive_lookup":
        host = (urlparse(capture.final_url).hostname or "").lower()
        if host != "web.archive.org":
            raise SourceAuthorityError(
                f"archive redirect escaped frozen host: {capture.final_url}"
            )
    return capture
