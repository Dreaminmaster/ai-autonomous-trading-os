from __future__ import annotations

import copy
import math
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from atos.c14a_contract import CANDIDATE_ID, CANDIDATE_POOL, HISTORICAL_WINDOWS, HOUR
from atos.c14a_historical_independent import (
    review_historical_window,
    review_pooled_summary,
)
from atos.c14a_historical_replay import (
    POLICIES,
    C14AHistoricalReplayError,
    build_signal,
    evaluate_historical_window,
    evaluate_historical_window_matrix,
    summarize_h1_h5,
)

SELECTED = CANDIDATE_POOL


def _signal_inputs(decision):
    cutoff = decision - timedelta(hours=24)
    first = cutoff - timedelta(days=28)
    opens: dict[str, dict[object, Decimal]] = {}
    quote_volumes: dict[str, dict[object, Decimal]] = {}
    for asset_index, instrument in enumerate(SELECTED):
        daily = [0.0001 * ((day % 7) + 1) for day in range(28)]
        daily[asset_index % 28] += 0.002 * (asset_index + 1)
        price = 100.0 + asset_index
        values = {first: Decimal(f"{price:.18f}")}
        for day, value in enumerate(daily, start=1):
            price *= math.exp(value)
            values[first + timedelta(days=day)] = Decimal(f"{price:.18f}")
        opens[instrument] = values
        quote_volumes[instrument] = {
            first + timedelta(hours=hour): Decimal(
                1000 + asset_index * 250 + (hour % 24)
            )
            for hour in range(28 * 24)
        }
    return opens, quote_volumes


def _window_sources():
    window = HISTORICAL_WINDOWS[0]
    trade_start = window.start - timedelta(days=29)
    trade_rows: dict[str, list[dict[str, str]]] = {}
    mark_rows: dict[str, list[dict[str, str]]] = {}
    funding_rows: dict[str, list[dict[str, str]]] = {}
    for asset_index, instrument in enumerate(SELECTED):
        prices: dict[object, Decimal] = {}
        price = 100.0 + asset_index
        current = trade_start
        index = 0
        while current <= window.end_exclusive:
            drift = 0.00002 * math.sin(index / (11 + asset_index))
            tail = 0.00008 * (asset_index - 3.5) * math.sin(index / 173)
            price *= math.exp(drift + tail)
            prices[current] = Decimal(f"{price:.18f}")
            current += HOUR
            index += 1
        trade_rows[instrument] = [
            {
                "timestamp": stamp.isoformat(),
                "open": format(value, "f"),
                "volume_quote": format(
                    Decimal(1000 + asset_index * 250 + index % 24), "f"
                ),
            }
            for index, (stamp, value) in enumerate(prices.items())
        ]
        mark_rows[instrument] = [
            {"timestamp": stamp.isoformat(), "close": format(value, "f")}
            for stamp, value in prices.items()
            if window.start - HOUR <= stamp < window.end_exclusive
        ]
        funding = []
        current = window.start
        while current < window.end_exclusive:
            funding.append(
                {"funding_time": current.isoformat(), "realized_rate": "0"}
            )
            current += timedelta(hours=8)
        funding_rows[instrument] = funding
    return trade_rows, mark_rows, funding_rows


def test_signal_uses_28_complete_days_with_fixed_24_hour_gap() -> None:
    decision = HISTORICAL_WINDOWS[0].start
    opens, quote_volumes = _signal_inputs(decision)
    result = build_signal(
        decision,
        selected_universe=SELECTED,
        trade_opens=opens,
        trade_quote_volumes=quote_volumes,
    )
    assert result["policy"] == CANDIDATE_ID
    assert result["signal_cutoff"] == "2023-12-31T00:00:00Z"
    assert result["first_signal_open"] == "2023-12-03T00:00:00Z"
    assert result["daily_return_count"] == 28
    assert result["hourly_quote_volume_count"] == 672
    assert len(result["longs"]) == len(result["shorts"]) == 2
    assert sum(value != 0 for value in result["directions"].values()) == 4
    assert all(len(row["daily_log_returns"]) == 28 for row in result["rows"])
    assert all(len(row["daily_quote_volumes"]) == 28 for row in result["rows"])
    assert all(len(row["daily_amihud"]) == 28 for row in result["rows"])

    forbidden = copy.deepcopy(opens)
    forbidden[SELECTED[0]][decision - HOUR] = Decimal(999999)
    assert build_signal(
        decision,
        selected_universe=SELECTED,
        trade_opens=forbidden,
        trade_quote_volumes=quote_volumes,
    ) == result


