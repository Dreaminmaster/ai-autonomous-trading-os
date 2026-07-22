from __future__ import annotations

import json
from pathlib import Path

import pytest

from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_authority_capture import (
    archive_lookup_requests,
    article_request,
    atomic_write_json,
    build_recursive_manifest,
    catalog_requests,
    classify_article,
    inventory_sha256,
    load_frozen_inventory,
    memento_request,
    parse_announcement_catalog,
    parse_wayback_cdx,
)
from atos.c6a_source_authority_metadata import decode_okx_instruments_response
from atos.c6a_source_authority_review import verify_manifest


CONFIG = Path(__file__).resolve().parents[1] / "config" / "c6a_source_authority_query_inventory_v1.json"


def _inventory() -> dict:
    return dict(load_frozen_inventory(CONFIG))


def test_committed_query_inventory_is_exact_and_non_placeholder() -> None:
    payload = _inventory()
    assert payload["design_authority_sha"] == "26a7604c34c610562643d7a732d35b39df84c94f"
    assert payload["authenticated"] is False
    assert payload["economic_endpoints_forbidden"] is True
    assert len(catalog_requests(payload)) == 250
    archives = archive_lookup_requests(payload)
    assert len(archives) == 4
    assert all(request.url.startswith("https://web.archive.org/cdx/") for request in archives)
    assert all("collapse=" not in request.url for request in archives)
    assert len(inventory_sha256(payload)) == 64


def test_catalog_parser_proves_pagination_and_classifies_every_article() -> None:
    html = b"""
    <html><body>
      <a href="/help/adjust-btc-swap">OKX to adjust lot size and minimum order quantity for BTC-USDT-SWAP Published on Apr 17, 2024</a>
      <a href="/help/unrelated">OKX launches an unrelated promotion Published on Apr 16, 2024</a>
      <div>Showing 1-2 of 2 articles</div>
    </body></html>
    """
    page = parse_announcement_catalog(
        "https://www.okx.com/help/section/announcements-latest-announcements/page/1",
        html,
    )
    assert page["page_number"] == 1
    assert page["declared_terminal_page"] == 1
    assert page["is_terminal_page"] is True
    assert len(page["articles"]) == 2

    payload = _inventory()
    classified = [
        classify_article(
            article,
            aliases=payload["instrument_aliases"],
            metadata_terms=payload["metadata_terms"],
        )
        for article in page["articles"]
    ]
    assert classified[0]["selected_for_article_capture"] is True
    assert "BTC-USDT-SWAP" in classified[0]["alias_matches"]
    assert classified[1]["selected_for_article_capture"] is False
    generated = article_request(classified[0], index=1)
    assert generated.request_kind == "announcement_article"
    assert generated.url == "https://www.okx.com/help/adjust-btc-swap"


def test_catalog_parser_rejects_missing_or_inconsistent_completeness_evidence() -> None:
    with pytest.raises(SourceAuthorityError, match="pagination summary"):
        parse_announcement_catalog(
            "https://www.okx.com/help/section/announcements-latest-announcements/page/1",
            b'<a href="/help/a">Article Published on Apr 17, 2024</a>',
        )
    with pytest.raises(SourceAuthorityError, match="first-item index drift"):
        parse_announcement_catalog(
            "https://www.okx.com/help/section/announcements-latest-announcements/page/2",
            b'<a href="/help/a">Article Published on Apr 17, 2024</a><div>Showing 1-1 of 1 articles</div>',
        )


def test_wayback_index_expands_only_exact_official_instrument_response() -> None:
    canonical = "https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=BTC-USDT-SWAP"
    cdx = [
        ["timestamp", "original", "statuscode", "mimetype", "digest", "length"],
        ["20240425070000", canonical, "200", "application/json", "DIGEST1", "900"],
    ]
    captures = parse_wayback_cdx(json.dumps(cdx).encode(), canonical_official_url=canonical)
    assert len(captures) == 1
    assert captures[0]["captured_at"] == "2024-04-25T07:00:00+00:00"
    request = memento_request(captures[0], parent_request_id="archive-btc", index=1)
    assert request.url == (
        "https://web.archive.org/web/20240425070000id_/"
        "https://www.okx.com/api/v5/public/instruments?instType=SWAP&instId=BTC-USDT-SWAP"
    )
    assert request.canonical_official_url == canonical


