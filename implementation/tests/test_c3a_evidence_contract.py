from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import scripts.c3a_evidence as evidence
import scripts.c3a_reference_recompute as reference
import scripts.c3a_source_inventory as inventory
import scripts.complete_c3a_manifest as completer
import scripts.finalize_c3a_evidence as finalizer


EXACT_SHA = "1" * 40
MERGE_SHA = "2" * 40
ROOT = Path(__file__).resolve().parents[2]
ACTIVE_WORKFLOW = ROOT / ".github/workflows/c3a-authoritative-screen.yml"
RESULT_DOCUMENT = (
    ROOT
    / "docs/architecture/phase-c/c3a-residual-mean-reversion/"
    "C3A_RESIDUAL_MEAN_REVERSION_RESULT_V1.md"
)


def test_authoritative_workflow_is_no_longer_active() -> None:
    assert not ACTIVE_WORKFLOW.exists()


def test_result_document_freezes_authoritative_rejection() -> None:
    text = RESULT_DOCUMENT.read_text(encoding="utf-8")
    assert "Economic result: `REJECTED`" in text
    assert "Selected policy: `null`" in text
    assert "Workflow run ID: `29688657555`" in text
    assert "Artifact ID: `8442879943`" in text
    assert "sha256:4079ef14a16969115e0666c2f9527b107a2f797e384197e468107afa34ef3aeb" in text
    assert "Independent artifact audit comment: `5016168856`" in text
    assert "Workflow-only head SHA: `2fa745fabb4f988c71901a64c0e86e191bdaac83`" in text
    assert "C3B_CLOSED" in text
    assert "HOLDOUT_CLOSED" in text
    assert "LIVE_FORBIDDEN" in text


def test_source_inventory_is_exact_and_contains_no_active_workflow() -> None:
    assert len(inventory.SOURCE_PATHS) == 18
    assert len(set(inventory.SOURCE_PATHS)) == 18
    assert not any(path.startswith(".github/workflows/") for path in inventory.SOURCE_PATHS)
    assert "implementation/scripts/c3a_reference_recompute.py" in inventory.SOURCE_PATHS
    assert "implementation/scripts/c3a_contract_guard.py" in inventory.SOURCE_PATHS
    payload = inventory.build_inventory(EXACT_SHA)
    assert payload["status"] == "PASS"
    assert payload["source_head_sha"] == EXACT_SHA
    assert payload["file_count"] == 18
    assert payload["confirmation_opened"] is False
    assert payload["holdout_state"] == "HOLDOUT_CLOSED"
    assert payload["live"] == "FORBIDDEN"


def test_finalizer_uses_separate_reference_model() -> None:
    assert finalizer.reference is reference
    assert reference.__name__.endswith("c3a_reference_recompute")
    assert not hasattr(reference, "run_screen")
    assert hasattr(reference, "reference_run_screen")


def test_evidence_exact_sha_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("C3A_SOURCE_SHA", "not-a-sha")
    with pytest.raises(evidence.C3AEvidenceError, match="exact lowercase"):
        evidence.exact_sha("C3A_SOURCE_SHA")
    monkeypatch.setenv("C3A_SOURCE_SHA", EXACT_SHA)
    assert evidence.exact_sha("C3A_SOURCE_SHA") == EXACT_SHA


def test_independent_compare_allows_only_small_float_roundoff() -> None:
    checks: list[str] = []
    finalizer.require_equal(
        "sample",
        {"value": 1.0, "nested": [2.0, "ok"]},
        {"value": 1.0 + 1e-12, "nested": [2.0 - 1e-12, "ok"]},
        checks,
    )
    assert checks == ["sample:INDEPENDENT_MATCH"]
    with pytest.raises(finalizer.C3AFinalizerError, match="numeric mismatch"):
        finalizer.require_equal("sample", {"value": 1.0}, {"value": 1.01}, [])


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


def test_finalizer_rehashes_inventoried_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "root"
    results = tmp_path / "results"
    source = root / "implementation/example.py"
    source.parent.mkdir(parents=True)
    results.mkdir()
    source.write_text("value = 1\n", encoding="utf-8")
    payload = {
        "status": "PASS",
        "source_head_sha": EXACT_SHA,
        "file_count": 1,
        "files": [{
            "path": "implementation/example.py",
            "size": source.stat().st_size,
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }],
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    (results / "source_inventory.json").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(finalizer, "ROOT", root)
    monkeypatch.setattr(finalizer, "RESULTS", results)
    checks: list[str] = []
    finalizer.verify_source_inventory(EXACT_SHA, checks)
    assert checks == ["source_inventory:1"]
    source.write_text("value = 2\n", encoding="utf-8")
    with pytest.raises(finalizer.C3AFinalizerError, match="hash mismatch"):
        finalizer.verify_source_inventory(EXACT_SHA, [])


def test_final_manifest_must_include_inventory_and_final_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(completer, "RESULTS", tmp_path)
    files = []
    for name, payload in (
        ("source_inventory.json", {"status": "PASS"}),
        ("final_evidence.json", {"status": "PASS"}),
    ):
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        files.append(
            {
                "path": name,
                "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    manifest = {
        "stage": "C3A",
        "source_head_sha": EXACT_SHA,
        "merge_ref_sha": MERGE_SHA,
        "file_count": len(files),
        "files": files,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    completer.verify_final_manifest(manifest, EXACT_SHA, MERGE_SHA)
    manifest["files"] = manifest["files"][:-1]
    manifest["file_count"] = len(manifest["files"])
    with pytest.raises(completer.C3AManifestCompletionError, match="omits final_evidence"):
        completer.verify_final_manifest(manifest, EXACT_SHA, MERGE_SHA)
