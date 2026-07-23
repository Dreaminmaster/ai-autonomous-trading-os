from __future__ import annotations

import json
from pathlib import Path

import pytest

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_capture import FrozenRequest
from atos.c6a_source_authority_catalog_remediation import parse_announcement_catalog
from atos.c6a_source_authority_scope import (
    SCOPE_FAILURE,
    global_scope_proof,
    parse_global_announcement_catalog,
    validate_global_catalog_url,
    validate_global_scope_inventory,
)
from atos.c6a_source_authority_scope_independent import review_global_scope
from atos.c6a_source_authority_transport import _validate_frozen_transport_target


GLOBAL_URL = (
    "https://www.okx.com/help/section/announcements-latest-announcements/page/1"
)


def _global_page(article_url: str = "/help/global-article") -> bytes:
    categories = " ".join(
        [
            "Latest announcements",
            "New listings",
            "Delistings",
            "Latest events",
            "Trading updates",
            "Deposit/withdrawal suspension",
            "P2P trading",
            "Web3",
            "Earn and Loan",
            "Jumpstart",
            "API",
            "OKB burn",
            "Others",
        ]
    )
    return f"""
    <html><head><title>Announcements | Help Center | OKX</title></head><body>
      <nav>{categories}</nav>
      <a href="{article_url}">Global metadata update Published on Apr 17, 2024</a>
      <div>Showing 1-1 of 1 articles</div>
    </body></html>
    """.encode()


def _us_page() -> bytes:
    return b"""
    <html><head><title>Announcements | Help Center | OKX United States</title></head><body>
      <nav>Latest announcements New listings Delistings Trading updates API</nav>
      <a href="/en-us/help/us-article">US update Published on Apr 17, 2024</a>
      <div>Showing 1-1 of 1 articles</div>
    </body></html>
    """


def _inventory() -> dict:
    return {
        "requests": [
            {
                "request_id": "okx-announcement-catalog-global",
                "request_kind": "announcement_catalog",
                "url": "https://www.okx.com/help/section/announcements-latest-announcements/page/{page}",
                "authority_jurisdiction": "GLOBAL",
                "requested_scope": {
                    "host": "www.okx.com",
                    "path_mode": "GLOBAL_LOCALE_NEUTRAL_HELP",
                    "regional_substitution_allowed": False,
                },
                "required_scope_proof": {
                    "final_url": True,
                    "page_content": True,
                    "cross_page_consistency": True,
                },
            }
        ]
    }


def test_inventory_freezes_exact_global_scope_contract() -> None:
    assert validate_global_scope_inventory(_inventory()) == _inventory()
    drifted = _inventory()
    drifted["requests"][0]["requested_scope"]["regional_substitution_allowed"] = True
    with pytest.raises(SourceAuthorityError, match="requested-scope contract drift"):
        validate_global_scope_inventory(drifted)


def test_global_parser_retains_positive_scope_proof() -> None:
    parsed = parse_global_announcement_catalog(
        GLOBAL_URL,
        _global_page(),
        base_parser=parse_announcement_catalog,
    )
    assert parsed["scope_proof"]["status"] == "PASS"
    assert parsed["scope_proof"]["authority_jurisdiction"] == "GLOBAL"
    assert parsed["articles"][0]["canonical_url"] == "https://www.okx.com/help/global-article"


def test_global_scope_rejects_us_page_content() -> None:
    with pytest.raises(SourceAuthorityError, match=SCOPE_FAILURE):
        global_scope_proof(GLOBAL_URL, _us_page())


def test_global_scope_rejects_regional_final_url_before_acceptance() -> None:
    request = FrozenRequest(
        request_id="okx-announcement-catalog-global-page-001",
        request_kind="announcement_catalog",
        url=GLOBAL_URL,
        expected_content_type="text/html",
        parent_request_id="okx-announcement-catalog-global",
    )
    with pytest.raises(SourceAuthorityError, match=SCOPE_FAILURE):
        _validate_frozen_transport_target(
            "https://www.okx.com/en-us/help/section/announcements-latest-announcements/page/1",
            request,
        )
    validate_global_catalog_url(GLOBAL_URL)


def test_global_parser_rejects_regional_article_link() -> None:
    with pytest.raises(SourceAuthorityError, match=SCOPE_FAILURE):
        parse_global_announcement_catalog(
            GLOBAL_URL,
            _global_page("/en-us/help/regional-article"),
            base_parser=parse_announcement_catalog,
        )


def test_independent_reviewer_recomputes_global_scope_from_retained_bytes(
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "raw" / "page.bin"
    decoded_path = tmp_path / "decoded" / "page.json"
    raw_path.parent.mkdir(parents=True)
    decoded_path.parent.mkdir(parents=True)
    raw_path.write_bytes(_global_page())
    parsed = parse_global_announcement_catalog(
        GLOBAL_URL,
        _global_page(),
        base_parser=parse_announcement_catalog,
    )
    decoded_path.write_text(json.dumps(parsed), encoding="utf-8")
    source_inventory = {
        "sources": [
            {
                "source_id": "okx-announcement-catalog-global-page-001",
                "requested_url": GLOBAL_URL,
                "retrieval_url": GLOBAL_URL,
                "raw_path": "raw/page.bin",
                "decoded_path": "decoded/page.json",
            }
        ]
    }
    review = review_global_scope(
        tmp_path,
        query_inventory=_inventory(),
        source_inventory=source_inventory,
        announcement_catalog={"pages": [{"page_number": 1}]},
    )
    assert review["status"] == "PASS"
    assert review["recomputed_failures"] == []
    assert review["page_numbers"] == [1]


def test_independent_reviewer_detects_retained_us_substitution(tmp_path: Path) -> None:
    raw_path = tmp_path / "raw" / "page.bin"
    decoded_path = tmp_path / "decoded" / "page.json"
    raw_path.parent.mkdir(parents=True)
    decoded_path.parent.mkdir(parents=True)
    raw_path.write_bytes(_us_page())
    decoded_path.write_text(
        json.dumps(
            {
                "page_number": 1,
                "articles": [
                    {"canonical_url": "https://www.okx.com/en-us/help/us-article"}
                ],
                "scope_proof": {
                    "status": "PASS",
                    "authority_jurisdiction": "GLOBAL",
                },
            }
        ),
        encoding="utf-8",
    )
    source_inventory = {
        "sources": [
            {
                "source_id": "okx-announcement-catalog-global-page-001",
                "requested_url": GLOBAL_URL,
                "retrieval_url": "https://www.okx.com/en-us/help/section/announcements-latest-announcements/page/1",
                "raw_path": "raw/page.bin",
                "decoded_path": "decoded/page.json",
            }
        ]
    }
    review = review_global_scope(
        tmp_path,
        query_inventory=_inventory(),
        source_inventory=source_inventory,
        announcement_catalog={"pages": [{"page_number": 1}]},
    )
    assert review["status"] == "FAIL"
    assert SCOPE_FAILURE in review["recomputed_failures"]