@pytest.mark.parametrize(
    "policy",
    ["MeanAbsoluteReturnRankComparator", "InverseQuoteVolumeRankComparator"],
)
def test_fixed_comparators_use_same_long_short_geometry(policy: str) -> None:
    opens, quote_volumes = _signal_inputs(HISTORICAL_WINDOWS[0].start)
    signal = build_signal(
        HISTORICAL_WINDOWS[0].start,
        selected_universe=SELECTED,
        trade_opens=opens,
        trade_quote_volumes=quote_volumes,
        policy=policy,
    )
    assert signal["policy"] == policy
    assert len(signal["longs"]) == len(signal["shorts"]) == 2
    assert set(signal["longs"]).isdisjoint(signal["shorts"])
    assert sum(value != 0 for value in signal["directions"].values()) == 4


def test_quote_volume_is_exactly_aggregated_and_comparator_ablation_is_distinct() -> None:
    decision = HISTORICAL_WINDOWS[0].start
    opens, quote_volumes = _signal_inputs(decision)
    baseline_mean_return = build_signal(
        decision,
        selected_universe=SELECTED,
        trade_opens=opens,
        trade_quote_volumes=quote_volumes,
        policy="MeanAbsoluteReturnRankComparator",
    )
    shifted = copy.deepcopy(quote_volumes)
    for stamp in shifted[SELECTED[0]]:
        shifted[SELECTED[0]][stamp] /= Decimal(1000)
    candidate = build_signal(
        decision,
        selected_universe=SELECTED,
        trade_opens=opens,
        trade_quote_volumes=shifted,
    )
    inverse_volume = build_signal(
        decision,
        selected_universe=SELECTED,
        trade_opens=opens,
        trade_quote_volumes=shifted,
        policy="InverseQuoteVolumeRankComparator",
    )
    shifted_mean_return = build_signal(
        decision,
        selected_universe=SELECTED,
        trade_opens=opens,
        trade_quote_volumes=shifted,
        policy="MeanAbsoluteReturnRankComparator",
    )
    assert SELECTED[0] in candidate["longs"]
    assert SELECTED[0] in inverse_volume["longs"]
    assert baseline_mean_return["directions"] == shifted_mean_return["directions"]
    for row in candidate["rows"]:
        daily_amihud = [Decimal(value) for value in row["daily_amihud"]]
        assert Decimal(row["amihud_illiquidity"]) == sum(
            daily_amihud, Decimal(0)
        ) / Decimal(28)


def test_signal_fails_closed_on_missing_or_zero_hourly_quote_volume() -> None:
    decision = HISTORICAL_WINDOWS[0].start
    opens, quote_volumes = _signal_inputs(decision)
    missing = copy.deepcopy(quote_volumes)
    missing[SELECTED[0]].pop(next(iter(missing[SELECTED[0]])))
    with pytest.raises(C14AHistoricalReplayError, match="quote volume"):
        build_signal(
            decision,
            selected_universe=SELECTED,
            trade_opens=opens,
            trade_quote_volumes=missing,
        )
    zero = copy.deepcopy(quote_volumes)
    zero[SELECTED[0]][next(iter(zero[SELECTED[0]]))] = Decimal(0)
    with pytest.raises(C14AHistoricalReplayError, match="quote volume"):
        build_signal(
            decision,
            selected_universe=SELECTED,
            trade_opens=opens,
            trade_quote_volumes=zero,
        )


