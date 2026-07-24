from __future__ import annotations

import json
import socket
import ssl
from pathlib import Path
from urllib.error import URLError

import pytest

import atos.c6a_source_scope_probe as probe
import atos.c6a_source_scope_probe_independent as probe_independent
from atos.c6a_source_authority import SourceAuthorityError
from atos.c6a_source_scope_category_execution import CATEGORY_PROBE_URL
from atos.c6a_source_scope_venue_preflight import (
    begin_invocation,
    invocation_marker_path,
    run_venue_preflight,
)
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


def _output(tmp_path: Path) -> Path:
    return tmp_path / "evidence"


def _begin(output: Path) -> None:
    begin_invocation(
        output,
        venue_label="test-neutral-venue",
        execution_mode="LOCAL_USER_CONTROLLED",
        implementation_sha=IMPLEMENTATION_SHA,
        source_commit_sha=SOURCE_COMMIT_SHA,
        validated_pr_merge_ref=MERGE_REF,
    )


def _run(tmp_path: Path, *, final_url: str | None = None, fetch_candidate=None):
    output = _output(tmp_path)
    _begin(output)
    if fetch_candidate is None:
        assert final_url is not None
        fetch_candidate = _fetch(final_url)
    result = run_venue_preflight(
        output,
        venue_label="test-neutral-venue",
        execution_mode="LOCAL_USER_CONTROLLED",
        implementation_sha=IMPLEMENTATION_SHA,
        source_commit_sha=SOURCE_COMMIT_SHA,
        validated_pr_merge_ref=MERGE_REF,
        environ={},
        fetch_candidate=fetch_candidate,
    )
    return output, result


def _review(output: Path):
    return review_venue_preflight(
        output,
        expected_implementation_sha=IMPLEMENTATION_SHA,
        expected_source_commit_sha=SOURCE_COMMIT_SHA,
        expected_validated_pr_merge_ref=MERGE_REF,
    )


def test_clean_venue_global_probe_passes_independent_review(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)

    output, (attestation, result, probe_review, manifest) = _run(
        tmp_path,
        final_url=CATEGORY_PROBE_URL,
    )
    venue_review = _review(output)

    assert attestation["status"] == "PREPARED_NOT_AUTHORIZED"
    assert attestation["proxy_environment_keys_present"] == []
    assert attestation["invocation_record_sha256"]
    assert result["status"] == "PASS"
    assert result["failed_candidate_count"] == 0
    assert probe_review["status"] == "PASS"
    assert venue_review["status"] == "PASS"
    assert venue_review["venue_status_recomputed"] == "ACCEPTED_FOR_BOUNDED_PREFLIGHT"
    assert venue_review["probe_status_recomputed"] == "PASS"
    assert venue_review["third_full_capture_authorized"] is False
    assert manifest["file_count"] == 13


def test_clean_venue_regional_substitution_is_valid_fail_closed_result(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)

    output, (_attestation, result, probe_review, _manifest) = _run(
        tmp_path,
        final_url="https://www.okx.com/en-us/help/category/announcements",
    )
    venue_review = _review(output)

    assert result["status"] == "FAIL"
    assert result["result"] == "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
    assert result["failed_candidate_count"] == 0
    assert probe_review["status"] == "PASS"
    assert probe_review["probe_status_recomputed"] == "FAIL"
    assert venue_review["status"] == "PASS"
    assert venue_review["venue_status_recomputed"] == "ACCEPTED_FOR_BOUNDED_PREFLIGHT"
    assert venue_review["probe_status_recomputed"] == "FAIL"
    assert venue_review["probe_result_recomputed"] == "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"


@pytest.mark.parametrize(
    "transport_error",
    [
        BrokenPipeError("broken pipe"),
        ConnectionResetError("reset"),
        TimeoutError("timeout"),
        URLError("unreachable"),
        socket.gaierror("dns"),
        ssl.SSLError("tls"),
    ],
)
def test_transport_failure_has_no_scope_decision(
    monkeypatch, tmp_path: Path, transport_error: BaseException
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)

    def fail(_candidate):
        raise transport_error

    output, (_attestation, result, probe_review, _manifest) = _run(
        tmp_path,
        fetch_candidate=fail,
    )
    venue_review = _review(output)

    assert result["status"] == "ERROR"
    assert result["result"] == "FAIL_SOURCE_SCOPE_PROBE_EXECUTION"
    assert result["failed_candidate_count"] == 8
    assert all(row["scope_status"] == "NOT_EVALUATED" for row in result["candidate_results"])
    assert all(row["final_url"] is None for row in result["candidate_results"])
    assert probe_review["status"] == "PASS"
    assert probe_review["probe_status_recomputed"] == "ERROR"
    assert venue_review["status"] == "PASS"
    assert venue_review["venue_status_recomputed"] == "REJECTED_EXECUTION_FAILURE"


