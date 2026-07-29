from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from atos.c8a_contract import COST_RATES, INSTRUMENTS, SIGNAL_CLOSE_COUNT
from atos.c8a_historical_independent import (
    review_historical_window,
    review_pooled_summary,
)
from atos.c8a_historical_replay import (
    C8AHistoricalReplayError,
    build_signal,
    evaluate_historical_window,
    summarize_h1_h5,
)
from atos.c8a_historical_schedule import HOUR, decision_times, window_by_id


def _hour_rows(
    start: datetime, end_exclusive: datetime, *, field: str, slope: float
) -> list[dict[str, str]]:
    rows = []
    current = start
    index = 0
    while current < end_exclusive:
        rows.append(
            {"timestamp": current.isoformat(), field: str(100.0 + slope * index)}
        )
        current += HOUR
        index += 1
    return rows


def _fixture(
    *,
    window_id: str = "H1",
    btc_slope: float = 0.001,
    eth_slope: float = -0.001,
) -> tuple[dict, dict, dict]:
    window = window_by_id(window_id)
    start = window.first_scored_decision - timedelta(hours=SIGNAL_CLOSE_COUNT + 1)
    slopes = {INSTRUMENTS[0]: btc_slope, INSTRUMENTS[1]: eth_slope}
    marks = {
        instrument: _hour_rows(start, window.end_exclusive, field="close", slope=slope)
        for instrument, slope in slopes.items()
    }
    trades = {
        instrument: _hour_rows(
            window.first_scored_decision,
            window.end_exclusive + HOUR,
            field="open",
            slope=slope,
        )
        for instrument, slope in slopes.items()
    }
    funding = {}
    for instrument in INSTRUMENTS:
        rows = []
        current = window.first_scored_decision
        while current <= window.end_exclusive:
            rows.append(
                {"funding_time": current.isoformat(), "realized_rate": "0.00001"}
            )
            current += timedelta(hours=8)
        funding[instrument] = rows
    return marks, trades, funding


def test_schedule_signal_uses_169_strictly_prior_closes() -> None:
    decision = datetime(2024, 1, 1, tzinfo=UTC)
    first = decision - timedelta(hours=SIGNAL_CLOSE_COUNT + 1)
    values = {
        first + index * HOUR: 100.0 + index for index in range(SIGNAL_CLOSE_COUNT)
    }
    marks = {instrument: dict(values) for instrument in INSTRUMENTS}
    # The source candle stamped t-1h closes at t, so neither it nor t may enter.
    for instrument in INSTRUMENTS:
        marks[instrument][decision - HOUR] = 999_999.0
        marks[instrument][decision] = 1_000_000.0
    signal = build_signal(decision, marks)
    assert (
        signal.endpoints[INSTRUMENTS[0]]["oldest_timestamp"] == "2023-12-24T22:00:00Z"
    )
    assert (
        signal.endpoints[INSTRUMENTS[0]]["oldest_close_time"] == "2023-12-24T23:00:00Z"
    )
    assert (
        signal.endpoints[INSTRUMENTS[0]]["latest_timestamp"] == "2023-12-31T22:00:00Z"
    )
    assert (
        signal.endpoints[INSTRUMENTS[0]]["latest_close_time"] == "2023-12-31T23:00:00Z"
    )
    assert signal.endpoints[INSTRUMENTS[0]]["close_count"] == 169
    assert signal.momentum_7d[INSTRUMENTS[0]] == pytest.approx(268.0 / 100.0 - 1.0)


def test_window_replay_is_deterministic_accounted_and_policy_separated() -> None:
    marks, trades, funding = _fixture()
    result = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    assert result["decision_count"] == 26
    assert len(result["signals"]) == 26
    assert set(result["replays"]) == {"candidate", "cash", "always_long_perpetual"}
    assert all(
        signal["directions"] == {INSTRUMENTS[0]: 1, INSTRUMENTS[1]: -1}
        for signal in result["signals"]
    )
    cash = result["replays"]["cash"]["1.0x"]
    assert cash["final_equity"] == pytest.approx(1.0)
    assert cash["costs"] == 0
    for cost in COST_RATES:
        replay = result["replays"]["candidate"][cost]
        assert len(replay["weekly_returns"]) == 26
        assert replay["unaccounted_funding_settlement_count"] == 0
        assert replay["missing_decision_count"] == 0
        assert replay["final_equity"] == pytest.approx(
            1.0 + replay["gross_price_pnl"] + replay["funding_pnl"] - replay["costs"]
        )
    assert (
        result["replays"]["candidate"]["2.0x"]["final_equity"]
        < result["replays"]["candidate"]["1.0x"]["final_equity"]
    )


