"""Strict transport wrapper for the one-shot C6A source capture.

The lower-level capture primitive validates request scope and retained bytes.
This wrapper additionally validates every HTTP redirect before it is followed,
so an archive lookup cannot contact or retain bytes from an unfrozen host.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import atos.c6a_source_authority_capture as capture_module
from atos.c6a_source_authority import SourceAuthorityError, validate_url
from atos.c6a_source_authority_capture import CapturedResponse, FrozenRequest


class _FrozenRedirectHandler(HTTPRedirectHandler):
    """Reject an out-of-scope redirect before urllib opens the target URL."""

    def __init__(self, frozen_request: FrozenRequest) -> None:
        super().__init__()
        self._frozen_request = frozen_request

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        resolved = urljoin(req.full_url, newurl)
        validate_url(
            resolved,
            request_kind=self._frozen_request.request_kind,
            canonical_official_url=self._frozen_request.canonical_official_url,
        )
        if self._frozen_request.request_kind == "archive_lookup":
            host = (urlparse(resolved).hostname or "").lower()
            if host != "web.archive.org":
                raise SourceAuthorityError(
                    f"archive redirect escaped frozen host before follow: {resolved}"
                )
        return super().redirect_request(req, fp, code, msg, headers, resolved)


def strict_capture_request(
    request: FrozenRequest,
    *,
    output_root: Path,
    timeout_seconds: int,
    max_attempts: int,
    initial_backoff_seconds: int,
    maximum_backoff_seconds: int,
) -> CapturedResponse:
    """Capture through a redirect-aware opener and retain defense-in-depth checks."""

    opener = build_opener(_FrozenRedirectHandler(request))
    original_urlopen = capture_module.urlopen
    capture_module.urlopen = opener.open
    try:
        capture = capture_module.capture_request(
            request,
            output_root=output_root,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
            initial_backoff_seconds=initial_backoff_seconds,
            maximum_backoff_seconds=maximum_backoff_seconds,
        )
    finally:
        capture_module.urlopen = original_urlopen

    if request.request_kind == "archive_lookup":
        host = (urlparse(capture.final_url).hostname or "").lower()
        if host != "web.archive.org":
            raise SourceAuthorityError(
                f"archive redirect escaped frozen host: {capture.final_url}"
            )
    return capture
