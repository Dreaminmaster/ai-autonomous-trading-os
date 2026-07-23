from __future__ import annotations

from pathlib import Path

import atos.c6a_source_scope_category_execution as execution
import atos.c6a_source_scope_probe as probe
import atos.c6a_source_scope_probe_independent as independent


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
            "retrieval_started_at": "2026-07-23T00:00:00+00:00",
            "retrieval_completed_at": "2026-07-23T00:00:01+00:00",
            "attempt_number": 1,
            "status_code": 200,
            "final_url": final_url,
            "headers": {"content-type": "text/html"},
            "redirect_chain": [],
            "raw_bytes": GLOBAL_HTML,
        }

    return fetch


def test_category_probe_passes_and_restores_bindings(monkeypatch, tmp_path: Path) -> None:
    original_probe_url = probe.PROBE_URL
    original_review_url = independent.PROBE_URL
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)

    result, review, manifest = execution.run_category_scope_probe(
        tmp_path,
        fetch_candidate=_fetch(execution.CATEGORY_PROBE_URL),
    )

    assert result["status"] == "PASS"
    assert result["result"] == "PASS"
    assert result["probe_url"] == execution.CATEGORY_PROBE_URL
    assert result["reproducible_passing_profiles"] == [
        "control-atos-minimal",
        "browser-neutral-en",
        "browser-en-us",
        "browser-en-gb",
    ]
    assert review["status"] == "PASS"
    assert review["probe_status_recomputed"] == "PASS"
    assert review["reproducible_passing_profiles"] == result["reproducible_passing_profiles"]
    assert manifest["file_count"] == 10
    assert probe.PROBE_URL == original_probe_url
    assert independent.PROBE_URL == original_review_url


def test_category_probe_fails_closed_on_regional_substitution(
    monkeypatch, tmp_path: Path
) -> None:
    original_probe_url = probe.PROBE_URL
    original_review_url = independent.PROBE_URL
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)

    result, review, _manifest = execution.run_category_scope_probe(
        tmp_path,
        fetch_candidate=_fetch("https://www.okx.com/en-us/help/category/announcements"),
    )

    assert result["status"] == "FAIL"
    assert result["result"] == "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
    assert result["reproducible_passing_profiles"] == []
    assert review["status"] == "PASS"
    assert review["probe_status_recomputed"] == "FAIL"
    assert review["probe_result_recomputed"] == "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
    assert probe.PROBE_URL == original_probe_url
    assert independent.PROBE_URL == original_review_url