def test_replay_fails_closed_on_missing_hour() -> None:
    marks, trades, funding = _fixture()
    marks[INSTRUMENTS[0]].pop(100)
    with pytest.raises(C8AHistoricalReplayError, match="missing exact"):
        evaluate_historical_window(
            window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
        )


def test_replay_rejects_duplicate_and_unordered_funding() -> None:
    marks, trades, funding = _fixture()
    funding[INSTRUMENTS[0]].insert(2, dict(funding[INSTRUMENTS[0]][1]))
    with pytest.raises(
        C8AHistoricalReplayError, match="unordered or duplicate funding"
    ):
        evaluate_historical_window(
            window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
        )


def test_funding_never_changes_the_frozen_signal() -> None:
    marks, trades, funding = _fixture()
    first = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    for rows in funding.values():
        for row in rows:
            row["realized_rate"] = "-0.01"
    second = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    assert first["signals"] == second["signals"]
    assert (
        first["replays"]["candidate"]["1.0x"]["funding_pnl"]
        != second["replays"]["candidate"]["1.0x"]["funding_pnl"]
    )


def test_delayed_funding_uses_last_completed_not_future_candle() -> None:
    marks, trades, funding = _fixture()
    delayed = datetime.fromisoformat(
        funding[INSTRUMENTS[0]][1]["funding_time"]
    ) + timedelta(minutes=1)
    funding[INSTRUMENTS[0]][1]["funding_time"] = delayed.isoformat()
    result = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    event = next(
        value
        for value in result["replays"]["candidate"]["1.0x"]["funding_events"]
        if value["instrument"] == INSTRUMENTS[0]
        and value["timestamp"] == "2024-01-01T08:01:00Z"
    )
    assert event["timestamp"] == "2024-01-01T08:01:00Z"
    assert event["predecessor_mark_timestamp"] == "2024-01-01T07:00:00Z"
    assert event["predecessor_mark_close_time"] == "2024-01-01T08:00:00Z"


def test_window_does_not_invent_a_settlement_at_its_start_boundary() -> None:
    marks, trades, funding = _fixture()
    for instrument in INSTRUMENTS:
        funding[instrument].pop(0)
    result = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    events = result["replays"]["candidate"]["1.0x"]["funding_events"]
    assert events[0]["timestamp"] == "2024-01-01T08:00:00Z"
    assert all(event["timestamp"] != "2024-01-01T00:00:00Z" for event in events)


def test_terminal_boundary_candle_close_cannot_replace_terminal_trade_open() -> None:
    marks, trades, funding = _fixture()
    for rows in funding.values():
        for row in rows:
            row["realized_rate"] = "0"
    first = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    terminal_source = window_by_id("H1").end_exclusive - HOUR
    for instrument in INSTRUMENTS:
        row = next(
            value
            for value in marks[instrument]
            if datetime.fromisoformat(value["timestamp"]) == terminal_source
        )
        row["close"] = str(float(row["close"]) * 1.001)
    second = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    assert first["replays"]["candidate"]["1.0x"]["final_equity"] == pytest.approx(
        second["replays"]["candidate"]["1.0x"]["final_equity"]
    )


def test_buffer_breach_forces_next_open_close_then_waits_for_next_monday() -> None:
    marks, trades, funding = _fixture()
    first_decision = window_by_id("H1").first_scored_decision
    row = next(
        value
        for value in marks[INSTRUMENTS[1]]
        if datetime.fromisoformat(value["timestamp"]) == first_decision
    )
    row["close"] = "300"
    result = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    replay = result["replays"]["candidate"]["1.0x"]
    assert replay["margin_buffer_breach_count"] >= 1
    first_risk_close = next(
        event
        for event in replay["trade_events"]
        if event["instrument"] == INSTRUMENTS[1] and event["kind"] == "RISK_CLOSE"
    )
    assert first_risk_close["timestamp"] == "2024-01-01T01:00:00Z"
    next_monday = next(
        event
        for event in replay["trade_events"]
        if event["instrument"] == INSTRUMENTS[1]
        and event["timestamp"] == "2024-01-08T00:00:00Z"
    )
    assert next_monday["requested_direction"] == -1
    assert next_monday["executed_direction"] == -1
    assert (
        review_historical_window(
            result, mark_rows=marks, trade_rows=trades, funding_rows=funding
        )["status"]
        == "PASS"
    )


