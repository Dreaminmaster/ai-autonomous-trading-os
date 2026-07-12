"""Simple CI evidence tests."""
import json
from unittest.mock import patch

import pytest

from atos.simple_ci_evidence import verify_simple_ci_for_sha


def _mock(wf_runs, pr_data=None):
    workflows = {
        "workflows": [
            {
                "id": 99,
                "path": ".github/workflows/ci.yml",
                "name": "CI",
                "state": "active",
            }
        ]
    }

    def fake(request, *args, **kwargs):
        url = request.full_url
        if url.endswith("/actions/workflows"):
            payload = workflows
        elif "/actions/workflows/99/runs?" in url:
            payload = wf_runs
        elif "/pulls/" in url and pr_data is not None:
            payload = pr_data
        else:
            raise AssertionError(f"unexpected URL: {url}")

        class Response:
            def read(self):
                return json.dumps(payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *unused):
                return None

        return Response()

    return fake


def _run(sha="abc123def", **overrides):
    data = {
        "name": "CI",
        "status": "completed",
        "conclusion": "success",
        "id": 123,
        "head_sha": sha,
        "event": "push",
        "pull_requests": [],
        "created_at": "2026-01-01",
    }
    data.update(overrides)
    return data


def test_success_exact_sha():
    runs = {"workflow_runs": [_run()]}
    with patch("atos.simple_ci_evidence.urllib.request.urlopen", _mock(runs)):
        result = verify_simple_ci_for_sha(
            "abc123def", token="x", run_event="push"
        )
    assert result["verified"] is True
    assert result["workflow_id"] == 99
    assert result["head_sha"] == "abc123def"
    assert result["run_head_sha"] == "abc123def"
    assert result["provenance_mode"] == "exact_sha"
    assert result["merge_commit_verified"] is False


def test_event_filter_disambiguates_push_and_pull_request_runs():
    runs = {
        "workflow_runs": [
            _run(id=1, event="push"),
            _run(id=2, event="pull_request", pull_requests=[{"number": 23}]),
        ]
    }
    with patch("atos.simple_ci_evidence.urllib.request.urlopen", _mock(runs)):
        result = verify_simple_ci_for_sha(
            "abc123def", token="x", run_event="push"
        )
    assert result["run_id"] == 1
    assert result["event"] == "push"


def test_success_pull_request_merge_ref():
    source_sha = "a" * 40
    merge_sha = "b" * 40
    runs = {
        "workflow_runs": [
            _run(
                sha=source_sha,
                event="pull_request",
                pull_requests=[{"number": 23}],
            )
        ]
    }
    pr_data = {
        "number": 23,
        "head": {"sha": source_sha},
        "merge_commit_sha": merge_sha,
    }
    with patch(
        "atos.simple_ci_evidence.urllib.request.urlopen", _mock(runs, pr_data)
    ):
        result = verify_simple_ci_for_sha(
            merge_sha,
            token="x",
            run_head_sha=source_sha,
            pr_number=23,
            run_event="pull_request",
        )
    assert result["verified"] is True
    assert result["head_sha"] == merge_sha
    assert result["run_head_sha"] == source_sha
    assert result["pr_number"] == 23
    assert result["provenance_mode"] == "pull_request_merge_ref"
    assert result["merge_commit_verified"] is True


def test_pull_request_merge_ref_requires_pr_number():
    with pytest.raises(RuntimeError, match="pr_number required"):
        verify_simple_ci_for_sha(
            "b" * 40,
            token="x",
            run_head_sha="a" * 40,
            run_event="pull_request",
        )


def test_pull_request_merge_ref_requires_pull_request_event():
    with pytest.raises(RuntimeError, match="pull_request event required"):
        verify_simple_ci_for_sha(
            "b" * 40,
            token="x",
            run_head_sha="a" * 40,
            pr_number=23,
            run_event="push",
        )


def test_pull_request_merge_ref_rejects_wrong_pr_head():
    source_sha = "a" * 40
    merge_sha = "b" * 40
    runs = {
        "workflow_runs": [
            _run(
                sha=source_sha,
                event="pull_request",
                pull_requests=[{"number": 23}],
            )
        ]
    }
    pr_data = {
        "number": 23,
        "head": {"sha": "c" * 40},
        "merge_commit_sha": merge_sha,
    }
    with patch(
        "atos.simple_ci_evidence.urllib.request.urlopen", _mock(runs, pr_data)
    ):
        with pytest.raises(RuntimeError, match="PR head_sha mismatch"):
            verify_simple_ci_for_sha(
                merge_sha,
                token="x",
                run_head_sha=source_sha,
                pr_number=23,
                run_event="pull_request",
            )


def test_pull_request_merge_ref_rejects_wrong_merge_sha():
    source_sha = "a" * 40
    merge_sha = "b" * 40
    runs = {
        "workflow_runs": [
            _run(
                sha=source_sha,
                event="pull_request",
                pull_requests=[{"number": 23}],
            )
        ]
    }
    pr_data = {
        "number": 23,
        "head": {"sha": source_sha},
        "merge_commit_sha": "c" * 40,
    }
    with patch(
        "atos.simple_ci_evidence.urllib.request.urlopen", _mock(runs, pr_data)
    ):
        with pytest.raises(RuntimeError, match="PR merge_commit_sha mismatch"):
            verify_simple_ci_for_sha(
                merge_sha,
                token="x",
                run_head_sha=source_sha,
                pr_number=23,
                run_event="pull_request",
            )


def test_missing():
    _check_failure({"workflow_runs": []})


def test_wrong_sha():
    _check_failure({"workflow_runs": [_run(sha="DIFFERENT")]})


def test_pending():
    _check_failure(
        {"workflow_runs": [_run(status="in_progress", conclusion=None)]}
    )


def test_failure():
    _check_failure({"workflow_runs": [_run(conclusion="failure")]})


def test_cancelled():
    _check_failure({"workflow_runs": [_run(conclusion="cancelled")]})


def test_ambiguous():
    _check_failure(
        {"workflow_runs": [_run(id=1), _run(id=2)]}
    )


def _check_failure(runs):
    with patch("atos.simple_ci_evidence.urllib.request.urlopen", _mock(runs)):
        with pytest.raises(RuntimeError):
            verify_simple_ci_for_sha("abc123def", token="x")


def test_api_error():
    error = RuntimeError("API down")

    def fail(*args, **kwargs):
        raise error

    with patch("atos.simple_ci_evidence.urllib.request.urlopen", fail):
        with pytest.raises(RuntimeError):
            verify_simple_ci_for_sha("abc123def", token="x")


def test_invalid_sha():
    with pytest.raises(RuntimeError):
        verify_simple_ci_for_sha("short", token="x")


def test_invalid_run_head_sha():
    with pytest.raises(RuntimeError):
        verify_simple_ci_for_sha(
            "abc123def", token="x", run_head_sha="short"
        )


def test_invalid_pr_number():
    with pytest.raises(RuntimeError):
        verify_simple_ci_for_sha(
            "b" * 40,
            token="x",
            run_head_sha="a" * 40,
            pr_number=0,
            run_event="pull_request",
        )
