from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from atos.c6a_contract import C6AError, FundingRecord
from atos.c6a_policy import construct_always_on_decision, construct_candidate_decision

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c6a_market_neutral_funding_carry.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def funding(decision: datetime, *, eth_positive: bool = True) -> tuple[FundingRecord, ...]:
    rows = []
    for instrument in ("BTC-USDT-SWAP", "ETH-USDT-SWAP"):
        rate = Decimal("0.004") if instrument.startswith("BTC") or eth_positive else Decimal("-0.004")
        for days in (27, 14, 1):
            rows.append(FundingRecord(instrument, decision - timedelta(days=days), rate))
    return tuple(sorted(rows, key=lambda row: (row.instrument, row.funding_time)))


def test_candidate_opens_both_equal_sleeves_when_both_are_eligible() -> None:
    decision_time = datetime(2024, 2, 5, tzinfo=UTC)
    decision = construct_candidate_decision(
        decision_time=decision_time,
        total_equity="900",
        funding_records=funding(decision_time),
        completed_basis={"BTC-USDT": "0.01", "ETH-USDT": "-0.01"},
        current_paired_notional={"BTC-USDT": "0", "ETH-USDT": "0"},
        config=config(),
    )
    assert decision.eligible_assets == ("BTC-USDT", "ETH-USDT")
    assert [target.action for target in decision.targets] == ["OPEN", "OPEN"]
    assert all(target.sleeve_capital == Decimal("450") for target in decision.targets)
    assert all(target.spot_target_notional == Decimal("150") for target in decision.targets)
    assert all(target.collateral_target == Decimal("300") for target in decision.targets)


def test_candidate_closes_ineligible_asset_and_respects_hold_band() -> None:
    decision_time = datetime(2024, 2, 5, tzinfo=UTC)
    decision = construct_candidate_decision(
        decision_time=decision_time,
        total_equity="900",
        funding_records=funding(decision_time, eth_positive=False),
        completed_basis={"BTC-USDT": "0.01", "ETH-USDT": "0.01"},
        current_paired_notional={"BTC-USDT": "295", "ETH-USDT": "100"},
        config=config(),
    )
    # BTC is the only eligible sleeve, so its target is 300 and the 1.69%
    # difference remains inside the 10% no-resize band.
    assert decision.eligible_assets == ("BTC-USDT",)
    assert decision.targets[0].action == "HOLD"
    assert decision.targets[1].action == "CLOSE"


def test_basis_guard_can_force_cash_only() -> None:
    decision_time = datetime(2024, 2, 5, tzinfo=UTC)
    decision = construct_candidate_decision(
        decision_time=decision_time,
        total_equity="1000",
        funding_records=funding(decision_time),
        completed_basis={"BTC-USDT": "0.021", "ETH-USDT": "-0.021"},
        current_paired_notional={"BTC-USDT": "0", "ETH-USDT": "0"},
        config=config(),
    )
    assert decision.cash_only is True
    assert [target.action for target in decision.targets] == ["HOLD_CASH", "HOLD_CASH"]


def test_always_on_differs_only_by_eligibility_filter() -> None:
    decision_time = datetime(2024, 2, 5, tzinfo=UTC)
    decision = construct_always_on_decision(
        decision_time=decision_time,
        total_equity="900",
        current_paired_notional={"BTC-USDT": "0", "ETH-USDT": "0"},
        config=config(),
    )
    assert decision.eligible_assets == ("BTC-USDT", "ETH-USDT")
    assert [target.action for target in decision.targets] == ["OPEN", "OPEN"]
    assert all(value.eligible for value in decision.asset_inputs.values())


def test_non_monday_decision_fails_closed() -> None:
    with pytest.raises(C6AError, match="Monday"):
        construct_always_on_decision(
            decision_time=datetime(2024, 2, 6, tzinfo=UTC),
            total_equity="1000",
            current_paired_notional={"BTC-USDT": "0", "ETH-USDT": "0"},
            config=config(),
        )