def test_signal_rejects_missing_cutoff_and_universe_reordering() -> None:
    decision = HISTORICAL_WINDOWS[0].start
    opens, quote_volumes = _signal_inputs(decision)
    del opens[SELECTED[0]][decision - timedelta(hours=24)]
    with pytest.raises(C14AHistoricalReplayError, match="missing exact trade open"):
        build_signal(
            decision,
            selected_universe=SELECTED,
            trade_opens=opens,
            trade_quote_volumes=quote_volumes,
        )
    with pytest.raises(C14AHistoricalReplayError, match="selected universe drift"):
        build_signal(
            decision,
            selected_universe=tuple(reversed(SELECTED)),
            trade_opens=_signal_inputs(decision)[0],
            trade_quote_volumes=_signal_inputs(decision)[1],
        )


def test_window_and_matrix_reconcile_every_event_cost_and_policy() -> None:
    trades, marks, funding = _window_sources()
    result = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trades,
        mark_rows=marks,
        funding_rows=funding,
        cost_label="1.0x",
    )
    assert result["decision_count"] == 26
    assert result["signal_count"] == 26
    assert result["nonflat_direction_count"] == 104
    assert Decimal(result["reconciliation_residual"]).copy_abs() <= Decimal("1e-10")
    assert result["live_state"] == "LIVE_FORBIDDEN"
    assert len(result["weekly_returns"]) == 26
    assert result["complete_hourly_equity_path"][-1]["event"] == "TERMINAL_CLOSE"

    matrix = evaluate_historical_window_matrix(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trades,
        mark_rows=marks,
        funding_rows=funding,
    )
    assert matrix["result_cell_count"] == 12
    assert set(matrix["replays"]) == set(POLICIES)
    review = review_historical_window(
        matrix, trade_rows=trades, mark_rows=marks, funding_rows=funding
    )
    assert review["status"] == "PASS"
    assert all(
        cell["status"] == "PASS" for cell in review["replay_reviews"].values()
    )


def test_window_rejects_missing_required_trade_hour() -> None:
    trades, marks, funding = _window_sources()
    trades[SELECTED[0]].pop(10)
    with pytest.raises(C14AHistoricalReplayError, match="misaligned|missing exact"):
        evaluate_historical_window(
            "H1",
            selected_universe=SELECTED,
            trade_rows=trades,
            mark_rows=marks,
            funding_rows=funding,
            cost_label="1.0x",
        )


def test_delayed_funding_uses_actual_timestamp_and_predecessor_mark() -> None:
    trades, marks, funding = _window_sources()
    delayed = HISTORICAL_WINDOWS[0].start + timedelta(minutes=30)
    funding[SELECTED[0]][0] = {
        "funding_time": delayed.isoformat(),
        "realized_rate": "0.001",
    }
    result = evaluate_historical_window(
        "H1",
        selected_universe=SELECTED,
        trade_rows=trades,
        mark_rows=marks,
        funding_rows=funding,
        cost_label="1.0x",
    )
    events = result["complete_hourly_equity_path"]
    assert any(row["timestamp"] == delayed.isoformat().replace("+00:00", "Z") for row in events)
    assert result["funding_settlement_count"] > 0


