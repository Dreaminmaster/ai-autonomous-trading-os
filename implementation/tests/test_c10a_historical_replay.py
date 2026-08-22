from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from atos.c10a_contract import (
    BETA_LOOKBACK_RETURNS,
    CANDIDATE_ID,
    CANDIDATE_POOL,
    EXPECTED_DECISIONS_PER_WINDOW,
    HISTORICAL_WINDOWS,
    HOUR,
)
from atos.c10a_historical_independent import (
    review_historical_window,
    review_pooled_summary,
)
from atos.c10a_historical_replay import (
    C10AHistoricalReplayError,
    build_signal,
    evaluate_historical_window,
    evaluate_historical_window_matrix,
    summarize_h1_h5,
)

SELECTED = CANDIDATE_POOL[:8]


def _signal_marks(
    decision: datetime,
) -> dict[str, dict[datetime, Decimal]]:
    start = decision - (BETA_LOOKBACK_RETURNS + 2) * HOUR
    end = decision
    times = []
    current = start
    while current < end:
        times.append(current)
        current += HOUR
    output: dict[str, dict[datetime, Decimal]] = {}
    for asset_index, instrument in enumerate(SELECTED):
        price = 100.0 + asset_index
        values: dict[datetime, Decimal] = {}
        for index, stamp in enumerate(times):
            common = 0.0002 * math.sin(index / 17.0) + 0.0001 * math.cos(index / 41.0)
            late = (
                (asset_index - 3.5) * 0.00002
                if index >= len(times) - 672
                else 0.0
            )
            idiosyncratic = 0.00003 * math.sin(index / (11.0 + asset_index))
            price *= math.exp(common + late + idiosyncratic)
            values[stamp] = Decimal(f"{price:.18f}")
        output[instrument] = values
    return output


def _window_sources():
    window = HISTORICAL_WINDOWS[0]
    mark_start = window.start - (BETA_LOOKBACK_RETURNS + 2) * HOUR
    mark_times = []
    current = mark_start
    while current < window.end_exclusive:
        mark_times.append(current)
        current += HOUR

    mark_rows: dict[str, list[dict[str, str]]] = {}
    trade_rows: dict[str, list[dict[str, str]]] = {}
    funding_rows: dict[str, list[dict[str, str]]] = {}
    for asset_index, instrument in enumerate(SELECTED):
        price = 100.0 + asset_index
        marks: list[dict[str, str]] = []
        by_time: dict[datetime, Decimal] = {}
        for index, stamp in enumerate(mark_times):
            common = 0.00012 * math.sin(index / 19.0) + 0.00007 * math.cos(index / 53.0)
            regime = (asset_index - 3.5) * 0.000008 * math.sin(index / 311.0)
            idiosyncratic = 0.00004 * math.sin(index / (13.0 + asset_index))
            price *= math.exp(common + regime + idiosyncratic)
            value = Decimal(f"{price:.18f}")
            by_time[stamp] = value
            marks.append({"timestamp": stamp.isoformat(), "close": format(value, "f")})
        mark_rows[instrument] = marks

        trades: list[dict[str, str]] = []
        current = window.start
        while current <= window.end_exclusive:
            prior = by_time[current - HOUR]
            trades.append(
                {
                    "timestamp": current.isoformat(),
                    "open": format(prior, "f"),
                }
            )
            current += HOUR
        trade_rows[instrument] = trades

        funding: list[dict[str, str]] = []
        current = window.start
        while current < window.end_exclusive:
            funding.append(
                {
                    "funding_time": current.isoformat(),
                    "realized_rate": "0",
                }
            )
            current += timedelta(hours=8)
        funding_rows[instrument] = funding
    return trade_rows, mark_rows, funding_rows


