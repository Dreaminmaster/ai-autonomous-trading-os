from __future__ import annotations

from pathlib import Path

import pytest

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_capture import load_frozen_inventory
from atos.c6a_source_authority_inventory import (
    KNOWN_TRANSITION_REQUESTS,
    classify_catalog_article,
    direct_transition_article_requests,
    prove_catalog_terminal_page,
)


CONFIG = Path(__file__).resolve().parents[1] / "config" / "c6a_source_authority_query_inventory_v1.json"


def _payload() -> dict:
    return dict(load_frozen_inventory(CONFIG))


def test_five_known_transition_announcements_are_directly_bound() -> None:
    requests = direct_transition_article_requests(_payload())
    assert tuple(request.request_id for request in requests) == tuple(KNOWN_TRANSITION_REQUESTS)
    assert all(request.url == request.canonical_official_url for request in requests)
    assert all(request.expected_content_type == "text/html" for request in requests)


def test_generic_metadata_notice_without_instrument_in_title_is_selected() -> None:
    payload = _payload()
    known_urls = [request.url for request in direct_transition_article_requests(payload)]
    article = {
        "title": "OKX to adjust the minimum order quantities for several futures",
        "published_at": "2024-04-12T00:00:00Z",
        "canonical_url": "https://www.okx.com/help/okx-to-adjust-the-minimum-order-quantities-for-several-futures-240412",
    }
    result = classify_catalog_article(
        article,
        aliases=payload["instrument_aliases"],
        metadata_terms=payload["metadata_terms"],
        known_urls=known_urls,
    )
    assert result["alias_matches"] == []
    assert "minimum order quantities" in result["metadata_term_matches"]
    assert "adjust" in result["adjustment_term_matches"]
    assert result["selected_for_article_capture"] is True
    assert type(result["selected_for_article_capture"]) is bool


def test_unrelated_article_and_post_boundary_article_are_not_selected() -> None:
    payload = _payload()
    known_urls = [request.url for request in direct_transition_article_requests(payload)]
    unrelated = classify_catalog_article(
        {
            "title": "OKX launches a trading competition",
            "published_at": "2024-04-12T00:00:00Z",
            "canonical_url": "https://www.okx.com/help/competition",
        },
        aliases=payload["instrument_aliases"],
        metadata_terms=payload["metadata_terms"],
        known_urls=known_urls,
    )
    assert unrelated["selected_for_article_capture"] is False
    assert type(unrelated["selected_for_article_capture"]) is bool

    future = classify_catalog_article(
        {
            "title": "OKX to adjust minimum order quantities for BTC-USDT-SWAP",
            "published_at": "2026-01-01T00:00:00Z",
            "canonical_url": "https://www.okx.com/help/future-adjustment",
        },
        aliases=payload["instrument_aliases"],
        metadata_terms=payload["metadata_terms"],
        known_urls=known_urls,
    )
    assert future["inside_authority_date_range"] is False
    assert future["selected_for_article_capture"] is False


def test_terminal_page_proof_must_land_inside_frozen_range() -> None:
    proof = prove_catalog_terminal_page(
        {
            "page_number": 203,
            "declared_terminal_page": 203,
            "is_terminal_page": True,
        },
        frozen_max_page=250,
    )
    assert proof == {
        "status": "PASS",
        "terminal_page": 203,
        "frozen_max_page": 250,
        "unused_frozen_page_capacity": 47,
    }

    with pytest.raises(SourceAuthorityError, match="did not stop"):
        prove_catalog_terminal_page(
            {
                "page_number": 202,
                "declared_terminal_page": 203,
                "is_terminal_page": False,
            },
            frozen_max_page=250,
        )
