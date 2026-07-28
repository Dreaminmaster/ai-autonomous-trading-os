from __future__ import annotations

import math
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from atos.c7a_contract import INSTRUMENTS
from atos.c7a_historical_independent import review_historical_window
from atos.c7a_historical_replay import (
    C7AHistoricalReplayError,
    HistoricalSignal,
    _policy_target,
    aggregate_candidate_window,
    evaluate_historical_window,
    replay_window,
    summarize_h1_h5,
)
from atos.c7a_historical_schedule import required_source_bounds, window_by_id

BTC, ETH = INSTRUMENTS
HOUR = timedelta(hours=1)


def _fixture(window_id: str = "H1") -> tuple[dict, dict, dict]:
    window = window_by_id(window_id)
    bounds = required_source_bounds(window)
    mark_start = datetime.fromisoformat(bounds["mark_start_inclusive"])
    trade_start = window.first_scored_decision
    trade_end = window.end_exclusive + HOUR

    marks = {instrument: [] for instrument in INSTRUMENTS}
    prices = {BTC: 40_000.0, ETH: 2_000.0}
    current = mark_start
    index = 0
    while current < window.end_exclusive:
        common_return = 0.0002 * math.sin(index / 17) + 0.0001 * math.cos(index / 11)
        for instrument in INSTRUMENTS:
            prices[instrument] *= math.exp(common_return)
            marks[instrument].append(
                {"timestamp": current.isoformat(), "close": prices[instrument]}
            )
        current += HOUR
        index += 1

    trades = {instrument: [] for instrument in INSTRUMENTS}
    mark_lookup = {
        instrument: {row["timestamp"]: row["close"] for row in marks[instrument]}
        for instrument in INSTRUMENTS
    }
    current = trade_start
    while current < trade_end:
        source = min(current, window.end_exclusive - HOUR).isoformat()
        for instrument in INSTRUMENTS:
            price = mark_lookup[instrument][source]
            trades[instrument].append(
                {"timestamp": current.isoformat(), "open": price, "close": price}
            )
        current += HOUR

    funding = {instrument: [] for instrument in INSTRUMENTS}
    current = datetime.fromisoformat(bounds["funding_start_inclusive"])
    while current < window.end_exclusive:
        funding[BTC].append(
            {"funding_time": current.isoformat(), "realized_rate": "0.0004"}
        )
        funding[ETH].append(
            {"funding_time": current.isoformat(), "realized_rate": "0.00005"}
        )
        current += timedelta(hours=8)
    return marks, trades, funding


def test_historical_candidate_replays_all_26_weeks_and_liquidates() -> None:
    marks, trades, funding = _fixture()
    result = replay_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
    )
    assert result["policy"] == "candidate"
    assert result["live_state"] == "LIVE_FORBIDDEN"
    assert len(result["signals"]) == len(result["weekly_rows"]) == 26
    assert all(signal["eligible"] for signal in result["signals"])
    assert all(len(row["equity_path"]) == 169 for row in result["weekly_rows"])
    assert result["weekly_rows"][0]["orientation"] == "LONG_ETH_SHORT_BTC"
    assert result["weekly_rows"][-1]["traded_notional"] > 0
    first_rebalance = result["weekly_rows"][0]["decision_rebalance"]
    assert first_rebalance["executed"] is True
    assert first_rebalance["gross_ratio_after"] == pytest.approx(0.5)
    assert first_rebalance["equity_after"] == pytest.approx(
        first_rebalance["equity_before"] - first_rebalance["total_fee"]
    )
    assert first_rebalance["gross_notional_after"] == pytest.approx(
        0.5 * first_rebalance["equity_after"]
    )
    assert result["weekly_rows"][-1]["terminal_liquidation"]["executed"] is True
    for row in result["weekly_rows"]:
        assert row["ending_equity"] == pytest.approx(
            row["starting_equity"]
            + row["funding_pnl"]
            + row["relative_price_pnl"]
            - row["trading_cost"]
        )


def test_higher_fixed_cost_reduces_same_replay_equity() -> None:
    marks, trades, funding = _fixture()
    expected = replay_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
        cost_label="1.0x",
    )
    stress = replay_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
        cost_label="2.0x",
    )
    assert (
        expected["weekly_rows"][-1]["ending_equity"]
        > stress["weekly_rows"][-1]["ending_equity"]
    )


def test_trade_opens_affect_only_frozen_execution_boundaries() -> None:
    marks, trades, funding = _fixture()
    baseline = replay_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
    )

    non_execution = deepcopy(trades)
    ignored_time = (window_by_id("H1").first_scored_decision + 8 * HOUR).isoformat()
    ignored_row = next(
        row for row in non_execution[BTC] if row["timestamp"] == ignored_time
    )
    ignored_row["open"] *= 2
    ignored_row["close"] *= 2
    ignored = replay_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=non_execution,
        funding_rows=funding,
    )
    assert ignored["weekly_rows"] == baseline["weekly_rows"]

    execution = deepcopy(trades)
    decision_time = window_by_id("H1").first_scored_decision.isoformat()
    execution_row = next(
        row for row in execution[BTC] if row["timestamp"] == decision_time
    )
    execution_row["open"] *= 1.01
    changed = replay_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=execution,
        funding_rows=funding,
    )
    assert changed["weekly_rows"] != baseline["weekly_rows"]