def test_signal_uses_exact_2016_returns_and_excludes_t_minus_one_candle() -> None:
    decision = datetime(2024, 1, 1, tzinfo=UTC)
    marks = _signal_marks(decision)
    first = build_signal(
        decision,
        selected_universe=SELECTED,
        mark_closes=marks,
    )
    assert first["policy"] == CANDIDATE_ID
    assert first["last_permitted_mark_timestamp"] == "2023-12-31T22:00:00Z"
    assert first["regression_return_count"] == 2016
    assert len(first["longs"]) == 2
    assert len(first["shorts"]) == 2
    assert sum(value != 0 for value in first["directions"].values()) == 4

    forbidden = decision - HOUR
    changed = {instrument: dict(values) for instrument, values in marks.items()}
    for instrument in SELECTED:
        changed[instrument][forbidden] = Decimal(999999999)
    second = build_signal(
        decision,
        selected_universe=SELECTED,
        mark_closes=changed,
    )
    assert second["directions"] == first["directions"]
    assert second["rows"] == first["rows"]


def test_signal_rejects_missing_hour_or_zero_factor_variance() -> None:
    decision = datetime(2024, 1, 1, tzinfo=UTC)
    marks = _signal_marks(decision)
    missing = {instrument: dict(values) for instrument, values in marks.items()}
    missing[SELECTED[0]].pop(decision - 100 * HOUR)
    with pytest.raises(C10AHistoricalReplayError, match="missing exact mark hour"):
        build_signal(decision, selected_universe=SELECTED, mark_closes=missing)

    constant = {
        instrument: {stamp: Decimal(100) for stamp in next(iter(marks.values()))}
        for instrument in SELECTED
    }
    with pytest.raises(C10AHistoricalReplayError, match="factor variance"):
        build_signal(decision, selected_universe=SELECTED, mark_closes=constant)


def test_raw_return_comparator_has_same_fixed_long_short_geometry() -> None:
    decision = datetime(2024, 1, 1, tzinfo=UTC)
    signal = build_signal(
        decision,
        selected_universe=SELECTED,
        mark_closes=_signal_marks(decision),
        policy="RawReturnMomentumComparator",
    )
    assert signal["policy"] == "RawReturnMomentumComparator"
    assert len(signal["longs"]) == 2
    assert len(signal["shorts"]) == 2
    assert set(signal["longs"]).isdisjoint(signal["shorts"])


def test_window_replay_reconciles_costs_and_all_hourly_events() -> None:
    trade_rows, mark_rows, funding_rows = _window_sources()
    result = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=funding_rows,
        cost_label="1.0x",
    )
    assert result["policy"] == CANDIDATE_ID
    assert result["decision_count"] == EXPECTED_DECISIONS_PER_WINDOW
    assert result["signal_count"] == EXPECTED_DECISIONS_PER_WINDOW
    assert result["nonflat_direction_count"] == 104
    assert len(result["weekly_returns"]) == EXPECTED_DECISIONS_PER_WINDOW
    assert Decimal(result["component_totals"]["costs"]) > 0
    assert abs(Decimal(result["reconciliation_residual"])) <= Decimal("1e-10")
    assert result["equity_buffer_breach_count"] == 0
    assert result["forced_close_count"] == 0
    path = result["complete_hourly_equity_path"]
    events = {row["event"] for row in path}
    assert {
        "FUNDING",
        "SCHEDULED_OPEN_MARK",
        "SCHEDULED_REBALANCE",
        "HOURLY_MARK",
        "TERMINAL_OPEN_MARK",
        "TERMINAL_CLOSE",
    } <= events
    peak = Decimal(path[0]["equity"])
    drawdown = Decimal(0)
    for row in path:
        equity = Decimal(row["equity"])
        peak = max(peak, equity)
        drawdown = max(drawdown, Decimal(1) - equity / peak)
    assert drawdown == Decimal(result["maximum_drawdown"])
    assert result["authenticated"] is False
    assert result["paper_state"] == "PAPER_CLOSED"
    assert result["shadow_state"] == "SHADOW_CLOSED"
    assert result["live_state"] == "LIVE_FORBIDDEN"


