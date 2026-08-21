from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from decimal import Decimal

import pytest
from atos.c9a_contract import COST_RATES, HOUR, SPOT_INSTRUMENTS, SWAP_INSTRUMENTS
from atos.c9a_historical_independent import (
    review_historical_window,
    review_pooled_summary,
)
from atos.c9a_historical_ledger import Portfolio
from atos.c9a_historical_replay import (
    C9AHistoricalReplayError,
    _apply_plan,
    _solve_scale,
    evaluate_historical_window,
    summarize_w1_w5,
)
from atos.c9a_historical_schedule import window_by_id


def _fixture(window_id: str = "W1") -> tuple[dict, dict, dict]:
    window = window_by_id(window_id)
    trade_rows = {}
    for instrument in (*SPOT_INSTRUMENTS, *SWAP_INSTRUMENTS):
        rows = []
        current = window.start - 2 * HOUR
        while current < window.end_exclusive + HOUR:
            price = "100" if instrument.startswith("BTC") else "50"
            rows.append(
                {"timestamp": current.isoformat(), "open": price, "close": price}
            )
            current += HOUR
        trade_rows[instrument] = rows
    mark_rows = {}
    for instrument in SWAP_INSTRUMENTS:
        rows = []
        current = window.start - 2 * HOUR
        while current < window.end_exclusive:
            price = "100" if instrument.startswith("BTC") else "50"
            rows.append({"timestamp": current.isoformat(), "close": price})
            current += HOUR
        mark_rows[instrument] = rows
    funding_rows = {}
    for instrument in SWAP_INSTRUMENTS:
        rows = []
        current = window.start - timedelta(days=28)
        while current < window.end_exclusive:
            rows.append(
                {"funding_time": current.isoformat(), "realized_rate": "0.00012"}
            )
            current += timedelta(hours=8)
        funding_rows[instrument] = rows
    return trade_rows, mark_rows, funding_rows


@pytest.fixture(scope="module")
def evaluated() -> tuple[dict, dict, dict, dict]:
    trades, marks, funding = _fixture()
    result = evaluate_historical_window(
        window_id="W1",
        trade_rows=trades,
        mark_rows=marks,
        funding_rows=funding,
    )
    return result, trades, marks, funding


def test_continuous_notional_replay_is_positive_accounted_and_exactly_hedged(
    evaluated: tuple[dict, dict, dict, dict],
) -> None:
    result, *_ = evaluated
    assert result["result_cell_count"] == 12
    for cost in COST_RATES:
        replay = result["replays"]["candidate"][cost]
        assert float(replay["net_return"]) > 0
        assert replay["decision_count"] == replay["weekly_bucket_count"] == 26
        assert replay["unaccounted_funding_settlement_count"] == 0
        assert replay["base_hedge_mismatch_count"] == 0
        assert replay["collateral_buffer_breach_count"] == 0
        assert abs(float(replay["reconciliation_residual"])) <= 1e-10
        assert all(
            action["quantity_after"] == action["short_after"]
            for decision in replay["decisions"]
            for action in decision["actions"].values()
        )
    assert float(result["replays"]["candidate"]["2.0x"]["final_equity"]) < float(
        result["replays"]["candidate"]["1.0x"]["final_equity"]
    )


def test_solver_finds_highest_feasible_interval_despite_low_scale_margin_gap() -> None:
    portfolio = Portfolio.create("1050")
    portfolio.accrue_to(
        spot_prices={"BTC-USDT": Decimal(100), "ETH-USDT": Decimal(50)},
        perpetual_prices={
            "BTC-USDT": Decimal(100),
            "ETH-USDT": Decimal(50),
        },
    )
    portfolio.trade_target(
        spot="BTC-USDT",
        new_quantity=Decimal(9),
        target_margin_before_fee=Decimal(100),
        spot_trade_price=Decimal(100),
        swap_trade_price=Decimal(100),
        cost_rate=Decimal(0),
    )
    plan = {
        "BTC-USDT": {
            "action": "RESIZE",
            "raw_spot_notional": "1000",
            "raw_margin": "100",
        },
        "ETH-USDT": {
            "action": "HOLD_CASH",
            "raw_spot_notional": "0",
            "raw_margin": "0",
        },
    }
    spot_opens = {"BTC-USDT": Decimal(100), "ETH-USDT": Decimal(50)}
    swap_opens = dict(spot_opens)
    scale = _solve_scale(
        portfolio,
        plan=plan,
        spot_opens=spot_opens,
        swap_opens=swap_opens,
        cost_rate=Decimal("0.2"),
    )
    assert scale > Decimal("0.7")
    _apply_plan(
        portfolio,
        plan=plan,
        scale=scale,
        spot_opens=spot_opens,
        swap_opens=swap_opens,
        cost_rate=Decimal("0.2"),
    )
    assert portfolio.free_cash >= -Decimal("1e-10")
    assert portfolio.sleeves["BTC-USDT"].margin_cash > 0


