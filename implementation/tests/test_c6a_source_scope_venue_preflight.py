from __future__ import annotations

import json
from pathlib import Path

import pytest

import atos.c6a_source_scope_probe as probe
from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_scope_category_execution import CATEGORY_PROBE_URL
from atos.c6a_source_scope_venue_preflight import run_venue_preflight
from atos.c6a_source_scope_venue_preflight_independent import review_venue_preflight


IMPLEMENTATION_SHA = "1" * 40
SOURCE_COMMIT_SHA = "2" * 40
MERGE_REF = "refs/pull/77/merge@" + ("3" * 40)
GLOBAL_HTML = b"""<!doctype html><html><body>
<h1>Announcements</h1>
<nav>
Latest events
Deposit/withdrawal suspension
P2P trading
Web3
Earn and Loan
Jumpstart
OKB burn
Others
</nav>
</body></html>"""


def _fetch(final_url: str):
    def fetch(candidate: probe.ProbeCandidate):
        return {
            "retrieval_started_at": "2026-07-24T00:00:00+00:00",
            "retrieval_completed_at": "2026-07-24T00:00:01+00:00",
            "attempt_number": 1,
            "status_code": 200,
            "final_url": final_url,
            "headers": {"content-type": "text/html"},
            "redirect_chain": [],
            "raw_bytes": GLOBAL_HTML,
        }

    return fetch


def _run(tmp_path: Path, *, final_url: str):
    return run_venue_preflight(
        tmp_path,
        venue_label="test-neutral-venue",
        execution_mode="LOCAL_USER_CONTROLLED",
        implementation_sha=IMPLEMENTATION_SHA,
        source_commit_sha=SOURCE_COMMIT_SHA,
        validated_pr_merge_ref=MERGE_REF,
        environ={},
        fetch_candidate=_fetch(final_url),
    )


def _review(tmp_path: Path):
    return review_venue_preflight(
        tmp_path,
        expected_implementation_sha=IMPLEMENTATION_SHA,
        expected_source_commit_sha=SOURCE_COMMIT_SHA,
        expected_validated_pr_merge_ref=MERGE_REF,
    )


def test_clean_venue_global_probe_passes_independent_review(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)

    attestation, result, probe_review, manifest = _run(
        tmp_path,
        final_url=CATEGORY_PROBE_URL,
    )
    venue_review = _review(tmp_path)

    assert attestation["status"] == "PREPARED_NOT_AUTHORIZED"
    assert attestation["proxy_environment_keys_present"] == []
    assert result["status"] == "PASS"
    assert probe_review["status"] == "PASS"
    assert venue_review["status"] == "PASS"
    assert venue_review["venue_status_recomputed"] == "ACCEPTED_FOR_BOUNDED_PREFLIGHT"
    assert venue_review["probe_status_recomputed"] == "PASS"
    assert venue_review["third_full_capture_authorized"] is False
    assert manifest["file_count"] == 11


def test_clean_venue_regional_substitution_is_valid_fail_closed_result(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)

    _attestation, result, probe_review, _manifest = _run(
        tmp_path,
        final_url="https://www.okx.com/en-us/help/category/announcements",
    )
    venue_review = _review(tmp_path)

    assert result["status"] == "FAIL"
    assert result["result"] == "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
    assert probe_review["status"] == "PASS"
    assert probe_review["probe_status_recomputed"] == "FAIL"
    assert venue_review["status"] == "PASS"
    assert venue_review["probe_status_recomputed"] == "FAIL"
    assert venue_review["probe_result_recomputed"] == "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"


def test_preflight_rejects_proxy_environment_before_network(tmp_path: Path) -> None:
    with pytest.raises(SourceAuthorityError, match="prohibited proxy environment state"):
        run_venue_preflight(
            tmp_path,
            venue_label="proxied-venue",
            execution_mode="LOCAL_USER_CONTROLLED",
            implementation_sha=IMPLEMENTATION_SHA,
            source_commit_sha=SOURCE_COMMIT_SHA,
            validated_pr_merge_ref=MERGE_REF,
            environ={"HTTPS_PROXY": "http://127.0.0.1:8080"},
            fetch_candidate=lambda _candidate: pytest.fail("network fetch must not run"),
        )


def test_venue_reviewer_rejects_attestation_tamper(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    _run(tmp_path, final_url=CATEGORY_PROBE_URL)

    path = tmp_path / "venue_attestation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["live_state"] = "LIVE_ALLOWED"
    path.write_text(json.dumps(payload), encoding="utf-8")

    venue_review = _review(tmp_path)

    assert venue_review["status"] == "FAIL"
    assert "venue live-state drift" in venue_review["errors"]
