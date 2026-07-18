from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.c3a_evidence as evidence
import scripts.c3a_source_inventory as inventory
import scripts.finalize_c3a_evidence as finalizer


EXACT_SHA = "1" * 40
MERGE_SHA = "2" * 40


def test_source_inventory_is_exact_and_contains_no_active_workflow() -> None:
    assert len(inventory.SOURCE_PATHS) == 13
    assert len(set(inventory.SOURCE_PATHS)) == 13
    assert not any(path.startswith(".github/workflows/") for path in inventory.SOURCE_PATHS)
    payload = inventory.build_inventory(EXACT_SHA)
    assert payload["status"] == "PASS"
    assert payload["source_head_sha"] == EXACT_SHA
    assert payload["file_count"] == 13
    assert payload["confirmation_opened"] is False
    assert payload["holdout_state"] == "HOLDOUT_CLOSED"
    assert payload["live"] == "FORBIDDEN"


def test_evidence_exact_sha_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("C3A_SOURCE_SHA", "not-a-sha")
    with pytest.raises(evidence.C3AEvidenceError, match="exact lowercase"):
        evidence.exact_sha("C3A_SOURCE_SHA")
    monkeypatch.setenv("C3A_SOURCE_SHA", EXACT_SHA)
    assert evidence.exact_sha("C3A_SOURCE_SHA") == EXACT_SHA


def test_manifest_binds_every_retained_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(evidence, "RESULTS", tmp_path)
    (tmp_path / "nested").mkdir()
    (tmp_path / "alpha.json").write_text("{}", encoding="utf-8")
    (tmp_path / "nested/beta.json").write_text('{"ok": true}', encoding="utf-8")
    (tmp_path / "manifest.json").write_text("ignored", encoding="utf-8")
    manifest = evidence.build_manifest(EXACT_SHA, MERGE_SHA)
    assert manifest["source_head_sha"] == EXACT_SHA
    assert manifest["merge_ref_sha"] == MERGE_SHA
    assert manifest["file_count"] == 2
    assert {item["path"] for item in manifest["files"]} == {"alpha.json", "nested/beta.json"}
    assert manifest["holdout_state"] == "HOLDOUT_CLOSED"
    assert manifest["live"] == "FORBIDDEN"


def test_finalizer_requires_exactly_63_hash_bound_pointers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(finalizer, "RESULTS", tmp_path)
    for index in range(63):
        directory = tmp_path / "cells" / f"cell-{index:02d}"
        directory.mkdir(parents=True)
        result_path = directory / "result.json"
        result_path.write_text(json.dumps({"index": index}), encoding="utf-8")
        digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
        (directory / ".last_result.json").write_text(
            json.dumps({"latest": "result.json", "sha256": digest}),
            encoding="utf-8",
        )
    checks: list[str] = []
    finalizer.verify_pointers(checks)
    assert checks == ["pointers:63", "exports:63"]

    pointer = tmp_path / "cells/cell-00/.last_result.json"
    pointer.write_text(json.dumps({"latest": "result.json", "sha256": "0" * 64}), encoding="utf-8")
    with pytest.raises(finalizer.C3AFinalizerError, match="hash mismatch"):
        finalizer.verify_pointers([])
