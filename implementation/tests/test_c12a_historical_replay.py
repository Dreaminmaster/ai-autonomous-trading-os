from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from atos.c12a_contract import WINDOWS, contract_decisions, iso_z, load_frozen_config
from atos.c12a_historical_independent import (
    C12AHistoricalIndependentError,
    review_historical_window,
    review_pooled_summary,
)
from atos.c12a_historical_replay import (
    C12AHistoricalReplayError,
    DecisionMarket,
    HourMark,
    build_decision_market,
    replay_h1_h5,
    replay_window,
    summarize_h1_h5,
)


def _direct_market(index: int, *, enter: bool) -> DecisionMarket:
    decision = contract_decisions(load_frozen_config(verify_authority=False))[index]
    signal_future = Decimal(260 if enter else 249)
    marks = []
    window = next(item for item in WINDOWS if item.window_id == decision.window_id)
    boundary = window.start + timedelta(days=7)
    while boundary < window.end:
        if decision.entry_timestamp < boundary < decision.exit_timestamp:
            progress = Decimal(
                str(
                    (boundary - decision.entry_timestamp).total_seconds()
                    / (
                        decision.exit_timestamp - decision.entry_timestamp
                    ).total_seconds()
                )
            )
            marks.append(
                HourMark(
                    timestamp=boundary,
                    spot=Decimal(100) + Decimal(20) * progress,
                    future=Decimal(110) + Decimal(10) * progress,
                )
            )
        boundary += timedelta(days=7)
    return DecisionMarket(
        decision=decision,
        signal_spot=Decimal(247),
        signal_future=signal_future,
        entry_spot=Decimal(100),
        entry_future=Decimal(110),
        exit_spot=Decimal(120),
        exit_future=Decimal(120),
        marks=tuple(marks),
    )


def _source_rows(index: int) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    decision = contract_decisions(load_frozen_config(verify_authority=False))[index]
    spot: list[dict[str, str]] = []
    future: list[dict[str, str]] = []
    current = decision.signal_cutoff - timedelta(hours=1)
    trade_id = 1
    while current <= decision.exit_timestamp:
        spot.append(
            {
                "instrument": decision.spot_instrument,
                "timestamp": iso_z(current),
                "open": "100",
                "close": "100",
            }
        )
        future.append(
            {
                "instrument": decision.futures_instrument,
                "trade_id": str(trade_id),
                "side": "buy",
                "price": "106",
                "size": "1",
                "timestamp": iso_z(current),
            }
        )
        trade_id += 1
        current += timedelta(hours=1)
    return spot, future


def _all_source_rows() -> tuple[
    dict[str, list[dict[str, str]]], dict[str, list[dict[str, str]]]
]:
    spot_by_instrument: dict[str, dict[str, dict[str, str]]] = {
        "BTC-USDT": {},
        "ETH-USDT": {},
    }
    future_by_instrument: dict[str, list[dict[str, str]]] = {}
    decisions = contract_decisions(load_frozen_config(verify_authority=False))
    for index, decision in enumerate(decisions):
        spot, future = _source_rows(index)
        for row in spot:
            spot_by_instrument[decision.spot_instrument][row["timestamp"]] = row
        future_by_instrument[decision.futures_instrument] = future
    # Weekly BTC benchmark boundaries extend outside contract custody hours.
    for window in WINDOWS:
        for index in range(27):
            stamp = iso_z(window.start + timedelta(days=7 * index, hours=-1))
            spot_by_instrument["BTC-USDT"].setdefault(
                stamp,
                {
                    "instrument": "BTC-USDT",
                    "timestamp": stamp,
                    "open": str(100 + index),
                    "close": str(100 + index),
                },
            )
    return (
        {
            instrument: sorted(rows.values(), key=lambda row: row["timestamp"])
            for instrument, rows in spot_by_instrument.items()
        },
        future_by_instrument,
    )