def test_solver_respects_strict_high_scale_margin_cap() -> None:
    portfolio = Portfolio.create("2000")
    spot_opens = {"BTC-USDT": Decimal(100), "ETH-USDT": Decimal(50)}
    portfolio.accrue_to(spot_prices=spot_opens, perpetual_prices=spot_opens)
    portfolio.trade_target(
        spot="BTC-USDT",
        new_quantity=Decimal(4),
        target_margin_before_fee=Decimal(100),
        spot_trade_price=Decimal(100),
        swap_trade_price=Decimal(100),
        cost_rate=Decimal(0),
    )
    plan = {
        "BTC-USDT": {
            "action": "RESIZE",
            "raw_spot_notional": "1000",
            "raw_margin": "100",
        },
        "ETH-USDT": {
            "action": "HOLD_CASH",
            "raw_spot_notional": "0",
            "raw_margin": "0",
        },
    }
    scale = _solve_scale(
        portfolio,
        plan=plan,
        spot_opens=spot_opens,
        swap_opens=spot_opens,
        cost_rate=Decimal("0.2"),
    )
    assert Decimal("0.79") < scale < Decimal("0.8")
    _apply_plan(
        portfolio,
        plan=plan,
        scale=scale,
        spot_opens=spot_opens,
        swap_opens=spot_opens,
        cost_rate=Decimal("0.2"),
    )
    assert portfolio.sleeves["BTC-USDT"].margin_cash > 0


def test_signal_uses_t_minus_two_and_funding_strictly_before_decision() -> None:
    trades, marks, funding = _fixture()
    decision = window_by_id("W1").start
    for spot in SPOT_INSTRUMENTS:
        row = next(
            value
            for value in trades[spot]
            if value["timestamp"] == (decision - HOUR).isoformat()
        )
        row["close"] = "999999"
    for swap in SWAP_INSTRUMENTS:
        row = next(
            value
            for value in funding[swap]
            if value["funding_time"] == decision.isoformat()
        )
        row["realized_rate"] = "-10"
    result = evaluate_historical_window(
        window_id="W1", trade_rows=trades, mark_rows=marks, funding_rows=funding
    )
    first = result["replays"]["candidate"]["1.0x"]["signals"][0]
    assert all(
        value["basis_source_timestamp"]
        == (decision - 2 * HOUR).isoformat().replace("+00:00", "Z")
        for value in first["assets"].values()
    )
    assert all(value["eligible"] for value in first["assets"].values())


def test_delayed_funding_uses_preceding_completed_mark(
    evaluated: tuple[dict, dict, dict, dict],
) -> None:
    _, trades, marks, funding = evaluated
    changed = {key: [dict(row) for row in value] for key, value in funding.items()}
    stamp = window_by_id("W1").start + timedelta(hours=8, minutes=1)
    for swap in SWAP_INSTRUMENTS:
        changed[swap][85]["funding_time"] = stamp.isoformat()
    result = evaluate_historical_window(
        window_id="W1", trade_rows=trades, mark_rows=marks, funding_rows=changed
    )
    event = next(
        row
        for row in result["replays"]["candidate"]["1.0x"]["funding_events"]
        if row["timestamp"] == stamp.isoformat().replace("+00:00", "Z")
    )
    assert event["preceding_mark_timestamp"] == (
        window_by_id("W1").start + timedelta(hours=7)
    ).isoformat().replace("+00:00", "Z")


def test_replay_fails_closed_on_missing_or_duplicate_source() -> None:
    trades, marks, funding = _fixture()
    trades["BTC-USDT"].pop(100)
    with pytest.raises(C9AHistoricalReplayError, match="missing exact"):
        evaluate_historical_window(
            window_id="W1", trade_rows=trades, mark_rows=marks, funding_rows=funding
        )

    trades, marks, funding = _fixture()
    funding["ETH-USDT-SWAP"].pop(10)
    with pytest.raises(C9AHistoricalReplayError, match="gap exceeds"):
        evaluate_historical_window(
            window_id="W1", trade_rows=trades, mark_rows=marks, funding_rows=funding
        )