def test_cost_stress_is_recomputed_and_cash_remains_exact() -> None:
    trade_rows, mark_rows, funding_rows = _window_sources()
    expected = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=funding_rows,
        cost_label="1.0x",
    )
    stress = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=funding_rows,
        cost_label="2.0x",
    )
    assert Decimal(stress["component_totals"]["costs"]) > Decimal(
        expected["component_totals"]["costs"]
    )
    assert Decimal(stress["final_equity"]) < Decimal(expected["final_equity"])

    cash = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows={},
        mark_rows={},
        funding_rows={},
        cost_label="1.0x",
        policy="CashComparator",
    )
    assert cash["final_equity"] == "1000"
    assert cash["weekly_returns"] == ["0"] * 26


def test_funding_uses_signed_quantity_and_pre_rebalance_event_order() -> None:
    trade_rows, mark_rows, funding_rows = _window_sources()
    zero = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=funding_rows,
        cost_label="1.0x",
        policy="AlwaysLongSelectedUniverseComparator",
    )
    first_only = {
        instrument: [dict(row) for row in rows]
        for instrument, rows in funding_rows.items()
    }
    for rows in first_only.values():
        rows[0]["realized_rate"] = "0.50"
    unchanged = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=first_only,
        cost_label="1.0x",
        policy="AlwaysLongSelectedUniverseComparator",
    )
    assert unchanged["final_equity"] == zero["final_equity"]

    positive_rates = {
        instrument: [
            {**row, "realized_rate": "0.001"}
            for row in rows
        ]
        for instrument, rows in funding_rows.items()
    }
    paying_longs = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=positive_rates,
        cost_label="1.0x",
        policy="AlwaysLongSelectedUniverseComparator",
    )
    assert Decimal(paying_longs["component_totals"]["funding_pnl"]) < 0
    assert Decimal(paying_longs["final_equity"]) < Decimal(zero["final_equity"])

    boundary_rates = {
        instrument: [dict(row) for row in rows]
        for instrument, rows in funding_rows.items()
    }
    first_rebalance_boundary = HISTORICAL_WINDOWS[0].start + timedelta(days=7)
    for rows in boundary_rates.values():
        boundary = next(
            row
            for row in rows
            if datetime.fromisoformat(row["funding_time"])
            == first_rebalance_boundary
        )
        boundary["realized_rate"] = "0.10"
    boundary_result = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=boundary_rates,
        cost_label="1.0x",
        policy="AlwaysLongSelectedUniverseComparator",
    )
    assert Decimal(boundary_result["weekly_returns"][0]) < Decimal(
        zero["weekly_returns"][0]
    )


def test_delayed_official_funding_uses_actual_time_and_predecessor_mark() -> None:
    trade_rows, mark_rows, funding_rows = _window_sources()
    exact = {
        instrument: [dict(row) for row in rows]
        for instrument, rows in funding_rows.items()
    }
    exact[SELECTED[0]][1]["realized_rate"] = "0.001"
    delayed = {
        instrument: [dict(row) for row in rows]
        for instrument, rows in exact.items()
    }
    exact_time = datetime.fromisoformat(delayed[SELECTED[0]][1]["funding_time"])
    delayed_time = exact_time + timedelta(seconds=8)
    delayed[SELECTED[0]][1]["funding_time"] = delayed_time.isoformat()

    exact_result = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=exact,
        cost_label="1.0x",
        policy="AlwaysLongSelectedUniverseComparator",
    )
    delayed_result = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=delayed,
        cost_label="1.0x",
        policy="AlwaysLongSelectedUniverseComparator",
    )

    assert delayed_result["final_equity"] == exact_result["final_equity"]
    assert (
        delayed_result["contributions"][SELECTED[0]]["funding_pnl"]
        == exact_result["contributions"][SELECTED[0]]["funding_pnl"]
    )
    assert any(
        row["event"] == "FUNDING"
        and row["timestamp"]
        == delayed_time.isoformat().replace("+00:00", "Z")
        for row in delayed_result["complete_hourly_equity_path"]
    )

    producer = evaluate_historical_window_matrix(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=delayed,
    )
    assert review_historical_window(
        producer,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=delayed,
    )["status"] == "PASS"


