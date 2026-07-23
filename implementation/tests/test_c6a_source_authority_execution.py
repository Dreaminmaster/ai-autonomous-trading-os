from __future__ import annotations

from pathlib import Path

import atos.c6a_source_authority_attempt as attempt
import atos.c6a_source_authority_execution as execution


def test_execution_binds_strict_transport_and_restores_original(monkeypatch, tmp_path: Path) -> None:
    original = attempt.capture_request
    observed = {}

    def strict_stub(*args, **kwargs):  # pragma: no cover - identity only
        raise AssertionError("not expected to perform network capture")

    def attempt_stub(**kwargs):
        observed["capture"] = attempt.capture_request
        observed["kwargs"] = kwargs
        return {"status": "DONE"}

    monkeypatch.setattr(execution, "strict_capture_request", strict_stub)
    monkeypatch.setattr(attempt, "run_source_authority_attempt", attempt_stub)
    result = execution.run_strict_source_authority_attempt(
        inventory_path=tmp_path / "inventory.json",
        output_root=tmp_path / "artifact",
        source_commit_sha="a" * 40,
        pr_merge_ref="refs/pull/61/merge@deadbeef",
    )

    assert result == {"status": "DONE"}
    assert observed["capture"] is strict_stub
    assert observed["kwargs"]["source_commit_sha"] == "a" * 40
    assert attempt.capture_request is original
