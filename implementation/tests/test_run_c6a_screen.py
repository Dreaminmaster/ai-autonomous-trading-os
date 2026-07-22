from __future__ import annotations

from decimal import Decimal

import pytest

from atos.c6a_contract import C6AError
from atos.c6a_metrics import GateDecision
from scripts import run_c6a_screen as runner


def cell(window: str, weekly_return: str = "0.001") -> dict:
    return {
        "window_id": window,
        "final_equity": "1026",
        "net_return": "0.026",
        "maximum_drawdown": "0.01",
        "annualized_one_way_turnover": "0.4",
        "weekly_buckets": [
            {"weekly_return": weekly_return, "weekly_pnl": "1"}
            for _ in range(26)
        ],
    }


def test_exact_source_sha_is_mandatory(monkeypatch) -> None:
    monkeypatch.delenv("C6A_SOURCE_SHA", raising=False)
    monkeypatch.delenv("GITHUB_SHA", raising=False)
    with pytest.raises(runner.C6AScreenError, match="exact lowercase"):
        runner._exact_source_sha()
    monkeypatch.setenv("C6A_SOURCE_SHA", "a" * 40)
    assert runner._exact_source_sha() == "a" * 40


def test_descriptive_aggregate_uses_five_independent_windows() -> None:
    result = runner._descriptive_aggregate(
        [cell(f"W{i}") for i in range(1, 6)],
        policy_id="SpotBuyAndHoldComparator",
        cost_label="1.0x",
    )
    assert result["aggregate_return"] == "0.026"
    assert len(result["weekly_returns"]) == 130
    assert result["selectable"] is False
    assert result["live"] == "FORBIDDEN"


def test_descriptive_aggregate_rejects_missing_window() -> None:
    with pytest.raises(runner.C6AScreenError, match="window set mismatch"):
        runner._descriptive_aggregate(
            [cell(f"W{i}") for i in range(1, 5)],
            policy_id="CashComparator",
            cost_label="1.0x",
        )


def test_decision_payload_never_opens_confirmation() -> None:
    decision = GateDecision(
        status="REJECTED",
        selected_policy=None,
        checks={"all_windows_positive": False},
        margins={"expected_return_minus_zero": Decimal("-0.01")},
        rejection_reasons=("all_windows_positive",),
    )
    payload = runner._decision_payload(decision, source_sha="b" * 40)
    assert payload["selected_policy"] is None
    assert payload["confirmation_opened"] is False
    assert payload["c6b_state"] == "C6B_CLOSED"
    assert payload["c5b_state"] == "C5B_CLOSED_AND_UNTOUCHED"
    assert payload["live"] == "FORBIDDEN"
