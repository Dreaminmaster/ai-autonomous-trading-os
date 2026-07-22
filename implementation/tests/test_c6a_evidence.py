from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import pytest

from atos.c6a_contract import C6AError
from atos.c6a_evidence import (
    COST_LABELS,
    POLICY_IDS,
    WINDOW_IDS,
    build_manifest,
    manifest_payload,
    validate_decision,
    validate_result_matrix,
    verify_manifest,
)


def result_matrix() -> list[dict]:
    return [
        {
            "status": "PASS",
            "policy_id": policy,
            "cost_label": cost,
            "window_id": window,
            "weekly_buckets": [{} for _ in range(26)],
            "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
            "holdout_state": "HOLDOUT_CLOSED",
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live": "FORBIDDEN",
        }
        for policy in POLICY_IDS
        for cost in COST_LABELS
        for window in WINDOW_IDS
    ]


def test_exact_sixty_cell_result_matrix() -> None:
    report = validate_result_matrix(result_matrix())
    assert report["status"] == "PASS"
    assert report["result_cell_count"] == 60
    assert report["policy_count"] == 4
    assert report["cost_count"] == 3
    assert report["window_count"] == 5


def test_result_matrix_rejects_missing_duplicate_or_safety_drift() -> None:
    rows = result_matrix()
    with pytest.raises(C6AError, match="60 cells"):
        validate_result_matrix(rows[:-1])

    rows = result_matrix()
    rows[-1] = dict(rows[0])
    with pytest.raises(C6AError, match="duplicate"):
        validate_result_matrix(rows)

    rows = result_matrix()
    rows[0]["live"] = "OPEN"
    with pytest.raises(C6AError, match="safety-state"):
        validate_result_matrix(rows)


def test_manifest_hashes_sizes_and_paths(tmp_path: Path) -> None:
    (tmp_path / "a.json").write_text("{}", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.txt").write_text("evidence", encoding="utf-8")
    entries = build_manifest(tmp_path)
    assert [entry.path for entry in entries] == ["a.json", "nested/b.txt"]
    verify_manifest(tmp_path, entries)
    payload = manifest_payload(entries)
    assert payload["entry_count"] == 2
    assert payload["live"] == "FORBIDDEN"

    (nested / "b.txt").write_text("tampered", encoding="utf-8")
    with pytest.raises(C6AError, match="size mismatch|SHA-256 mismatch"):
        verify_manifest(tmp_path, entries)


def test_manifest_rejects_path_escape(tmp_path: Path) -> None:
    inside = tmp_path / "inside.txt"
    inside.write_text("inside", encoding="utf-8")
    outside = tmp_path.parent / "outside-c6a.txt"
    outside.write_text("outside", encoding="utf-8")
    try:
        with pytest.raises(C6AError, match="escapes root"):
            build_manifest(tmp_path, relative_paths=["../outside-c6a.txt"])
    finally:
        outside.unlink(missing_ok=True)


def test_decision_state_and_selected_policy_are_fail_closed() -> None:
    base = {
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }
    validate_decision(
        {
            **base,
            "status": "SELECTED",
            "selected_policy": "C6AMarketNeutralFundingCarry",
        }
    )
    validate_decision({**base, "status": "REJECTED", "selected_policy": None})
    with pytest.raises(C6AError, match="null"):
        validate_decision(
            {
                **base,
                "status": "REJECTED",
                "selected_policy": "C6AMarketNeutralFundingCarry",
            }
        )
