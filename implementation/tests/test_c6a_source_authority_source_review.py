from __future__ import annotations

from atos.c6a_source_authority_source_review import review_source_boundaries


def _source(authority_class: str, retrieval_url: str, **overrides) -> dict:
    value = {
        "source_id": "source-1",
        "authority_class": authority_class,
        "canonical_official_url": "https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT",
        "retrieval_url": retrieval_url,
        "archive_capture_timestamp": "2024-01-01T00:00:00+00:00",
        "eligible": True,
        "rejection_reason": None,
    }
    value.update(overrides)
    return value


def test_exact_archived_response_must_be_retrieved_from_wayback() -> None:
    result = review_source_boundaries(
        {
            "sources": [
                _source(
                    "EXACT_ARCHIVED_OFFICIAL_OKX_RESPONSE",
                    "https://example.invalid/copied-okx-response.json",
                )
            ]
        }
    )
    assert result["status"] == "FAIL"
    assert any("web.archive.org" in error for error in result["errors"])


def test_exact_wayback_and_direct_okx_sources_pass() -> None:
    archive = _source(
        "EXACT_ARCHIVED_OFFICIAL_OKX_RESPONSE",
        "https://web.archive.org/web/20240101000000id_/https://www.okx.com/api/v5/public/instruments?instType=SPOT&instId=BTC-USDT",
    )
    direct = _source(
        "OFFICIAL_OKX_ANNOUNCEMENT",
        "https://www.okx.com/help/example",
        source_id="source-2",
        archive_capture_timestamp=None,
    )
    result = review_source_boundaries({"sources": [archive, direct]})
    assert result["status"] == "PASS"
    assert result["source_count"] == 2
    assert result["archived_source_count"] == 1


def test_non_archive_source_cannot_escape_okx() -> None:
    result = review_source_boundaries(
        {
            "sources": [
                _source(
                    "OFFICIAL_OKX_ANNOUNCEMENT",
                    "https://example.invalid/help-copy",
                    archive_capture_timestamp=None,
                )
            ]
        }
    )
    assert result["status"] == "FAIL"
    assert any("escaped official OKX" in error for error in result["errors"])
