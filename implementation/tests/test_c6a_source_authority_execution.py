from __future__ import annotations

import json
from pathlib import Path

import atos.c6a_source_authority_attempt as attempt
import atos.c6a_source_authority_execution as execution
import atos.c6a_source_authority_package as package


def test_execution_binds_strict_remediations_and_restores_originals(
    monkeypatch, tmp_path: Path
) -> None:
    original_capture = attempt.capture_request
    original_parser = attempt.parse_announcement_catalog
    original_review = package.review_package
    observed = {}
    inventory = tmp_path / "inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "rate_limit_policy": {
                    "minimum_interval_seconds": 0,
                    "maximum_requests_per_minute": 60,
                }
            }
        ),
        encoding="utf-8",
    )

    def strict_stub(*args, **kwargs):
        observed["strict_args"] = args
        observed["strict_kwargs"] = kwargs
        return "CAPTURED"

    def attempt_stub(**kwargs):
        observed["capture_binding"] = attempt.capture_request
        observed["parser_binding"] = attempt.parse_announcement_catalog
        observed["review_binding"] = package.review_package
        observed["capture_result"] = attempt.capture_request(
            "request", output_root=tmp_path / "artifact"
        )
        observed["kwargs"] = kwargs
        return {"status": "DONE"}

    monkeypatch.setattr(execution, "strict_capture_request", strict_stub)
    monkeypatch.setattr(attempt, "run_source_authority_attempt", attempt_stub)
    result = execution.run_strict_source_authority_attempt(
        inventory_path=inventory,
        output_root=tmp_path / "artifact",
        source_commit_sha="a" * 40,
        pr_merge_ref="refs/pull/61/merge@deadbeef",
    )

    assert result == {"status": "DONE"}
    assert observed["capture_binding"] is not original_capture
    assert observed["parser_binding"] is execution.parse_announcement_catalog
    assert observed["review_binding"] is execution.review_package_with_attempt_diagnostics
    assert observed["capture_result"] == "CAPTURED"
    assert observed["strict_args"] == ("request",)
    assert observed["kwargs"]["source_commit_sha"] == "a" * 40
    assert attempt.capture_request is original_capture
    assert attempt.parse_announcement_catalog is original_parser
    assert package.review_package is original_review