def test_fixed_comparators_use_frozen_signal_boundaries() -> None:
    marks, trades, funding = _fixture()
    always = replay_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
        policy="always_on_funding_rank",
    )
    equal = replay_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
        policy="equal_notional_funding_rank",
    )
    cash = replay_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
        policy="cash",
    )
    assert all(row["active"] for row in always["weekly_rows"])
    assert all(row["active"] for row in equal["weekly_rows"])
    assert all(row["ending_equity"] == 1.0 for row in cash["weekly_rows"])


def test_always_on_comparator_holds_cash_when_beta_validity_fails() -> None:
    base = {
        "decision_time": "2024-01-01T00:00:00Z",
        "eligible": False,
        "high_funding_instrument": BTC,
        "low_funding_instrument": ETH,
        "funding_sums_28d": {BTC: 0.01, ETH: 0.001},
        "beta": 1.0,
        "r_squared": 0.1,
        "long_weight": 0.0,
        "short_weight": 0.0,
        "projected_carry_28d": 0.0,
        "positive_daily_spreads": 0,
        "target_weights": {BTC: 0.0, ETH: 0.0},
    }
    invalid = HistoricalSignal(reason="R_SQUARED_BELOW_MINIMUM", **base)
    assert _policy_target(invalid, "always_on_funding_rank") == {
        BTC: 0.0,
        ETH: 0.0,
    }
    carry_filtered = HistoricalSignal(reason="PROJECTED_CARRY_BELOW_MINIMUM", **base)
    assert sum(
        abs(value)
        for value in _policy_target(carry_filtered, "always_on_funding_rank").values()
    ) == pytest.approx(0.5)


def test_missing_execution_hour_fails_closed() -> None:
    marks, trades, funding = _fixture()
    trades[BTC].pop(100)
    with pytest.raises(C7AHistoricalReplayError, match="missing exact trade source"):
        replay_window(
            window_id="H1",
            mark_rows=marks,
            trade_rows=trades,
            funding_rows=funding,
        )


def test_missing_eth_mark_hour_fails_closed_before_replay() -> None:
    marks, trades, funding = _fixture()
    marks[ETH].pop(1000)
    with pytest.raises(C7AHistoricalReplayError, match="mark source ETH-USDT-SWAP"):
        replay_window(
            window_id="H1",
            mark_rows=marks,
            trade_rows=trades,
            funding_rows=funding,
        )


def test_unaccounted_scored_funding_settlement_fails_closed() -> None:
    marks, trades, funding = _fixture()
    funding[BTC].append(
        {
            "funding_time": "2024-01-01T00:30:00+00:00",
            "realized_rate": "0.1",
        }
    )
    funding[BTC].sort(key=lambda row: row["funding_time"])
    with pytest.raises(C7AHistoricalReplayError, match="exact hour"):
        replay_window(
            window_id="H1",
            mark_rows=marks,
            trade_rows=trades,
            funding_rows=funding,
        )


def test_complete_window_evaluation_runs_all_costs_comparators_and_gates() -> None:
    marks, trades, funding = _fixture()
    evidence = evaluate_historical_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
    )
    assert set(evidence["candidate_replays"]) == {"1.0x", "1.5x", "2.0x"}
    assert set(evidence["comparator_replays"]) == {
        "cash",
        "always_on_funding_rank",
        "equal_notional_funding_rank",
    }
    assert evidence["decision"]["decision"] == "REJECTED"
    assert "always_on_return_increment" in evidence["decision"]["failed_gates"]


def test_historical_aggregate_rejects_weekly_accounting_tamper() -> None:
    marks, trades, funding = _fixture()
    replay = replay_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
    )
    replay["weekly_rows"][3]["ending_equity"] += 1.0
    with pytest.raises(C7AHistoricalReplayError, match="accounting"):
        aggregate_candidate_window(
            window_id="H1",
            rows=replay["weekly_rows"],
            cost_label="1.0x",
        )


def test_physically_separate_historical_review_recomputes_and_detects_tamper() -> None:
    marks, trades, funding = _fixture()
    evidence = evaluate_historical_window(
        window_id="H1",
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
    )
    independent = review_historical_window(
        evidence,
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
    )
    assert independent["status"] == "PASS"
    assert independent["primitive_source_recompute_performed"] is True
    assert independent["primitive_source_recompute_passed"] is True
    evidence["candidate_replays"]["1.0x"]["signals"][0]["eligible"] = False
    source_review = review_historical_window(
        evidence,
        mark_rows=marks,
        trade_rows=trades,
        funding_rows=funding,
    )
    assert source_review["status"] == "FAIL"
    assert (
        "source.candidate.1.0x.signals[0].eligible value mismatch"
        in source_review["errors"]
    )
    evidence["candidate_replays"]["1.0x"]["signals"][0]["eligible"] = True
    evidence["candidate_aggregates"]["1.0x"]["aggregate_net_return"] += 1.0
    review = review_historical_window(evidence)
    assert review["status"] == "FAIL"
    assert "candidate.1.0x.aggregate_net_return value mismatch" in review["errors"]


def test_pooled_summary_uses_all_five_windows_without_best_window_selection() -> None:
    evidence = {}
    for index in range(1, 6):
        window_id = f"H{index}"
        marks, trades, funding = _fixture(window_id)
        evidence[window_id] = evaluate_historical_window(
            window_id=window_id,
            mark_rows=marks,
            trade_rows=trades,
            funding_rows=funding,
        )
    pooled = summarize_h1_h5(evidence)
    assert pooled["weekly_return_count"] == 130
    assert pooled["best_window_selection_performed"] is False
    assert pooled["overall_economic_verdict"] == "ECONOMIC_FAIL"
    assert pooled["live_state"] == "LIVE_FORBIDDEN"
