from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import pytest

from atos.c7a_contract import C7AError
from atos.c7a_weekly_evaluation import (
    aggregate_candidate_weekly,
    aggregate_comparator_weekly,
    decide_c7a,
)

START = datetime(2026, 8, 24, tzinfo=UTC)
SYNTHETIC_METADATA = {
    "stage": "C7A",
    "source_kind": "SYNTHETIC",
    "contains_real_market_rows": False,
    "network_access": False,
    "economic_run": False,
    "paper_state": "PAPER_CLOSED",
    "shadow_state": "SHADOW_CLOSED",
    "live_state": "LIVE_FORBIDDEN",
}


def candidate_rows(label: str, base_return: float, cost_rate: float) -> list[dict]:
    rows: list[dict] = []
    equity = 1000.0
    for index in range(26):
        weekly_return = base_return + ((index % 3) - 1) * 0.00005
        starting = equity
        ending = starting * (1.0 + weekly_return)
        receipts = starting * 0.0045
        payments = starting * 0.0005
        funding = receipts - payments
        cost = starting * cost_rate
        relative = ending - starting - funding + cost
        rows.append(
            {
                "decision_time": (START + timedelta(days=7 * index)).isoformat(),
                "cost_label": label,
                "starting_equity": starting,
                "ending_equity": ending,
                "funding_pnl": funding,
                "gross_funding_receipts": receipts,
                "gross_funding_payments": payments,
                "relative_price_pnl": relative,
                "trading_cost": cost,
                "turnover": 0.05,
                "btc_mark_return": 0.02 if index % 2 == 0 else -0.02,
                "active": True,
                "orientation": (
                    "LONG_BTC_SHORT_ETH"
                    if index < 13
                    else "LONG_ETH_SHORT_BTC"
                ),
                "missing_decision": False,
                "unaccounted_funding_settlements": 0,
            }
        )
        equity = ending
    return rows


def comparator_rows() -> list[dict]:
    rows: list[dict] = []
    equity = 1000.0
    for index in range(26):
        weekly_return = 0.006 if index % 2 == 0 else -0.003
        starting = equity
        ending = starting * (1.0 + weekly_return)
        rows.append(
            {
                "decision_time": (START + timedelta(days=7 * index)).isoformat(),
                "starting_equity": starting,
                "ending_equity": ending,
            }
        )
        equity = ending
    return rows


def build_evidence() -> dict:
    candidate = {
        "1.0x": candidate_rows("1.0x", 0.003, 0.001),
        "1.5x": candidate_rows("1.5x", 0.002, 0.0015),
        "2.0x": candidate_rows("2.0x", 0.001, 0.002),
    }
    aggregates = {
        label: aggregate_candidate_weekly(
            rows,
            cost_label=label,
            metadata=SYNTHETIC_METADATA,
        )
        for label, rows in candidate.items()
    }
    always_on_rows = comparator_rows()
    always_on = aggregate_comparator_weekly(
        always_on_rows,
        comparator_id="always_on_funding_rank",
        metadata=SYNTHETIC_METADATA,
    )
    decision = decide_c7a(
        expected=aggregates["1.0x"],
        stress_1_5x=aggregates["1.5x"],
        stress_2_0x=aggregates["2.0x"],
        always_on=always_on,
    )
    return {
        "metadata": dict(SYNTHETIC_METADATA),
        "candidate_rows": candidate,
        "always_on_rows": always_on_rows,
        "candidate_aggregates": aggregates,
        "always_on_aggregate": always_on,
        "decision": decision,
    }


def test_synthetic_selected_fixture() -> None:
    evidence = build_evidence()
    assert evidence["decision"]["decision"] == "SELECTED"
    assert evidence["decision"]["failed_gates"] == []


def test_candidate_aggregation_rejects_accounting_tamper() -> None:
    rows = candidate_rows("1.0x", 0.003, 0.001)
    rows[7]["ending_equity"] += 1.0
    with pytest.raises(C7AError, match="weekly accounting"):
        aggregate_candidate_weekly(
            rows,
            cost_label="1.0x",
            metadata=SYNTHETIC_METADATA,
        )


def test_candidate_aggregation_rejects_real_data_boundary() -> None:
    metadata = dict(SYNTHETIC_METADATA)
    metadata["contains_real_market_rows"] = True
    with pytest.raises(C7AError, match="synthetic-only"):
        aggregate_candidate_weekly(
            candidate_rows("1.0x", 0.003, 0.001),
            cost_label="1.0x",
            metadata=metadata,
        )


def test_frozen_gate_rejects_orientation_concentration() -> None:
    evidence = build_evidence()
    concentrated = copy.deepcopy(evidence["candidate_rows"]["1.0x"])
    for row in concentrated:
        row["orientation"] = "LONG_BTC_SHORT_ETH"
    aggregate = aggregate_candidate_weekly(
        concentrated,
        cost_label="1.0x",
        metadata=SYNTHETIC_METADATA,
    )
    decision = decide_c7a(
        expected=aggregate,
        stress_1_5x=evidence["candidate_aggregates"]["1.5x"],
        stress_2_0x=evidence["candidate_aggregates"]["2.0x"],
        always_on=evidence["always_on_aggregate"],
    )
    assert decision["decision"] == "REJECTED"
    assert "orientation_concentration" in decision["failed_gates"]
