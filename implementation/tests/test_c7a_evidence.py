from __future__ import annotations

import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from atos.c7a_contract import C7AError
from atos.c7a_evidence import build_synthetic_evidence_package
from atos.c7a_weekly_evaluation import (
    aggregate_candidate_weekly,
    aggregate_comparator_weekly,
    decide_c7a,
)
from atos.c7a_weekly_independent import review_weekly_evidence

START = datetime(2026, 8, 24, tzinfo=UTC)
METADATA = {
    "stage": "C7A",
    "source_kind": "SYNTHETIC",
    "contains_real_market_rows": False,
    "network_access": False,
    "economic_run": False,
    "paper_state": "PAPER_CLOSED",
    "shadow_state": "SHADOW_CLOSED",
    "live_state": "LIVE_FORBIDDEN",
}


def path(start: float, end: float) -> list[float]:
    return [start + (end - start) * index / 168 for index in range(169)]


def candidate(label: str, weekly_base: float, cost_rate: float) -> list[dict]:
    rows = []
    equity = 1000.0
    for index in range(26):
        weekly_return = weekly_base + ((index % 3) - 1) * 0.00005
        start = equity
        end = start * (1 + weekly_return)
        receipts = start * 0.0045
        payments = start * 0.0005
        funding = receipts - payments
        traded = start * 0.05
        cost = traded * cost_rate
        relative = end - start - funding + cost
        rows.append(
            {
                "decision_time": (START + timedelta(days=7 * index)).isoformat(),
                "cost_label": label,
                "starting_equity": start,
                "ending_equity": end,
                "funding_pnl": funding,
                "gross_funding_receipts": receipts,
                "gross_funding_payments": payments,
                "relative_price_pnl": relative,
                "negative_relative_price_pnl": min(relative, 0.0),
                "traded_notional": traded,
                "trading_cost": cost,
                "turnover": 0.05,
                "btc_mark_return": 0.02 if index % 2 == 0 else -0.02,
                "active": True,
                "orientation": "LONG_BTC_SHORT_ETH"
                if index < 13
                else "LONG_ETH_SHORT_BTC",
                "missing_decision": False,
                "unaccounted_funding_settlements": 0,
                "equity_path": path(start, end),
            }
        )
        equity = end
    return rows


def comparator(weekly_positive: float, weekly_negative: float) -> list[dict]:
    rows = []
    equity = 1000.0
    for index in range(26):
        weekly_return = weekly_positive if index % 2 == 0 else weekly_negative
        start = equity
        end = start * (1 + weekly_return)
        rows.append(
            {
                "decision_time": (START + timedelta(days=7 * index)).isoformat(),
                "starting_equity": start,
                "ending_equity": end,
                "equity_path": path(start, end),
            }
        )
        equity = end
    return rows


def inputs() -> tuple[dict, dict]:
    candidates = {
        "1.0x": candidate("1.0x", 0.003, 0.0015),
        "1.5x": candidate("1.5x", 0.002, 0.00225),
        "2.0x": candidate("2.0x", 0.001, 0.003),
    }
    comparators = {
        "cash": comparator(0.0, 0.0),
        "always_on_funding_rank": comparator(0.006, -0.003),
        "equal_notional_funding_rank": comparator(0.004, -0.003),
    }
    return candidates, comparators


def evidence() -> dict:
    candidates, comparators = inputs()
    candidate_aggregates = {
        label: aggregate_candidate_weekly(rows, cost_label=label, metadata=METADATA)
        for label, rows in candidates.items()
    }
    comparator_aggregates = {
        name: aggregate_comparator_weekly(rows, comparator_id=name, metadata=METADATA)
        for name, rows in comparators.items()
    }
    decision = decide_c7a(
        expected=candidate_aggregates["1.0x"],
        stress_1_5x=candidate_aggregates["1.5x"],
        stress_2_0x=candidate_aggregates["2.0x"],
        always_on=comparator_aggregates["always_on_funding_rank"],
    )
    return {
        "metadata": dict(METADATA),
        "candidate_rows": candidates,
        "comparator_rows": comparators,
        "producer_candidate_aggregates": candidate_aggregates,
        "producer_comparator_aggregates": comparator_aggregates,
        "producer_decision": decision,
    }


def test_independent_review_passes_complete_synthetic_evidence() -> None:
    review = review_weekly_evidence(evidence())
    assert review["status"] == "PASS"
    assert review["errors"] == []
    assert review["decision_recomputed"]["decision"] == "SELECTED"


def test_independent_review_detects_producer_tamper() -> None:
    retained = evidence()
    retained["producer_candidate_aggregates"]["1.0x"]["aggregate_net_return"] += 1.0
    review = review_weekly_evidence(retained)
    assert review["status"] == "FAIL"
    assert any("aggregate_net_return" in error for error in review["errors"])


def test_package_manifest_is_complete_and_hash_consistent(tmp_path) -> None:
    candidates, comparators = inputs()
    root = tmp_path / "c7a-synthetic-evidence"
    decision, review, manifest = build_synthetic_evidence_package(
        root,
        metadata=METADATA,
        candidate_rows=candidates,
        comparator_rows=comparators,
    )
    assert decision["decision"] == "SELECTED"
    assert review["status"] == "PASS"
    observed = {row["path"]: row for row in manifest["files"]}
    expected = {
        file.relative_to(root).as_posix(): file
        for file in root.rglob("*")
        if file.is_file() and file.name != "manifest.json"
    }
    assert set(observed) == set(expected)
    assert manifest["file_count"] == len(expected)
    for relative, file in expected.items():
        data = file.read_bytes()
        assert observed[relative]["size"] == len(data)
        assert observed[relative]["sha256"] == hashlib.sha256(data).hexdigest()
    assert json.loads((root / "independent_review.json").read_text())["status"] == "PASS"


def test_package_rejects_real_data_and_missing_comparator(tmp_path) -> None:
    candidates, comparators = inputs()
    bad_metadata = dict(METADATA)
    bad_metadata["contains_real_market_rows"] = True
    with pytest.raises(C7AError, match="synthetic-only"):
        build_synthetic_evidence_package(
            tmp_path / "real",
            metadata=bad_metadata,
            candidate_rows=candidates,
            comparator_rows=comparators,
        )
    incomplete = copy.deepcopy(comparators)
    incomplete.pop("cash")
    with pytest.raises(C7AError, match="comparator set"):
        build_synthetic_evidence_package(
            tmp_path / "missing",
            metadata=METADATA,
            candidate_rows=candidates,
            comparator_rows=incomplete,
        )


def test_package_rejects_output_reuse(tmp_path) -> None:
    candidates, comparators = inputs()
    root = tmp_path / "evidence"
    build_synthetic_evidence_package(
        root,
        metadata=METADATA,
        candidate_rows=candidates,
        comparator_rows=comparators,
    )
    with pytest.raises(C7AError, match="already exists"):
        build_synthetic_evidence_package(
            root,
            metadata=METADATA,
            candidate_rows=candidates,
            comparator_rows=comparators,
        )
