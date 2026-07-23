from __future__ import annotations

from pathlib import Path

import atos.c6a_source_authority as core
import atos.c6a_source_authority_attempt as attempt
import atos.c6a_source_authority_attempt_review as attempt_review
import atos.c6a_source_authority_execution as execution
import atos.c6a_source_authority_gate as gate
import atos.c6a_source_authority_independent as independent
import atos.c6a_source_authority_package as package


def test_execution_binds_global_scope_and_restores_originals(
    monkeypatch, tmp_path: Path
) -> None:
    original_capture = attempt.capture_request
    original_parser = attempt.parse_announcement_catalog
    original_review = package.review_package
    original_loader = attempt.load_frozen_inventory
    original_mapper = attempt._failure_for_exception
    original_priorities = (
        core.FAILURE_PRIORITY,
        attempt.FAILURE_PRIORITY,
        gate.FAILURE_PRIORITY,
        independent.FAILURE_PRIORITY,
        attempt_review.FAILURE_PRIORITY,
    )
    observed = {}
    inventory = Path(__file__).parents[1] / "config" / "c6a_source_authority_query_inventory_v1.json"

    def strict_stub(*args, **kwargs):
        observed["strict_args"] = args
        observed["strict_kwargs"] = kwargs
        return "CAPTURED"

    def attempt_stub(**kwargs):
        observed["capture_binding"] = attempt.capture_request
        observed["parser_binding"] = attempt.parse_announcement_catalog
        observed["review_binding"] = package.review_package
        observed["loader_binding"] = attempt.load_frozen_inventory
        observed["mapper_binding"] = attempt._failure_for_exception
        observed["priorities"] = (
            core.FAILURE_PRIORITY,
            attempt.FAILURE_PRIORITY,
            gate.FAILURE_PRIORITY,
            independent.FAILURE_PRIORITY,
            attempt_review.FAILURE_PRIORITY,
        )
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
        pr_merge_ref="refs/pull/69/merge@deadbeef",
    )

    assert result == {"status": "DONE"}
    assert observed["capture_binding"] is not original_capture
    assert observed["parser_binding"] is execution._global_catalog_parser
    assert observed["review_binding"] is execution.review_package_with_attempt_diagnostics
    assert observed["loader_binding"] is not original_loader
    assert observed["mapper_binding"] is not original_mapper
    assert all("FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT" in priority for priority in observed["priorities"])
    assert observed["capture_result"] == "CAPTURED"
    assert observed["strict_args"] == ("request",)
    assert observed["kwargs"]["source_commit_sha"] == "a" * 40
    assert attempt.capture_request is original_capture
    assert attempt.parse_announcement_catalog is original_parser
    assert package.review_package is original_review
    assert attempt.load_frozen_inventory is original_loader
    assert attempt._failure_for_exception is original_mapper
    assert (
        core.FAILURE_PRIORITY,
        attempt.FAILURE_PRIORITY,
        gate.FAILURE_PRIORITY,
        independent.FAILURE_PRIORITY,
        attempt_review.FAILURE_PRIORITY,
    ) == original_priorities
