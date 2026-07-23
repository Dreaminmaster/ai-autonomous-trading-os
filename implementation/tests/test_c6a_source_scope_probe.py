from __future__ import annotations

from pathlib import Path

import pytest

import atos.c6a_source_scope_probe as probe
from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_scope_probe import (
    CANDIDATES,
    PROBE_URL,
    atomic_write_json,
    build_manifest,
    run_probe,
    validate_probe_target,
)
from atos.c6a_source_scope_probe_independent import review_probe


def _global_page() -> bytes:
    return b"""
    <html><head><title>Announcements | Help Center | OKX</title></head><body>
      <nav>
        Latest announcements New listings Delistings Latest events Trading updates
        Deposit/withdrawal suspension P2P trading Web3 Earn and Loan Jumpstart API
        OKB burn Others
      </nav>
      <div>Showing 1-15 of 3042 articles</div>
    </body></html>
    """


def _us_page() -> bytes:
    return b"""
    <html><head><title>Announcements | Help Center | OKX United States</title></head><body>
      <nav>Latest announcements New listings Delistings Trading updates API</nav>
      <div>Showing 1-15 of 121 articles</div>
    </body></html>
    """


def _fetcher(raw: bytes, final_url: str):
    def fetch(candidate):
        return {
            "retrieval_started_at": "2026-07-23T00:00:00+00:00",
            "retrieval_completed_at": "2026-07-23T00:00:01+00:00",
            "attempt_number": 1,
            "status_code": 200,
            "final_url": final_url,
            "headers": {"content-type": "text/html"},
            "redirect_chain": [],
            "raw_bytes": raw,
        }

    return fetch


def test_candidate_matrix_has_two_replicates_per_transparent_profile() -> None:
    profiles = {candidate.profile_id for candidate in CANDIDATES}
    assert profiles == {
        "control-atos-minimal",
        "browser-neutral-en",
        "browser-en-us",
        "browser-en-gb",
    }
    for profile_id in profiles:
        selected = [candidate for candidate in CANDIDATES if candidate.profile_id == profile_id]
        assert {candidate.replicate for candidate in selected} == {"A", "B"}
        assert len(selected) == 2
        assert all("Cookie" not in candidate.headers() for candidate in selected)
        assert all("Authorization" not in candidate.headers() for candidate in selected)


def test_probe_target_is_bounded_to_public_help_page() -> None:
    validate_probe_target(PROBE_URL)
    validate_probe_target(
        "https://www.okx.com/en-us/help/section/announcements-latest-announcements/page/1"
    )
    with pytest.raises(SourceAuthorityError, match="escaped the frozen Help Center page"):
        validate_probe_target("https://www.okx.com/api/v5/public/instruments")
    with pytest.raises(SourceAuthorityError, match="escaped www.okx.com"):
        validate_probe_target("https://example.com/help/category/announcements")


def test_global_probe_pass_requires_replicated_profile_and_independent_pass(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _: None)
    result = run_probe(tmp_path, fetch_candidate=_fetcher(_global_page(), PROBE_URL))
    assert result["status"] == "PASS"
    assert set(result["reproducible_passing_profiles"]) == {
        "control-atos-minimal",
        "browser-neutral-en",
        "browser-en-us",
        "browser-en-gb",
    }
    review = review_probe(tmp_path)
    assert review["status"] == "PASS"
    assert review["probe_status_recomputed"] == "PASS"
    assert review["reproducible_passing_profiles"] == result[
        "reproducible_passing_profiles"
    ]
    atomic_write_json(tmp_path / "independent_review.json", review)
    manifest = build_manifest(tmp_path)
    assert manifest["file_count"] == 10
    assert manifest["third_full_capture_authorized"] is False


def test_regional_substitution_is_expected_probe_fail_with_review_pass(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _: None)
    regional_url = (
        "https://www.okx.com/en-us/help/section/announcements-latest-announcements/page/1"
    )
    result = run_probe(tmp_path, fetch_candidate=_fetcher(_us_page(), regional_url))
    assert result["status"] == "FAIL"
    assert result["result"] == "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
    assert result["reproducible_passing_profiles"] == []
    assert all(
        row["failure_code"] == "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
        for row in result["candidate_results"]
    )
    review = review_probe(tmp_path)
    assert review["status"] == "PASS"
    assert review["probe_status_recomputed"] == "FAIL"
    assert review["probe_result_recomputed"] == "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
    assert review["errors"] == []


def test_independent_review_rejects_candidate_header_drift(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _: None)
    run_probe(tmp_path, fetch_candidate=_fetcher(_global_page(), PROBE_URL))
    import json

    path = tmp_path / "probe_result.json"
    payload = json.loads(path.read_text())
    payload["candidate_results"][0]["request_headers"]["Cookie"] = "forbidden"
    path.write_text(json.dumps(payload), encoding="utf-8")
    review = review_probe(tmp_path)
    assert review["status"] == "FAIL"
    assert any("request header drift" in error for error in review["errors"])
    assert any("prohibited request state" in error for error in review["errors"])
