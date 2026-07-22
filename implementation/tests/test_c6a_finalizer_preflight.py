from __future__ import annotations

import json
from pathlib import Path

import pytest

from atos.c6a_evidence import build_manifest, manifest_payload, write_json_atomic
from scripts import c6a_finalizer_preflight as preflight


def write_cell(root: Path, policy: str, cost: str, window: str) -> None:
    decisions = [{} for _ in range(26)] if policy in preflight.DELTA_NEUTRAL else []
    payload = {
        "status": "PASS",
        "policy_id": policy,
        "cost_label": cost,
        "window_id": window,
        "weekly_buckets": [{} for _ in range(26)],
        "decisions": decisions,
        "events": [],
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }
    write_json_atomic(root / "cells" / policy / cost / f"{window}.json", payload)


def fixture(root: Path) -> None:
    for policy in preflight.POLICY_IDS:
        for cost in preflight.COST_LABELS:
            for window in preflight.WINDOW_IDS:
                write_cell(root, policy, cost, window)
            write_json_atomic(
                root / "aggregates" / policy / f"{cost}.json",
                {
                    "status": "PASS",
                    "policy_id": policy,
                    "cost_label": cost,
                },
            )
    write_json_atomic(
        root / "decision.json",
        {
            "status": "REJECTED",
            "selected_policy": None,
            "c6b_state": "C6B_CLOSED",
            "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
            "holdout_state": "HOLDOUT_CLOSED",
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live": "FORBIDDEN",
        },
    )
    entries = build_manifest(root)
    write_json_atomic(root / "manifest.json", manifest_payload(entries))


def rebuild_manifest(root: Path) -> None:
    (root / "manifest.json").unlink(missing_ok=True)
    entries = build_manifest(root)
    write_json_atomic(root / "manifest.json", manifest_payload(entries))


def test_preflight_requires_exact_full_shape(tmp_path: Path) -> None:
    fixture(tmp_path)
    report = preflight.preflight(tmp_path)
    assert report["status"] == "PASS"
    assert report["cell_count"] == 60
    assert report["aggregate_count"] == 12
    assert report["weekly_row_count"] == 1560
    assert report["decision_row_count"] == 780
    assert report["economic_result"] == "REJECTED"
    assert report["selected_policy"] is None


def test_preflight_rejects_missing_week_or_decision_even_with_valid_manifest(
    tmp_path: Path,
) -> None:
    fixture(tmp_path)
    path = (
        tmp_path
        / "cells/C6AMarketNeutralFundingCarry/1.0x/W1.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["weekly_buckets"] = payload["weekly_buckets"][:-1]
    write_json_atomic(path, payload)
    rebuild_manifest(tmp_path)
    with pytest.raises(preflight.C6AFinalizerPreflightError, match="26 weekly"):
        preflight.preflight(tmp_path)

    payload["weekly_buckets"].append({})
    payload["decisions"] = payload["decisions"][:-1]
    write_json_atomic(path, payload)
    rebuild_manifest(tmp_path)
    with pytest.raises(preflight.C6AFinalizerPreflightError, match="decision-row"):
        preflight.preflight(tmp_path)


def test_preflight_rejects_safety_state_drift(tmp_path: Path) -> None:
    fixture(tmp_path)
    decision_path = tmp_path / "decision.json"
    payload = json.loads(decision_path.read_text(encoding="utf-8"))
    payload["live"] = "OPEN"
    write_json_atomic(decision_path, payload)
    rebuild_manifest(tmp_path)
    with pytest.raises(preflight.C6AFinalizerPreflightError, match="safety-state"):
        preflight.preflight(tmp_path)