def test_window_rejects_missing_trade_hour_and_unaccounted_source_shape() -> None:
    trade_rows, mark_rows, funding_rows = _window_sources()
    trade_rows[SELECTED[0]].pop(100)
    with pytest.raises(C10AHistoricalReplayError, match="misaligned|missing exact"):
        evaluate_historical_window(
            "H1",
            selected_universe=SELECTED,
            trade_rows=trade_rows,
            mark_rows=mark_rows,
            funding_rows=funding_rows,
            cost_label="1.0x",
        )


def _synthetic_pooled_windows() -> dict[str, dict[str, object]]:
    windows: dict[str, dict[str, object]] = {}
    for window_index, window in enumerate(HISTORICAL_WINDOWS):
        btc = [
            Decimal(str(0.01 * math.sin((window_index * 26 + week) * 0.73)))
            for week in range(26)
        ]
        replays: dict[str, dict[str, dict[str, object]]] = {}
        for policy in (
            CANDIDATE_ID,
            "RawReturnMomentumComparator",
            "AlwaysLongSelectedUniverseComparator",
            "CashComparator",
        ):
            replays[policy] = {}
            for cost_index, cost_label in enumerate(("1.0x", "1.5x", "2.0x")):
                if policy == "CashComparator":
                    net_return = Decimal(0)
                    weekly = [Decimal(0)] * 26
                    turnover = Decimal(0)
                    drawdown = Decimal(0)
                    contributions: dict[str, dict[str, str]] = {}
                    nonflat = 0
                else:
                    base = {
                        CANDIDATE_ID: Decimal("0.030"),
                        "RawReturnMomentumComparator": Decimal("0.010"),
                        "AlwaysLongSelectedUniverseComparator": Decimal("0.015"),
                    }[policy]
                    net_return = base - Decimal(cost_index) * Decimal("0.004")
                    weekly_level, weekly_noise = {
                        CANDIDATE_ID: (Decimal("0.002"), 0.0003),
                        "RawReturnMomentumComparator": (Decimal("0.0005"), 0.0015),
                        "AlwaysLongSelectedUniverseComparator": (
                            Decimal("0.001"),
                            0.001,
                        ),
                    }[policy]
                    weekly = [
                        weekly_level
                        + Decimal(
                            str(weekly_noise * math.sin(window_index * 26 + week))
                        )
                        - Decimal(cost_index) * Decimal("0.00005")
                        for week in range(26)
                    ]
                    turnover = (
                        Decimal(5)
                        if policy == CANDIDATE_ID
                        else Decimal(6)
                    )
                    drawdown = (
                        Decimal("0.02")
                        if policy == CANDIDATE_ID
                        else Decimal("0.03")
                    )
                    contributions = {
                        instrument: {
                            "price_pnl": "4",
                            "funding_pnl": "0",
                            "costs": "0.25",
                            "net": "3.75",
                        }
                        for instrument in SELECTED
                    }
                    nonflat = 104 if policy != "AlwaysLongSelectedUniverseComparator" else 0
                final_equity = Decimal(1000) * (Decimal(1) + net_return)
                replays[policy][cost_label] = {
                    "final_equity": format(final_equity, "f"),
                    "net_return": format(net_return, "f"),
                    "weekly_returns": [format(value, "f") for value in weekly],
                    "weekly_buckets": [
                        {"weekly_pnl": format(value * Decimal(1000), "f")}
                        for value in weekly
                    ],
                    "maximum_drawdown": format(drawdown, "f"),
                    "turnover_sum": format(turnover, "f"),
                    "decision_count": 26,
                    "signal_count": 26 if policy != "CashComparator" else 0,
                    "nonflat_direction_count": nonflat,
                    "funding_settlement_count": 100,
                    "equity_buffer_breach_count": 0,
                    "forced_close_count": 0,
                    "contributions": contributions,
                    "component_totals": {
                        "price_pnl": "32",
                        "funding_pnl": "0",
                        "costs": "2",
                    },
                    "reconciliation_residual": "0",
                }
        windows[window.window_id] = {
            "selected_universe": list(SELECTED),
            "replays": replays,
            "btc_weekly_mark_returns": [format(value, "f") for value in btc],
        }
    return windows