def test_build_decision_market_uses_separate_signal_and_execution_clocks() -> None:
    decision = contract_decisions(load_frozen_config(verify_authority=False))[0]
    spot, future = _source_rows(0)
    signal_stamp = iso_z(decision.signal_cutoff - timedelta(hours=1))
    entry_stamp = iso_z(decision.entry_timestamp)
    exit_stamp = iso_z(decision.exit_timestamp)
    for row in spot:
        if row["timestamp"] == signal_stamp:
            row["close"] = "100"
        if row["timestamp"] == entry_stamp:
            row["open"] = "101"
        if row["timestamp"] == exit_stamp:
            row["open"] = "102"
    for row in future:
        if row["timestamp"] == signal_stamp:
            row["price"] = "106"
        if row["timestamp"] == entry_stamp:
            row["price"] = "107"
        if row["timestamp"] == exit_stamp:
            row["price"] = "102"
    market = build_decision_market(decision, spot_rows=spot, futures_rows=future)
    assert market.signal_spot == Decimal(100)
    assert market.signal_future == Decimal(106)
    assert market.entry_spot == Decimal(101)
    assert market.entry_future == Decimal(107)
    assert market.exit_spot == Decimal(102)
    assert market.exit_future == Decimal(102)


def test_build_decision_market_rejects_missing_carried_hour() -> None:
    decision = contract_decisions(load_frozen_config(verify_authority=False))[0]
    spot, future = _source_rows(0)
    missing_stamp = iso_z(decision.entry_timestamp + timedelta(hours=3))
    future = [row for row in future if row["timestamp"] != missing_stamp]
    with pytest.raises(C12AHistoricalReplayError, match="carried hour"):
        build_decision_market(decision, spot_rows=spot, futures_rows=future)


def test_execution_uses_first_trade_within_five_minute_bound() -> None:
    decision = contract_decisions(load_frozen_config(verify_authority=False))[0]
    spot, future = _source_rows(0)
    exit_row = next(
        row for row in future if row["timestamp"] == iso_z(decision.exit_timestamp)
    )
    exit_row["timestamp"] = iso_z(decision.exit_timestamp + timedelta(seconds=61))
    exit_row["price"] = "109"
    market = build_decision_market(decision, spot_rows=spot, futures_rows=future)
    assert market.exit_future == Decimal(109)

    exit_row["timestamp"] = iso_z(decision.exit_timestamp + timedelta(seconds=301))
    with pytest.raises(C12AHistoricalReplayError, match="exit execution"):
        build_decision_market(decision, spot_rows=spot, futures_rows=future)


def test_producer_and_independent_reject_unordered_futures_rows() -> None:
    decision = contract_decisions(load_frozen_config(verify_authority=False))[0]
    spot, future = _source_rows(0)
    future[0], future[1] = future[1], future[0]
    with pytest.raises(C12AHistoricalReplayError, match="unordered"):
        build_decision_market(decision, spot_rows=spot, futures_rows=future)

    producer = replay_window(
        window_id="H1",
        markets=tuple(_direct_market(index, enter=True) for index in range(4)),
    )
    spot_series, futures_series = _all_source_rows()
    futures_series[decision.futures_instrument][0], futures_series[
        decision.futures_instrument
    ][1] = (
        futures_series[decision.futures_instrument][1],
        futures_series[decision.futures_instrument][0],
    )
    with pytest.raises(C12AHistoricalIndependentError, match="unordered"):
        review_historical_window(
            producer,
            spot_series=spot_series,
            futures_series=futures_series,
            config=load_frozen_config(verify_authority=False),
        )


def test_window_replay_keeps_candidate_and_comparators_non_selectable() -> None:
    markets = tuple(_direct_market(index, enter=index % 2 == 0) for index in range(4))
    result = replay_window(window_id="H1", markets=markets)
    assert len(result["decisions"]) == 4
    assert sum(item["entered"] for item in result["decisions"]) == 2
    for cost_label in ("1.0x", "1.5x", "2.0x"):
        cell = result["cost_cells"][cost_label]
        candidate = cell["candidate"]
        cash = cell["cash_comparator"]
        always = cell["always_enter_comparator"]
        spot = cell["spot_only_comparator"]
        assert candidate["position_count"] == 2
        assert always["position_count"] == 4
        assert spot["position_count"] == 2
        assert cash == {"final_equity": "1000", "return": "0", "position_count": 0}
        assert len(candidate["weekly_returns"]) == 26
        assert candidate["buffer_breaches"] == 0
        assert candidate["base_hedge_mismatches"] == 0
        assert candidate["reconciliation_errors"] == 0
        assert Decimal(candidate["final_equity"]) > Decimal(1000)


