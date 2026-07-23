"""Strict transport wrapper for the one-shot C6A source capture.

The lower-level capture primitive validates request scope and retained bytes.
This wrapper additionally validates every initial target and HTTP redirect
against a positive path allowlist before it is contacted.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

import atos.c6a_source_authority_capture as capture_module
from atos.c6a_source_authority import SourceAuthorityError, validate_url
from atos.c6a_source_authority_capture import CapturedResponse, FrozenRequest


_HELP_PATH_RE = re.compile(r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?help(?:/.*)?$", re.IGNORECASE)
_CATALOG_PATH_RE = re.compile(
    r"^/(?:[a-z]{2}(?:-[a-z]{2})?/)?help/section/[^/]+(?:/page/\d+)?$",
    re.IGNORECASE,
)


def _validate_frozen_transport_target(url: str, request: FrozenRequest) -> None:
    """Apply the request-kind-specific positive host/path boundary."""

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path
    kind = request.request_kind

    if kind == "archive_lookup":
        if host != "web.archive.org" or not (
            path == "/cdx/search/cdx" or path.startswith("/web/")
        ):
            raise SourceAuthorityError(f"archive target escaped frozen host/path: {url}")
        return

    if host != "okx.com" and not host.endswith(".okx.com"):
        raise SourceAuthorityError(f"official source target escaped OKX host: {url}")
    if kind == "public_instruments" and path.lower() != "/api/v5/public/instruments":
        raise SourceAuthorityError(f"public-instruments target escaped frozen path: {url}")
    if kind == "announcement_catalog" and _CATALOG_PATH_RE.fullmatch(path) is None:
        raise SourceAuthorityError(f"announcement catalog target escaped frozen help path: {url}")
    if kind == "announcement_article" and _HELP_PATH_RE.fullmatch(path) is None:
        raise SourceAuthorityError(f"announcement article target escaped frozen help path: {url}")


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
        _validate_frozen_transport_target(resolved, self._frozen_request)
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

    validate_url(
        request.url,
        request_kind=request.request_kind,
        canonical_official_url=request.canonical_official_url,
    )
    _validate_frozen_transport_target(request.url, request)
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

    _validate_frozen_transport_target(capture.final_url, request)
    return capture
