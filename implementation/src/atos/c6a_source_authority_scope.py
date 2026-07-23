"""Fail-closed GLOBAL announcement-scope validation for C6A.

The source-authority inventory intends the locale-neutral GLOBAL OKX Help
Center.  A regional Help Center is an official OKX source, but it is not an
authority-equivalent substitute.  This module validates the frozen inventory,
request/final URLs, visible page evidence, and article links without accessing
any economic, account, private, paper, shadow, or live endpoint.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

from atos.c6a_source_authority import SourceAuthorityError


SCOPE_FAILURE = "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
GLOBAL_JURISDICTION = "GLOBAL"
GLOBAL_CATALOG_REQUEST_ID = "okx-announcement-catalog-global"
GLOBAL_CATALOG_PATH_RE = re.compile(
    r"^/help/(?:category/announcements|section/announcements-latest-announcements(?:/page/\d+)?)$",
    re.IGNORECASE,
)
GLOBAL_ARTICLE_PATH_RE = re.compile(r"^/help/[^/].*$", re.IGNORECASE)
LOCALE_HELP_PATH_RE = re.compile(r"^/[a-z]{2,3}(?:-[a-z]{2,4})?/help(?:/|$)", re.IGNORECASE)

_REQUIRED_GLOBAL_CATEGORY_MARKERS = (
    "latest events",
    "deposit/withdrawal suspension",
    "p2p trading",
    "web3",
    "earn and loan",
    "jumpstart",
    "okb burn",
    "others",
)
_FORBIDDEN_REGIONAL_MARKERS = (
    "okx united states",
    "okx europe",
    "okx tr",
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = " ".join(data.split())
        if text:
            self.parts.append(text)


def _scope_error(message: str) -> SourceAuthorityError:
    return SourceAuthorityError(f"{SCOPE_FAILURE}: {message}")


def is_global_catalog_request(request: Any) -> bool:
    return bool(
        getattr(request, "request_kind", None) == "announcement_catalog"
        and (
            getattr(request, "parent_request_id", None) == GLOBAL_CATALOG_REQUEST_ID
            or str(getattr(request, "request_id", "")).startswith(
                f"{GLOBAL_CATALOG_REQUEST_ID}-page-"
            )
        )
    )


def is_global_catalog_article_request(request: Any) -> bool:
    return bool(
        getattr(request, "request_kind", None) == "announcement_article"
        and getattr(request, "parent_request_id", None) == GLOBAL_CATALOG_REQUEST_ID
    )


def validate_global_catalog_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "www.okx.com":
        raise _scope_error(f"GLOBAL catalog escaped www.okx.com: {url}")
    if LOCALE_HELP_PATH_RE.match(parsed.path):
        raise _scope_error(f"GLOBAL catalog was substituted by a regional locale path: {url}")
    if GLOBAL_CATALOG_PATH_RE.fullmatch(parsed.path) is None:
        raise _scope_error(f"GLOBAL catalog escaped the frozen locale-neutral path: {url}")


def validate_global_article_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() != "www.okx.com":
        raise _scope_error(f"GLOBAL catalog article escaped www.okx.com: {url}")
    if LOCALE_HELP_PATH_RE.match(parsed.path):
        raise _scope_error(f"GLOBAL catalog article was substituted by a regional path: {url}")
    if GLOBAL_ARTICLE_PATH_RE.fullmatch(parsed.path) is None:
        raise _scope_error(f"GLOBAL catalog article escaped /help/: {url}")


def validate_global_scope_inventory(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    """Require the explicit immutable GLOBAL request-scope contract."""

    rows = payload.get("requests")
    if not isinstance(rows, list):
        raise SourceAuthorityError("GLOBAL scope inventory requests missing")
    matches = [row for row in rows if isinstance(row, Mapping) and row.get("request_id") == GLOBAL_CATALOG_REQUEST_ID]
    if len(matches) != 1:
        raise SourceAuthorityError("GLOBAL scope inventory must contain one exact catalog request")
    row = matches[0]
    if row.get("request_kind") != "announcement_catalog":
        raise SourceAuthorityError("GLOBAL scope catalog request kind drift")
    if row.get("authority_jurisdiction") != GLOBAL_JURISDICTION:
        raise SourceAuthorityError("GLOBAL authority jurisdiction is not frozen")
    requested_scope = row.get("requested_scope")
    if not isinstance(requested_scope, Mapping) or dict(requested_scope) != {
        "host": "www.okx.com",
        "path_mode": "GLOBAL_LOCALE_NEUTRAL_HELP",
        "regional_substitution_allowed": False,
    }:
        raise SourceAuthorityError("GLOBAL requested-scope contract drift")
    required_proof = row.get("required_scope_proof")
    if not isinstance(required_proof, Mapping) or dict(required_proof) != {
        "final_url": True,
        "page_content": True,
        "cross_page_consistency": True,
    }:
        raise SourceAuthorityError("GLOBAL required-scope proof contract drift")
    validate_global_catalog_url(str(row.get("url", "")).replace("{page}", "1"))
    return payload


def global_scope_proof(page_url: str, data: bytes) -> dict[str, Any]:
    """Derive positive GLOBAL scope evidence from retained official page bytes."""

    validate_global_catalog_url(page_url)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _scope_error("GLOBAL catalog page is not UTF-8") from exc
    parser = _VisibleTextParser()
    parser.feed(text)
    visible = " ".join(parser.parts)
    folded = visible.casefold()
    forbidden = [marker for marker in _FORBIDDEN_REGIONAL_MARKERS if marker in folded]
    missing = [marker for marker in _REQUIRED_GLOBAL_CATEGORY_MARKERS if marker not in folded]
    if forbidden:
        raise _scope_error(f"regional page identity markers present: {forbidden}")
    if missing:
        raise _scope_error(f"positive GLOBAL category evidence missing: {missing}")
    return {
        "schema_version": 1,
        "stage": "C6A_SOURCE_AUTHORITY_GLOBAL_SCOPE_PROOF",
        "status": "PASS",
        "authority_jurisdiction": GLOBAL_JURISDICTION,
        "requested_url": page_url,
        "required_category_markers": list(_REQUIRED_GLOBAL_CATEGORY_MARKERS),
        "forbidden_regional_markers": list(_FORBIDDEN_REGIONAL_MARKERS),
        "implementation_authorized": False,
        "economic_data_access_authorized": False,
        "live_state": "LIVE_FORBIDDEN",
    }


def parse_global_announcement_catalog(
    page_url: str,
    data: bytes,
    *,
    base_parser: Callable[..., dict[str, Any]],
    expected_page_size: int = 15,
) -> dict[str, Any]:
    """Parse one GLOBAL catalog page and retain independently reviewable proof."""

    proof = global_scope_proof(page_url, data)
    parsed = dict(base_parser(page_url, data, expected_page_size=expected_page_size))
    for article in parsed.get("articles", []):
        if not isinstance(article, Mapping):
            raise _scope_error("catalog article record is not an object")
        validate_global_article_url(str(article.get("canonical_url", "")))
    parsed["scope_proof"] = proof
    return parsed


def extend_failure_priority(priority: tuple[str, ...]) -> tuple[str, ...]:
    """Insert scope drift before archive/catalog completeness failures."""

    if SCOPE_FAILURE in priority:
        return priority
    values = list(priority)
    anchor = "FAIL_ARCHIVE_DECODING_OR_PROVENANCE"
    index = values.index(anchor) if anchor in values else 0
    values.insert(index, SCOPE_FAILURE)
    return tuple(values)
