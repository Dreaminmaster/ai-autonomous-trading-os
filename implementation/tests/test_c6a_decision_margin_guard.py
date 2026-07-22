from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import c6a_decision_margin_guard as guard


def write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def fixture(root: Path, strict_path: Path) -> None:
    candidate_expected = {
        "aggregate_return": "0.12",
        "statistics": {"annualized_weekly_sharpe": 1.4},
    }
    write(
        root / "aggregates/C6AMarketNeutralFundingCarry/1.0x.json",
        candidate_expected,
    )
    write(
        root / "aggregates/C6AMarketNeutralFundingCarry/1.5x.json",
        {"aggregate_return": "0.08"},
    )
    write(
        root / "aggregates/C6AMarketNeutralFundingCarry/2.0x.json",
        {"aggregate_return": "0.03"},
    )
    write(
        root / "aggregates/AlwaysOnDeltaNeutralComparator/1.0x.json",
        {
            "aggregate_return": "0.09",
            "statistics": {"annualized_weekly_sharpe": 1.1},
        },
    )
    write(
        root / "decision.json",
        {
            "status": "SELECTED",
            "selected_policy": "C6AMarketNeutralFundingCarry",
            "margins": {
                "expected_return_minus_zero": "0.12",
                "stress_return_minus_zero": "0.08",
                "severe_return_minus_zero": "0.03",
                "return_delta_vs_always_on": "0.03",
                "sharpe_delta_vs_always_on": "0.3",
            },
        },
    )
    write(
        strict_path,
        {
            "status": "PASS",
            "all_gate_driving_aggregate_fields_compared": True,
        },
    )


def test_margin_guard_verifies_all_exact_values(tmp_path: Path) -> None:
    strict_path = tmp_path / "strict.json"
    fixture(tmp_path / "results", strict_path)
    report = guard.verify(
        result_dir=tmp_path / "results",
        strict_finalizer_path=strict_path,
    )
    assert report["status"] == "PASS"
    assert report["margin_count"] == 5
    assert report["margins"]["return_delta_vs_always_on"] == "0.03"
    assert report["margins"]["sharpe_delta_vs_always_on"] == "0.3"
    assert report["c6b_state"] == "C6B_CLOSED"
    assert report["live"] == "FORBIDDEN"


def test_margin_guard_rejects_value_key_or_strict_finalizer_drift(
    tmp_path: Path,
) -> None:
    strict_path = tmp_path / "strict.json"
    root = tmp_path / "results"
    fixture(root, strict_path)
    decision_path = root / "decision.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["margins"]["sharpe_delta_vs_always_on"] = "0.299"
    write(decision_path, decision)
    with pytest.raises(guard.C6ADecisionMarginError, match="margin mismatch"):
        guard.verify(result_dir=root, strict_finalizer_path=strict_path)

    fixture(root, strict_path)
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    decision["margins"].pop("severe_return_minus_zero")
    write(decision_path, decision)
    with pytest.raises(guard.C6ADecisionMarginError, match="key-set"):
        guard.verify(result_dir=root, strict_finalizer_path=strict_path)

    fixture(root, strict_path)
    write(strict_path, {"status": "PASS"})
    with pytest.raises(guard.C6ADecisionMarginError, match="must PASS"):
        guard.verify(result_dir=root, strict_finalizer_path=strict_path)


def test_undefined_statistics_require_empty_margin_map(tmp_path: Path) -> None:
    root = tmp_path / "results"
    strict_path = tmp_path / "strict.json"
    write(
        root / "aggregates/C6AMarketNeutralFundingCarry/1.0x.json",
        {"aggregate_return": "0", "statistics": None},
    )
    write(
        root / "aggregates/C6AMarketNeutralFundingCarry/1.5x.json",
        {"aggregate_return": "0"},
    )
    write(
        root / "aggregates/C6AMarketNeutralFundingCarry/2.0x.json",
        {"aggregate_return": "0"},
    )
    write(
        root / "aggregates/AlwaysOnDeltaNeutralComparator/1.0x.json",
        {"aggregate_return": "0", "statistics": None},
    )
    write(
        root / "decision.json",
        {"status": "REJECTED", "selected_policy": None, "margins": {}},
    )
    write(
        strict_path,
        {
            "status": "PASS",
            "all_gate_driving_aggregate_fields_compared": True,
        },
    )
    report = guard.verify(result_dir=root, strict_finalizer_path=strict_path)
    assert report["margin_count"] == 0
    assert report["economic_result"] == "REJECTED"
    assert report["selected_policy"] is None