def test_basis_breach_closes_next_open_and_cannot_reopen_same_timestamp() -> None:
    trades, marks, funding = _fixture()
    start = window_by_id("W1").start
    row = next(
        value
        for value in marks["BTC-USDT-SWAP"]
        if value["timestamp"] == start.isoformat()
    )
    row["close"] = "105.1"
    result = evaluate_historical_window(
        window_id="W1", trade_rows=trades, mark_rows=marks, funding_rows=funding
    )
    replay = result["replays"]["candidate"]["1.0x"]
    close_time = start + HOUR
    risk_close = next(
        event
        for event in replay["trade_events"]
        if event["kind"] == "RISK_CLOSE"
        and event["timestamp"] == close_time.isoformat().replace("+00:00", "Z")
    )
    btc = next(
        trade
        for trade in risk_close["trades"]
        if trade["spot_instrument"] == "BTC-USDT"
    )
    assert btc["blocked_until"] == (start + timedelta(days=7)).isoformat().replace(
        "+00:00", "Z"
    )
    assert not any(
        event["kind"] == "SCHEDULED_REBALANCE"
        and event["timestamp"] == close_time.isoformat().replace("+00:00", "Z")
        for event in replay["trade_events"]
    )
    review = review_historical_window(
        result, trade_rows=trades, mark_rows=marks, funding_rows=funding
    )
    assert review["status"] == "PASS"
    trades, marks, funding = _fixture()
    funding["BTC-USDT-SWAP"].insert(2, dict(funding["BTC-USDT-SWAP"][1]))
    with pytest.raises(C9AHistoricalReplayError, match="duplicate or unordered"):
        evaluate_historical_window(
            window_id="W1", trade_rows=trades, mark_rows=marks, funding_rows=funding
        )


def test_independent_recompute_covers_all_cells_and_detects_tampering(
    evaluated: tuple[dict, dict, dict, dict],
) -> None:
    result, trades, marks, funding = evaluated
    review = review_historical_window(
        result, trade_rows=trades, mark_rows=marks, funding_rows=funding
    )
    assert review["status"] == "PASS"
    assert len(review["replay_reviews"]) == 6
    assert review["imports_production_replay"] is False
    tampered_result = deepcopy(result)
    tampered_result["replays"]["candidate"]["1.0x"]["trade_events"][0]["trades"][0][
        "spot_cost"
    ] = "999"
    tampered = review_historical_window(
        tampered_result, trade_rows=trades, mark_rows=marks, funding_rows=funding
    )
    assert tampered["status"] == "FAIL"
    assert (
        tampered["replay_reviews"]["candidate:1.0x"]["checks"]["fee_recompute"] is False
    )

    tampered_result = deepcopy(result)
    replay = tampered_result["replays"]["candidate"]["1.0x"]
    replay["decisions"][0]["actions"]["BTC-USDT"]["raw_spot_notional"] = "1"
    replay["weekly_returns"][0] = "99"
    replay["gross_positive_funding_receipts"] = "999999"
    tampered = review_historical_window(
        tampered_result, trade_rows=trades, mark_rows=marks, funding_rows=funding
    )["replay_reviews"]["candidate:1.0x"]
    assert tampered["status"] == "FAIL"
    assert tampered["checks"]["action_plan_recompute"] is False
    assert tampered["checks"]["weekly_return_vector_recompute"] is False
    assert tampered["checks"]["gross_funding_recompute"] is False


def test_pooled_summary_uses_equal_independent_capital_and_independent_gates(
    evaluated: tuple[dict, dict, dict, dict],
) -> None:
    result, *_ = evaluated
    windows = {f"W{index}": result for index in range(1, 6)}
    pooled = summarize_w1_w5(windows)
    review = review_pooled_summary(pooled, windows)
    assert review["status"] == "PASS"
    assert review["reference_final_verdict"] == pooled["overall_economic_verdict"]
    assert pooled["overall_economic_verdict"] == "ECONOMIC_FAIL"
    assert pooled["eligibility_gates"]["return_delta_vs_always_on"] is False


def test_each_frozen_window_completes_source_ordered_independent_recompute() -> None:
    windows = {}
    for window_id in ("W1", "W2", "W3", "W4", "W5"):
        trades, marks, funding = _fixture(window_id)
        result = evaluate_historical_window(
            window_id=window_id,
            trade_rows=trades,
            mark_rows=marks,
            funding_rows=funding,
        )
        review = review_historical_window(
            result,
            trade_rows=trades,
            mark_rows=marks,
            funding_rows=funding,
        )
        assert review["status"] == "PASS"
        assert all(
            cell["checks"]["source_ordered_state_recompute"] is True
            for cell in review["replay_reviews"].values()
        )
        windows[window_id] = result
    pooled = summarize_w1_w5(windows)
    assert review_pooled_summary(pooled, windows)["status"] == "PASS"
