from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import c6a_pack_final_evidence as packer


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def record(path: Path) -> dict:
    return {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "status": "PASS",
    }


def fixture(tmp_path: Path) -> dict[str, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source_sha = "a" * 40
    raw = tmp_path / "raw.zip"
    raw.write_bytes(b"raw public bytes")
    canonical = tmp_path / "canonical.jsonl"
    canonical.write_text('{"x":1}\n', encoding="utf-8")
    download_path = tmp_path / "download.json"
    prepare_path = tmp_path / "prepare.json"
    inventory_path = tmp_path / "inventory.json"
    finalizer_path = tmp_path / "finalizer.json"
    snapshot = tmp_path / "snapshot"
    results = tmp_path / "results"
    snapshot.mkdir()
    results.mkdir()
    (snapshot / "source.py").write_text("pass\n", encoding="utf-8")
    (results / "decision.json").write_text("{}", encoding="utf-8")
    raw_row = {
        **record(raw),
        "source_id": "raw-one",
    }
    canonical_row = {
        **record(canonical),
        "kind": "funding_history",
        "instrument": "ALL",
        "row_count": 1,
    }
    write_json(
        download_path,
        {
            "status": "PASS",
            "program_guard": {"status": "PASS", "source_head_sha": source_sha},
            "sources": [raw_row],
        },
    )
    write_json(
        prepare_path,
        {"status": "PASS", "outputs": [canonical_row]},
    )
    write_json(
        inventory_path,
        {
            "status": "PASS",
            "source_head_sha": source_sha,
            "snapshot_file_count": 1,
        },
    )
    write_json(
        finalizer_path,
        {
            "status": "PASS",
            "source_head_sha": source_sha,
            "cell_check_count": 60,
            "aggregate_check_count": 12,
            "weekly_row_count": 1560,
            "decision_row_count": 780,
            "economic_result": "REJECTED",
            "selected_policy": None,
        },
    )
    return {
        "download_report_path": download_path,
        "prepare_report_path": prepare_path,
        "source_inventory_path": inventory_path,
        "source_snapshot_path": snapshot,
        "results_path": results,
        "finalizer_path": finalizer_path,
        "output_path": tmp_path / "package",
    }


def test_pack_copies_raw_canonical_source_results_and_complete_manifest(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    summary = packer.pack(**paths)
    output = paths["output_path"]
    assert summary["status"] == "PASS"
    assert summary["economic_result"] == "REJECTED"
    assert summary["selected_policy"] is None
    assert summary["public_raw_object_count"] == 1
    assert summary["canonical_object_count"] == 1
    assert summary["manifest_entry_count"] >= 8
    assert (output / "public_raw/raw-one.zip").read_bytes() == b"raw public bytes"
    assert (output / "canonical/funding_history/ALL.jsonl").is_file()
    assert (output / "source_snapshot/source.py").is_file()
    assert (output / "production_results/decision.json").is_file()
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "PASS"
    assert manifest["entry_count"] == summary["manifest_entry_count"]


def test_pack_rejects_sha_or_evidence_count_drift(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    download = json.loads(paths["download_report_path"].read_text(encoding="utf-8"))
    download["sources"][0]["sha256"] = "0" * 64
    write_json(paths["download_report_path"], download)
    with pytest.raises(packer.C6APackError, match="hash/size mismatch"):
        packer.pack(**paths)

    paths = fixture(tmp_path / "second")
    finalizer = json.loads(paths["finalizer_path"].read_text(encoding="utf-8"))
    finalizer["decision_row_count"] = 779
    write_json(paths["finalizer_path"], finalizer)
    with pytest.raises(packer.C6APackError, match="counts are incomplete"):
        packer.pack(**paths)


def test_pack_rejects_raw_and_canonical_destination_traversal(tmp_path: Path) -> None:
    paths = fixture(tmp_path)
    download = json.loads(paths["download_report_path"].read_text(encoding="utf-8"))
    download["sources"][0]["source_id"] = "../escape"
    write_json(paths["download_report_path"], download)
    with pytest.raises(packer.C6APackError, match="unsafe source_id"):
        packer.pack(**paths)
    assert not (tmp_path / "escape.zip").exists()

    paths = fixture(tmp_path / "canonical")
    prepare = json.loads(paths["prepare_report_path"].read_text(encoding="utf-8"))
    prepare["outputs"][0]["kind"] = "../escape"
    write_json(paths["prepare_report_path"], prepare)
    with pytest.raises(packer.C6APackError, match="unsafe canonical kind"):
        packer.pack(**paths)
    assert not (tmp_path / "canonical/escape/ALL.jsonl").exists()
