"""Higher-level validation for the frozen C6A source-authority inventory.

The catalog title for a critical metadata notice may omit the affected BTC/ETH
instrument.  This module therefore binds the five already identified official
transition notices directly and uses a conservative metadata-adjustment title
classifier for any additional catalog item.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence
from urllib.parse import urlparse

from atos.c6a_source_authority import AUTHORITY_END, AUTHORITY_START, SourceAuthorityError, parse_utc_timestamp, validate_url
from atos.c6a_source_authority_capture import FrozenRequest


KNOWN_TRANSITION_REQUESTS = {
    "known-transition-eth-2024-04-18": "/en-us/help/okx-to-adjust-the-minimum-order-quantities-for-several-futures-240412",
    "known-transition-btc-2024-04-25": "/en-us/help/okx-to-adjust-the-minimum-order-quantities-for-several-futures-24-04-19",
    "known-transition-eth-original-2024-12-18": "/en-us/help/okx-to-adjust-the-minimum-order-quantities-for-ethusdt-perpetual-and-expiry",
    "known-transition-eth-postponed-2025-01-09": "/en-us/help/okx-to-postpone-adjusting-minimum-order-quantities-for-ethusdt-perpetual-and",
    "known-transition-btc-2025-01-22": "/en-us/help/okx-to-adjust-the-minimum-order-quantities-of-spots-and-futures",
}
ADJUSTMENT_TERMS = (
    "adjust",
    "change",
    "update",
    "postpone",
    "minimum",
    "lot",
    "tick",
    "step size",
    "trading parameter",
)


def direct_transition_article_requests(payload: Mapping[str, Any]) -> tuple[FrozenRequest, ...]:
    rows = {
        str(row.get("request_id")): row
        for row in payload.get("requests", [])
        if isinstance(row, Mapping) and str(row.get("request_id", "")).startswith("known-transition-")
    }
    if set(rows) != set(KNOWN_TRANSITION_REQUESTS):
        missing = sorted(set(KNOWN_TRANSITION_REQUESTS) - set(rows))
        extra = sorted(set(rows) - set(KNOWN_TRANSITION_REQUESTS))
        raise SourceAuthorityError(f"known transition announcement inventory drift: missing={missing} extra={extra}")
    result: list[FrozenRequest] = []
    for request_id, expected_path in KNOWN_TRANSITION_REQUESTS.items():
        row = rows[request_id]
        if row.get("request_kind") != "announcement_article" or row.get("method") != "GET":
            raise SourceAuthorityError("known transition announcement request contract drift")
        url = str(row.get("url", ""))
        canonical = str(row.get("canonical_official_url", ""))
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "www.okx.com" or parsed.path != expected_path:
            raise SourceAuthorityError(f"known transition announcement URL drift: {request_id}")
        if canonical != url:
            raise SourceAuthorityError("known transition announcement canonical URL drift")
        validate_url(url, request_kind="announcement_article")
        if row.get("expected_content_type") != "text/html":
            raise SourceAuthorityError("known transition announcement content type drift")
        result.append(
            FrozenRequest(
                request_id=request_id,
                request_kind="announcement_article",
                url=url,
                canonical_official_url=canonical,
                expected_content_type="text/html",
            )
        )
    return tuple(result)


def classify_catalog_article(
    article: Mapping[str, Any],
    *,
    aliases: Mapping[str, Sequence[str]],
    metadata_terms: Sequence[str],
    known_urls: Sequence[str],
) -> dict[str, Any]:
    title = str(article.get("title", ""))
    url = str(article.get("canonical_url", ""))
    published_at = parse_utc_timestamp(article.get("published_at"))
    normalized = title.casefold()
    alias_matches = sorted(
        {
            alias
            for values in aliases.values()
            for alias in values
            if alias.casefold() in normalized
        }
    )
    metadata_matches = sorted(term for term in metadata_terms if term.casefold() in normalized)
    adjustment_matches = sorted(term for term in ADJUSTMENT_TERMS if term in normalized)
    direct_known_match = url in set(known_urls)
    inside_date_range = AUTHORITY_START <= published_at < AUTHORITY_END
    selected = inside_date_range and (
        direct_known_match
        or bool(metadata_matches and adjustment_matches)
        or bool(alias_matches and metadata_matches)
    )
    return {
        **dict(article),
        "inside_authority_date_range": inside_date_range,
        "alias_matches": alias_matches,
        "metadata_term_matches": metadata_matches,
        "adjustment_term_matches": adjustment_matches,
        "direct_known_transition_match": direct_known_match,
        "selected_for_article_capture": selected,
        "classification_rule": "METADATA_ADJUSTMENT_OR_INSTRUMENT_METADATA_MATCH",
    }


def prove_catalog_terminal_page(page: Mapping[str, Any], *, frozen_max_page: int) -> dict[str, Any]:
    page_number = page.get("page_number")
    terminal = page.get("declared_terminal_page")
    is_terminal = page.get("is_terminal_page")
    if type(page_number) is not int or type(terminal) is not int:
        raise SourceAuthorityError("catalog terminal-page proof lacks integer page values")
    if terminal < 1 or terminal > frozen_max_page:
        raise SourceAuthorityError("declared catalog terminal page exceeds frozen scan range")
    if page_number != terminal or is_terminal is not True:
        raise SourceAuthorityError("catalog scan did not stop on the declared terminal page")
    return {
        "status": "PASS",
        "terminal_page": terminal,
        "frozen_max_page": frozen_max_page,
        "unused_frozen_page_capacity": frozen_max_page - terminal,
    }