def _synthetic_pooled_windows() -> dict[str, dict[str, object]]:
    windows: dict[str, dict[str, object]] = {}
    policy_level = {
        CANDIDATE_ID: (Decimal("0.030"), Decimal("0.0020"), 0.0002),
        "MeanAbsoluteReturnRankComparator": (
            Decimal("0.010"),
            Decimal("0.0004"),
            0.0012,
        ),
        "InverseQuoteVolumeRankComparator": (
            Decimal("0.012"),
            Decimal("0.0005"),
            0.0010,
        ),
    }
    for window_index, window in enumerate(HISTORICAL_WINDOWS):
        replays: dict[str, dict[str, dict[str, object]]] = {}
        for policy in POLICIES:
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
                    base, weekly_level, noise = policy_level[policy]
                    net_return = base - Decimal(cost_index) * Decimal("0.004")
                    weekly = [
                        weekly_level
                        + Decimal(str(noise * math.sin(window_index * 26 + week)))
                        - Decimal(cost_index) * Decimal("0.00005")
                        for week in range(26)
                    ]
                    turnover = Decimal(5 if policy == CANDIDATE_ID else 6)
                    drawdown = Decimal("0.02" if policy == CANDIDATE_ID else "0.03")
                    contributions = {
                        instrument: {
                            "price_pnl": "4",
                            "funding_pnl": "0",
                            "costs": "0.25",
                            "net": "3.75",
                        }
                        for instrument in SELECTED
                    }
                    nonflat = 104
                final_equity = Decimal(1000) * (Decimal(1) + net_return)
                replays[policy][cost_label] = {
                    "final_equity": format(final_equity, "f"),
                    "net_return": format(net_return, "f"),
                    "weekly_returns": [format(value, "f") for value in weekly],
                    "weekly_buckets": [
                        {
                            "start_equity": "1000",
                            "weekly_pnl": format(value * Decimal(1000), "f"),
                        }
                        for value in weekly
                    ],
                    "maximum_drawdown": format(drawdown, "f"),
                    "turnover_sum": format(turnover, "f"),
                    "decision_count": 26,
                    "signal_count": 0 if policy == "CashComparator" else 26,
                    "nonflat_direction_count": nonflat,
                    "funding_settlement_count": 100,
                    "equity_buffer_breach_count": 0,
                    "forced_close_count": 0,
                    "contributions": contributions,
                    "component_totals": {"price_pnl": "32", "funding_pnl": "0", "costs": "2"},
                    "reconciliation_residual": "0",
                }
        btc = [
            Decimal(str(0.01 * math.sin((window_index * 26 + week) * 0.73)))
            for week in range(26)
        ]
        windows[window.window_id] = {
            "selected_universe": list(SELECTED),
            "replays": replays,
            "btc_weekly_mark_returns": [format(value, "f") for value in btc],
        }
    return windows


def test_pooled_summary_applies_all_gates_both_comparators_and_trial_629() -> None:
    windows = _synthetic_pooled_windows()
    result = summarize_h1_h5(windows)
    assert result["declared_program_familywise_trial_count"] == 629
    assert result["overall_economic_verdict"] == "ECONOMIC_PASS"
    assert all(result["eligibility_gates"].values())
    assert result["pooled"][CANDIDATE_ID]["1.0x"]["decision_count"] == 130
    assert result["pooled"][CANDIDATE_ID]["1.0x"]["nonflat_direction_count"] == 520
    assert Decimal(
        result["pooled"][CANDIDATE_ID]["1.0x"]["annualized_one_way_turnover"]
    ) == Decimal("0.005")
    review = review_pooled_summary(result, windows)
    assert review["status"] == "PASS"
    assert review["reference_final_verdict"] == "ECONOMIC_PASS"


def test_pooled_summary_never_promotes_failed_candidate_or_tampered_result() -> None:
    windows = _synthetic_pooled_windows()
    windows["H3"]["replays"][CANDIDATE_ID]["1.0x"]["final_equity"] = "999"
    windows["H3"]["replays"][CANDIDATE_ID]["1.0x"]["net_return"] = "-0.001"
    result = summarize_h1_h5(windows)
    assert result["overall_economic_verdict"] == "ECONOMIC_FAIL"
    assert result["selected_policy"] is None
    assert "all_five_windows_positive" in result["rejection_reasons"]
    tampered = copy.deepcopy(result)
    tampered["overall_economic_verdict"] = "ECONOMIC_PASS"
    assert review_pooled_summary(tampered, windows)["status"] == "FAIL"


def test_independent_module_never_imports_production_replay_or_finalizer() -> None:
    source = (Path(__file__).parents[1] / "src/atos/c14a_historical_independent.py").read_text()
    assert "from atos.c14a_historical_replay" not in source
    assert "import atos.c14a_historical_replay" not in source
    assert "summarize_h1_h5" not in source