def test_physically_separate_reference_recomputes_every_policy_and_cost() -> None:
    marks, trades, funding = _fixture()
    producer = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    review = review_historical_window(
        producer, mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    assert review["status"] == "PASS"
    assert review["source_signal_recompute_passed"] is True
    assert review["imports_production_replay"] is False
    assert len(review["replay_reviews"]) == 9


def test_reference_recompute_detects_tampered_fee() -> None:
    marks, trades, funding = _fixture()
    producer = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    producer["replays"]["candidate"]["1.0x"]["trade_events"][0]["cost"] += 1.0
    review = review_historical_window(
        producer, mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    assert review["status"] == "FAIL"


def test_reference_recompute_detects_an_omitted_price_transition() -> None:
    marks, trades, funding = _fixture()
    producer = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    replay = producer["replays"]["candidate"]["1.0x"]
    removed = replay["price_events"].pop()
    replay["gross_price_pnl"] -= removed["price_pnl"]
    replay["final_equity"] -= removed["price_pnl"]
    review = review_historical_window(
        producer, mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    assert review["status"] == "FAIL"
    assert (
        review["replay_reviews"]["candidate:1.0x"]["checks"][
            "complete_price_event_coverage"
        ]
        is False
    )


def test_reference_recompute_rejects_a_fabricated_equity_path_and_drawdown() -> None:
    marks, trades, funding = _fixture()
    producer = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    replay = producer["replays"]["candidate"]["1.0x"]
    replay["complete_equity_path"] = [1.0] * len(replay["complete_equity_path"])
    replay["maximum_drawdown"] = 0.0
    review = review_historical_window(
        producer, mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    candidate = review["replay_reviews"]["candidate:1.0x"]
    assert review["status"] == "FAIL"
    assert candidate["checks"]["drawdown_recompute"] is True
    assert candidate["checks"]["source_ordered_state_recompute"] is False


def test_reference_recomputes_pooled_gates_and_final_verdict() -> None:
    marks, trades, funding = _fixture()
    window = evaluate_historical_window(
        window_id="H1", mark_rows=marks, trade_rows=trades, funding_rows=funding
    )
    windows = {f"H{index}": window for index in range(1, 6)}
    producer = summarize_h1_h5(windows)
    review = review_pooled_summary(producer, windows)
    assert review["status"] == "PASS"
    assert review["reference_final_verdict"] == producer["overall_economic_verdict"]
    assert review["imports_production_replay"] is False


def test_each_frozen_h1_h5_grid_completes_source_ordered_independent_review() -> None:
    windows = {}
    for window_id in ("H1", "H2", "H3", "H4", "H5"):
        marks, trades, funding = _fixture(window_id=window_id)
        producer = evaluate_historical_window(
            window_id=window_id,
            mark_rows=marks,
            trade_rows=trades,
            funding_rows=funding,
        )
        independent = review_historical_window(
            producer, mark_rows=marks, trade_rows=trades, funding_rows=funding
        )
        assert producer["decision_count"] == 26
        assert independent["status"] == "PASS"
        assert all(
            value["checks"]["source_ordered_state_recompute"] is True
            for value in independent["replay_reviews"].values()
        )
        windows[window_id] = producer
    summary = summarize_h1_h5(windows)
    pooled = review_pooled_summary(summary, windows)
    assert sum(window["decision_count"] for window in windows.values()) == 130
    assert pooled["status"] == "PASS"
    assert pooled["reference_final_verdict"] == summary["overall_economic_verdict"]


def test_all_decision_times_are_frozen_mondays() -> None:
    for window_id in ("H1", "H2", "H3", "H4", "H5"):
        values = decision_times(window_id)
        assert len(values) == 26
        assert all(value.weekday() == 0 and value.hour == 0 for value in values)