def test_pooled_summary_applies_program_correction_and_raw_comparator_gates() -> None:
    result = summarize_h1_h5(_synthetic_pooled_windows())
    candidate = result["pooled"][CANDIDATE_ID]["1.0x"]
    assert result["overall_economic_verdict"] == "ECONOMIC_PASS"
    assert result["declared_program_familywise_trial_count"] == 627
    assert Decimal(candidate["bonferroni_adjusted_psr"]) >= Decimal("0.95")
    assert candidate["decision_count"] == 130
    assert candidate["nonflat_direction_count"] == 520
    assert abs(Decimal(result["candidate_btc_beta"])) <= Decimal("0.20")
    assert all(result["eligibility_gates"].values())


def test_pooled_summary_cannot_promote_best_ineligible_candidate() -> None:
    windows = _synthetic_pooled_windows()
    windows["H3"]["replays"][CANDIDATE_ID]["1.0x"]["final_equity"] = "999"
    windows["H3"]["replays"][CANDIDATE_ID]["1.0x"]["net_return"] = "-0.001"
    result = summarize_h1_h5(windows)
    assert result["overall_economic_verdict"] == "ECONOMIC_FAIL"
    assert result["selected_policy"] is None
    assert "all_five_windows_positive" in result["rejection_reasons"]


def test_independent_window_recompute_covers_every_cell_and_detects_tamper() -> None:
    trade_rows, mark_rows, funding_rows = _window_sources()
    producer = evaluate_historical_window_matrix(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=funding_rows,
    )
    review = review_historical_window(
        producer,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=funding_rows,
    )
    assert review["status"] == "PASS"
    assert len(review["replay_reviews"]) == 12

    producer["replays"][CANDIDATE_ID]["1.0x"]["final_equity"] = "999999"
    tampered = review_historical_window(
        producer,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=funding_rows,
    )
    assert tampered["status"] == "FAIL"
    assert (
        tampered["replay_reviews"][f"{CANDIDATE_ID}:1.0x"]["checks"][
            "scalar_recompute"
        ]
        is False
    )


def test_independent_window_recompute_matches_nonzero_signed_funding() -> None:
    trade_rows, mark_rows, funding_rows = _window_sources()
    for asset_index, instrument in enumerate(SELECTED):
        for settlement_index, row in enumerate(funding_rows[instrument]):
            direction = Decimal(1 if (asset_index + settlement_index) % 2 else -1)
            magnitude = Decimal(asset_index % 3 + 1) / Decimal(100000)
            row["realized_rate"] = format(direction * magnitude, "f")

    producer = evaluate_historical_window_matrix(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=funding_rows,
    )
    review = review_historical_window(
        producer,
        trade_rows=trade_rows,
        mark_rows=mark_rows,
        funding_rows=funding_rows,
    )

    assert review["status"] == "PASS"
    assert all(
        result["checks"]["scalar_recompute"]
        for result in review["replay_reviews"].values()
    )


def test_independent_pooled_recompute_matches_metrics_gates_and_verdict() -> None:
    windows = _synthetic_pooled_windows()
    producer = summarize_h1_h5(windows)
    review = review_pooled_summary(producer, windows)
    assert review["status"] == "PASS"
    assert review["reference_final_verdict"] == "ECONOMIC_PASS"

    producer["candidate_btc_beta"] = "9"
    assert review_pooled_summary(producer, windows)["status"] == "FAIL"


def test_independent_module_does_not_import_production_engine() -> None:
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "atos"
        / "c10a_historical_independent.py"
    ).read_text(encoding="utf-8")
    assert "from atos.c10a_historical_replay" not in source
    assert "from atos.c10a_historical_signal" not in source
    assert "from atos.c10a_historical_ledger" not in source
    assert "from atos.phase_c_research_program_guard" not in source
