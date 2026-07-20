from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import c4a_evidence as evidence
from scripts import c4a_finalizer_core as finalizer
from scripts import c4a_source_inventory as inventory

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c4a_large_liquid_cross_sectional_momentum.json"
EXPECTED_CONFIG_SHA256 = "14e7b96d1167afad6b23c1bc6302e7f9b86ad291f956944ba8f546908402fa92"


def test_canonical_config_hash_and_safety_state_are_frozen() -> None:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert hashlib.sha256(canonical.encode("utf-8")).hexdigest() == EXPECTED_CONFIG_SHA256
    assert payload["confirmation_opened"] is False
    assert payload["holdout_state"] == "HOLDOUT_CLOSED"
    assert payload["live"] == "FORBIDDEN"


def _fake_screen() -> dict[str, Any]:
    policies = list(evidence.POLICIES)
    windows = ("S1", "S2", "S3")
    costs = list(evidence.COST_LABELS)
    policy_rows = []
    for policy in policies:
        for window in windows:
            for cost in costs:
                signals = []
                if cost == "1.0x":
                    decision_count = 14 if window == "S3" else 13
                    for index in range(decision_count):
                        signals.append(
                            {
                                "execution_time": f"2024-01-{index + 1:02d}T00:00:00+00:00",
                                "signal_time": f"2024-01-{index + 1:02d}T20:00:00+00:00",
                                "forced_cash": window == "S3" and index == decision_count - 1,
                                "risk_on": False,
                                "breadth": 0.0,
                                "chosen_pairs": [],
                                "rows": [
                                    {
                                        "pair": f"P{asset}",
                                        "weekly_return": 0.0,
                                        "high_proximity": 1.0,
                                        "weekly_return_rank": 8 - asset,
                                        "high_proximity_rank": 8 - asset,
                                        "composite_score": float(8 - asset),
                                        "positive": False,
                                        "selected_target": False,
                                    }
                                    for asset in range(8)
                                ],
                            }
                        )
                policy_rows.append(
                    {
                        "policy_id": policy,
                        "window_id": window,
                        "cost_label": cost,
                        "signals": signals,
                        "events": [],
                    }
                )
    aggregates = []
    for policy in policies:
        aggregates.append(
            {
                "policy_id": policy,
                "cost_label": "1.0x",
                "full_week_returns": [0.0] * 39,
                "weekly_mean": 0.0,
                "weekly_std": 0.0,
                "sr_weekly_raw": 0.0,
                "sr_weekly_annualized": 0.0,
                "skewness": 0.0,
                "ordinary_kurtosis": 3.0,
                "sigma_sr_raw": 0.0,
                "sr_star_raw": 0.0,
                "dsr_radicand": 1.0,
                "dsr_z_score": 0.0,
                "within_stage_dsr_probability": 0.0,
            }
        )
    return {"policy_rows": policy_rows, "policy_aggregates": aggregates}


def test_evidence_views_freeze_schedule_signal_and_dsr_counts() -> None:
    views = evidence.evidence_views(_fake_screen())
    assert len(views["schedule"]) == 120
    assert len(views["signals"]) == 960
    assert views["multiple_testing"]["trial_count"] == 3
    assert views["multiple_testing"]["within_stage_only"] is True
    assert all(len(values) == 39 for values in views["weekly_dsr"].values())


def test_source_inventory_is_unique_complete_and_snapshot_bound() -> None:
    assert len(inventory.SOURCE_PATHS) == len(set(inventory.SOURCE_PATHS))
    assert "implementation/scripts/c4a_finalizer_core.py" in inventory.SOURCE_PATHS
    assert "implementation/tests/test_c4a_evidence_contract.py" in inventory.SOURCE_PATHS
    missing = [relative for relative in inventory.SOURCE_PATHS if not (inventory.ROOT / relative).is_file()]
    assert missing == []


def test_finalizer_comparison_is_strict_but_numerically_tolerant() -> None:
    finalizer.compare("same", {"a": [1.0, True]}, {"a": [1.0 + 1e-12, True]})
    with pytest.raises(finalizer.C4AFinalizerError, match="numeric mismatch"):
        finalizer.compare("different", 1.0, 1.01)
    with pytest.raises(finalizer.C4AFinalizerError, match="key mismatch"):
        finalizer.compare("keys", {"a": 1}, {"b": 1})