def test_buffer_breach_forces_ineligibility_count() -> None:
    market = _direct_market(0, enter=True)
    breach_mark = HourMark(
        timestamp=market.marks[0].timestamp,
        spot=market.marks[0].spot,
        future=Decimal(200),
    )
    market = DecisionMarket(
        decision=market.decision,
        signal_spot=market.signal_spot,
        signal_future=market.signal_future,
        entry_spot=market.entry_spot,
        entry_future=market.entry_future,
        exit_spot=market.exit_spot,
        exit_future=market.exit_future,
        marks=(breach_mark, *market.marks[1:]),
    )
    other = tuple(_direct_market(index, enter=False) for index in range(1, 4))
    result = replay_window(window_id="H1", markets=(market, *other))
    assert result["cost_cells"]["1.5x"]["candidate"]["buffer_breaches"] == 1
    no_breach = replay_window(
        window_id="H1", markets=(_direct_market(0, enter=True), *other)
    )
    assert Decimal(
        result["cost_cells"]["1.5x"]["spot_only_comparator"]["final_equity"]
    ) < Decimal(no_breach["cost_cells"]["1.5x"]["spot_only_comparator"]["final_equity"])


def test_pooled_summary_classifies_without_selecting_a_comparator() -> None:
    markets = tuple(_direct_market(index, enter=index % 2 == 0) for index in range(20))
    replay = replay_h1_h5(markets)
    benchmark = tuple(
        Decimal("0.01") if index % 2 else Decimal("-0.005") for index in range(130)
    )
    summary = summarize_h1_h5(replay, btc_weekly_returns=benchmark)
    assert summary["overall_economic_verdict"] == "ECONOMIC_FAIL"
    assert summary["selected_policy"] is None
    assert summary["declared_program_familywise_trial_count"] == 628
    assert len(summary["pooled"]["candidate"]["1.5x"]["weekly_returns"]) == 130
    assert summary["pooled"]["candidate"]["1.5x"]["position_count"] == 10
    assert "return_delta_vs_always_enter" in summary["rejection_reasons"]


def test_independent_recompute_matches_every_window_and_pooled_summary() -> None:
    spot, future = _all_source_rows()
    markets = tuple(
        build_decision_market(
            decision,
            spot_rows=spot[decision.spot_instrument],
            futures_rows=future[decision.futures_instrument],
        )
        for decision in contract_decisions(load_frozen_config(verify_authority=False))
    )
    replay = replay_h1_h5(markets)
    config = load_frozen_config(verify_authority=False)
    for producer in replay["windows"]:
        review = review_historical_window(
            producer, spot_series=spot, futures_series=future, config=config
        )
        assert review["status"] == "PASS"
        assert review["producer_sha256"] == review["independent_sha256"]
    # The independent benchmark is intentionally rebuilt from retained BTC rows.
    from atos.c12a_historical_replay import btc_weekly_benchmark_returns

    summary = summarize_h1_h5(
        replay, btc_weekly_returns=btc_weekly_benchmark_returns(spot["BTC-USDT"])
    )
    review = review_pooled_summary(
        summary, replay=replay, btc_spot_rows=spot["BTC-USDT"]
    )
    assert review["status"] == "PASS"
    assert review["producer_sha256"] == review["independent_sha256"]


def test_independent_recompute_rejects_producer_tamper() -> None:
    spot, future = _all_source_rows()
    producer = replay_window(
        window_id="H1",
        markets=tuple(
            build_decision_market(
                item,
                spot_rows=spot[item.spot_instrument],
                futures_rows=future[item.futures_instrument],
            )
            for item in contract_decisions(load_frozen_config(verify_authority=False))
            if item.window_id == "H1"
        ),
    )
    producer["decisions"][0]["normalized_basis"] = "999"
    with pytest.raises(C12AHistoricalIndependentError, match="mismatch"):
        review_historical_window(
            producer,
            spot_series=spot,
            futures_series=future,
            config=load_frozen_config(verify_authority=False),
        )


def test_independent_module_does_not_import_producer_replay() -> None:
    source = (
        Path(__file__).parents[1] / "src" / "atos" / "c12a_historical_independent.py"
    ).read_text(encoding="utf-8")
    assert "from atos.c12a_historical_replay" not in source
    assert "from atos.c12a_research_program_guard" not in source