def test_wayback_index_rejects_wrong_original_and_out_of_range_capture() -> None:
    canonical = "https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT"
    wrong = [
        ["timestamp", "original", "statuscode", "mimetype", "digest", "length"],
        [
            "20240425070000",
            "https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=ETH-USDT",
            "200",
            "application/json",
            "DIGEST1",
            "900",
        ],
    ]
    with pytest.raises(SourceAuthorityError, match="does not match"):
        parse_wayback_cdx(json.dumps(wrong).encode(), canonical_official_url=canonical)

    future = [
        ["timestamp", "original", "statuscode", "mimetype", "digest", "length"],
        ["20260101000000", canonical, "200", "application/json", "DIGEST2", "900"],
    ]
    with pytest.raises(SourceAuthorityError, match="escaped"):
        parse_wayback_cdx(json.dumps(future).encode(), canonical_official_url=canonical)


def test_archived_okx_swap_decoder_uses_underlying_and_preserves_exact_strings() -> None:
    response = {
        "code": "0",
        "msg": "",
        "data": [
            {
                "instId": "ETH-USDT-SWAP",
                "instType": "SWAP",
                "uly": "ETH-USDT",
                "baseCcy": "",
                "quoteCcy": "",
                "settleCcy": "USDT",
                "ctVal": "0.1",
                "ctValCcy": "ETH",
                "lotSz": "0.01",
                "minSz": "0.01",
                "tickSz": "0.01",
                "state": "live",
                "ignored": "not-authority",
            }
        ],
    }
    decoded = decode_okx_instruments_response(
        json.dumps(response).encode(), expected_instrument="ETH-USDT-SWAP"
    )
    row = decoded["data"][0]
    assert row["baseCcy"] == "ETH"
    assert row["quoteCcy"] == "USDT"
    assert row["uly"] == "ETH-USDT"
    assert row["identity_derivation"] == "EXACT_OFFICIAL_UNDERLYING"
    assert row["ctVal"] == "0.1"
    assert row["lotSz"] == "0.01"
    assert "ignored" not in row


def test_archived_okx_spot_decoder_uses_direct_base_and_quote() -> None:
    response = {
        "code": "0",
        "msg": "",
        "data": [
            {
                "instId": "BTC-USDT",
                "instType": "SPOT",
                "baseCcy": "BTC",
                "quoteCcy": "USDT",
                "uly": "",
                "lotSz": "0.00000001",
                "minSz": "0.00001",
                "tickSz": "0.1",
                "state": "live",
            }
        ],
    }
    row = decode_okx_instruments_response(
        json.dumps(response).encode(), expected_instrument="BTC-USDT"
    )["data"][0]
    assert row["baseCcy"] == "BTC"
    assert row["quoteCcy"] == "USDT"
    assert row["identity_derivation"] == "DIRECT_SPOT_BASE_QUOTE"


def test_archived_okx_decoder_rejects_wrapper_and_swap_identity_drift() -> None:
    wrapper = b'<html><body>Wayback Machine</body></html>'
    with pytest.raises(SourceAuthorityError, match="valid JSON"):
        decode_okx_instruments_response(wrapper, expected_instrument="ETH-USDT-SWAP")

    wrong_underlying = {
        "code": "0",
        "msg": "",
        "data": [
            {
                "instId": "ETH-USDT-SWAP",
                "instType": "SWAP",
                "uly": "BTC-USDT",
                "settleCcy": "USDT",
                "ctVal": "0.1",
                "ctValCcy": "ETH",
                "lotSz": "0.01",
                "minSz": "0.01",
                "tickSz": "0.01",
                "state": "live",
            }
        ],
    }
    with pytest.raises(SourceAuthorityError, match="underlying identity mismatch"):
        decode_okx_instruments_response(
            json.dumps(wrong_underlying).encode(), expected_instrument="ETH-USDT-SWAP"
        )


def test_recursive_manifest_is_canonical_and_independently_verifiable(tmp_path: Path) -> None:
    atomic_write_json(tmp_path / "source_inventory.json", {"sources": []})
    atomic_write_json(tmp_path / "coverage_matrix.json", {"rows": []})
    manifest = build_recursive_manifest(tmp_path)
    atomic_write_json(tmp_path / "manifest.json", manifest)
    assert manifest["file_count"] == 2
    assert verify_manifest(tmp_path, manifest) == []

    (tmp_path / "coverage_matrix.json").write_text("tampered", encoding="utf-8")
    errors = verify_manifest(tmp_path, manifest)
    assert any("manifest size mismatch" in error or "manifest SHA-256 mismatch" in error for error in errors)
