"""Attempt-1 remediation for the official OKX announcement catalog parser.

OKX serves the same Help Center under a bounded, single-segment locale prefix
such as ``/en-us/help/``, ``/zh-hans/help/``, or ``/pt/help/``.  Attempt 1
incorrectly accepted only ``/help/``.  This module keeps the original strict
pagination and article-count contract while accepting only the documented
shape of those locale-prefixed official Help Center paths.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_capture import CATALOG_PAGE_RE, PUBLISHED_RE, _AnchorParser


OKX_HELP_PATH_RE = re.compile(
    r"^/(?:[a-z]{2,3}(?:-[a-z]{2,4})?/)?help(?:/|$)"
)


def is_bounded_okx_help_path(path: str) -> bool:
    """Return whether ``path`` is global Help Center or one locale segment deep."""

    return bool(OKX_HELP_PATH_RE.match(path))


def parse_announcement_catalog(
    page_url: str, data: bytes, *, expected_page_size: int = 15
) -> dict[str, Any]:
    """Parse one frozen catalog page without rewriting its exact article URLs."""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SourceAuthorityError("announcement catalog is not UTF-8") from exc
    parser = _AnchorParser()
    parser.feed(text)
    joined_text = " ".join(parser.text_parts)
    summary_match = CATALOG_PAGE_RE.search(joined_text)
    if not summary_match:
        raise SourceAuthorityError("announcement catalog pagination summary missing")
    first, last, total = (int(value) for value in summary_match.groups())
    if first < 1 or last < first or total < last:
        raise SourceAuthorityError("announcement catalog pagination summary is invalid")
    page_number_match = re.search(r"/page/(\d+)(?:$|[/?#])", page_url)
    if not page_number_match:
        raise SourceAuthorityError("announcement catalog page URL lacks an exact page number")
    page_number = int(page_number_match.group(1))
    expected_first = (page_number - 1) * expected_page_size + 1
    if first != expected_first:
        raise SourceAuthorityError("announcement catalog first-item index drift")
    if last - first + 1 > expected_page_size:
        raise SourceAuthorityError("announcement catalog page exceeds frozen page size")
    terminal_page = (total + expected_page_size - 1) // expected_page_size

    articles: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for href, anchor_text in parser.anchors:
        match = PUBLISHED_RE.match(anchor_text)
        if not match:
            continue
        canonical_url = urljoin(page_url, href)
        parsed = urlparse(canonical_url)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "www.okx.com"
            or not is_bounded_okx_help_path(parsed.path)
        ):
            raise SourceAuthorityError("catalog article URL escaped the frozen OKX help scope")
        published_date = datetime.strptime(match.group("date"), "%b %d, %Y").replace(
            tzinfo=timezone.utc
        )
        if canonical_url in seen_urls:
            raise SourceAuthorityError("duplicate article URL within one catalog page")
        seen_urls.add(canonical_url)
        articles.append(
            {
                "title": match.group("title").strip(),
                "published_at": published_date.isoformat(),
                "canonical_url": canonical_url,
            }
        )
    expected_count = last - first + 1
    if len(articles) != expected_count:
        raise SourceAuthorityError(
            f"announcement catalog article count mismatch: parsed={len(articles)} expected={expected_count}"
        )
    return {
        "page_number": page_number,
        "first_item": first,
        "last_item": last,
        "total_items": total,
        "declared_terminal_page": terminal_page,
        "is_terminal_page": page_number == terminal_page,
        "articles": articles,
    }