def test_probe_reviewer_rejects_transport_failure_mislabeled_as_scope_drift(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)

    def fail(_candidate):
        raise BrokenPipeError("broken pipe")

    output, _result = _run(tmp_path, fetch_candidate=fail)
    result_path = output / "probe_result.json"
    progress_path = output / "probe_progress.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    progress = json.loads(progress_path.read_text(encoding="utf-8"))
    for container in (result, progress):
        row = container["candidate_results"][0]
        row["execution_status"] = "COMPLETE"
        row["scope_status"] = "FAIL"
        row["failure_code"] = "FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT"
        row.pop("execution_error", None)
    result_path.write_text(json.dumps(result), encoding="utf-8")
    progress_path.write_text(json.dumps(progress), encoding="utf-8")

    review = probe_independent.review_probe(output)

    assert review["status"] == "FAIL"
    assert any("missing response evidence" in error for error in review["errors"])


def test_preflight_rejects_proxy_environment_before_network(tmp_path: Path) -> None:
    output = _output(tmp_path)
    _begin(output)
    with pytest.raises(SourceAuthorityError, match="prohibited proxy environment state"):
        run_venue_preflight(
            output,
            venue_label="test-neutral-venue",
            execution_mode="LOCAL_USER_CONTROLLED",
            implementation_sha=IMPLEMENTATION_SHA,
            source_commit_sha=SOURCE_COMMIT_SHA,
            validated_pr_merge_ref=MERGE_REF,
            environ={"HTTPS_PROXY": "http://127.0.0.1:8080"},
            fetch_candidate=lambda _candidate: pytest.fail("network fetch must not run"),
        )


def test_second_invocation_start_is_rejected(tmp_path: Path) -> None:
    output = _output(tmp_path)
    _begin(output)
    marker = invocation_marker_path(output)
    assert marker.is_file()
    with pytest.raises(SourceAuthorityError, match="output already exists|repeated start rejected"):
        _begin(output)


def test_interruption_retains_invocation_attestation_and_progress(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    output = _output(tmp_path)
    _begin(output)

    def interrupt(_candidate):
        raise KeyboardInterrupt("interrupted")

    with pytest.raises(KeyboardInterrupt):
        run_venue_preflight(
            output,
            venue_label="test-neutral-venue",
            execution_mode="LOCAL_USER_CONTROLLED",
            implementation_sha=IMPLEMENTATION_SHA,
            source_commit_sha=SOURCE_COMMIT_SHA,
            validated_pr_merge_ref=MERGE_REF,
            environ={},
            fetch_candidate=interrupt,
        )

    assert invocation_marker_path(output).is_file()
    assert (output / "invocation_record.json").is_file()
    assert (output / "venue_attestation.json").is_file()
    progress = json.loads((output / "probe_progress.json").read_text(encoding="utf-8"))
    assert progress["state"] == "STARTED"
    assert progress["recorded_candidate_count"] == 0


def test_venue_reviewer_rejects_invocation_record_tamper(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    output, _result = _run(tmp_path, final_url=CATEGORY_PROBE_URL)

    path = output / "invocation_record.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["started_at"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    venue_review = _review(output)

    assert venue_review["status"] == "FAIL"
    assert "venue invocation-record digest mismatch" in venue_review["errors"]


def test_venue_reviewer_rejects_attestation_tamper(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    output, _result = _run(tmp_path, final_url=CATEGORY_PROBE_URL)

    path = output / "venue_attestation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["live_state"] = "LIVE_ALLOWED"
    path.write_text(json.dumps(payload), encoding="utf-8")

    venue_review = _review(output)

    assert venue_review["status"] == "FAIL"
    assert "venue live-state drift" in venue_review["errors"]
