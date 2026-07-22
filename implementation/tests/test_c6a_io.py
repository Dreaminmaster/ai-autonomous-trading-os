from __future__ import annotations

import json
from pathlib import Path

import pytest

from atos.c6a_contract import C6AError
from atos.c6a_io import _output_map, _verified_rows, load_canonical_inputs, read_jsonl


def test_read_jsonl_rejects_empty_and_invalid_rows(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text('{"x":1}\n{"x":2}\n', encoding="utf-8")
    assert read_jsonl(path) == [{"x": 1}, {"x": 2}]

    path.write_text("", encoding="utf-8")
    with pytest.raises(C6AError, match="empty"):
        read_jsonl(path)

    path.write_text("not-json\n", encoding="utf-8")
    with pytest.raises(C6AError, match="invalid canonical JSONL"):
        read_jsonl(path)


def test_output_map_rejects_duplicate_keys() -> None:
    report = {
        "outputs": [
            {"kind": "funding_history", "instrument": "ALL"},
            {"kind": "funding_history", "instrument": "ALL"},
        ]
    }
    with pytest.raises(C6AError, match="duplicate"):
        _output_map(report)


def test_verified_rows_checks_size_hash_and_count(tmp_path: Path) -> None:
    path = tmp_path / "rows.jsonl"
    path.write_text('{"x":1}\n', encoding="utf-8")
    import hashlib

    row = {
        "path": str(path),
        "size": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "row_count": 1,
    }
    assert _verified_rows(row) == [{"x": 1}]
    with pytest.raises(C6AError, match="row-count"):
        _verified_rows({**row, "row_count": 2})
    with pytest.raises(C6AError, match="SHA-256"):
        _verified_rows({**row, "sha256": "0" * 64})


def test_loader_rejects_nonpass_or_open_safety_before_files() -> None:
    with pytest.raises(C6AError, match="identity/status"):
        load_canonical_inputs({"schema_version": 1, "stage": "C6A", "status": "FAIL"})
    with pytest.raises(C6AError, match="safety-state"):
        load_canonical_inputs(
            {
                "schema_version": 1,
                "stage": "C6A",
                "status": "PASS",
                "economic_boundary_exclusive": "2025-12-29T00:00:00Z",
                "c6b_state": "OPEN",
                "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
                "live": "FORBIDDEN",
                "outputs": [],
            }
        )
