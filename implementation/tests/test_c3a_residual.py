from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from atos.c3a_residual import (
    COST_RATES,
    POLICY_IDS,
    compute_indicators,
    frame_from_rows,
    run_screen,
    simulate_window,
)


def indicator_frame(periods: int = 40) -> pd.DataFrame:
    index = pd.date_range("2024-01-01T00:00:00Z", periods=periods, freq="4h")
    frame = pd.DataFrame(index=index)
    for asset, price in (("BTC", 100.0), ("ETH", 50.0), ("SOL", 20.0)):
        frame[f"{asset}_open"] = price
        frame[f"{asset}_close"] = price
    frame["ETH_z"] = -1.0
    frame["SOL_z"] = -1.0
    frame["btc_regime_on"] = True
    return frame


def test_entry_and_exit_execute_at_next_open_with_post_cost_half_weight() -> None:
    frame = indicator_frame(12)
    frame.iloc[0, frame.columns.get_loc("ETH_z")] = -3.0
    frame.iloc[2, frame.columns.get_loc("ETH_z")] = 0.0
    result = simulate_window(
        frame,
        "C3AEthResidualReversion",
        "T",
        frame.index[0].isoformat(),
        (frame.index[-1] + pd.Timedelta(hours=4)).isoformat(),
        "1.0x",
        COST_RATES["1.0x"],
    )
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.entry_time == frame.index[1].isoformat()
    assert trade.exit_time == frame.index[3].isoformat()
    post_cost_equity = 1000.0 - trade.entry_cost
    assert trade.entry_notional == pytest.approx(0.5 * post_cost_equity)
    assert trade.held_bars == 2


def test_time_exit_occurs_after_exactly_18_completed_held_bars() -> None:
    frame = indicator_frame(24)
    frame.iloc[0, frame.columns.get_loc("ETH_z")] = -3.0
    result = simulate_window(
        frame,
        "C3AEthResidualReversion",
        "T",
        frame.index[0].isoformat(),
        (frame.index[-1] + pd.Timedelta(hours=4)).isoformat(),
        "1.0x",
        COST_RATES["1.0x"],
    )
    assert result.trades[0].entry_time == frame.index[1].isoformat()
    assert result.trades[0].exit_time == frame.index[19].isoformat()
    assert result.trades[0].held_bars == 18
    assert result.trades[0].reason == "time_exit"


def test_six_bar_cooldown_allows_signal_on_sixth_close_for_next_open() -> None:
    frame = indicator_frame(16)
    frame.iloc[0, frame.columns.get_loc("ETH_z")] = -3.0
    frame.iloc[2, frame.columns.get_loc("ETH_z")] = 0.0
    for position in range(3, 9):
        frame.iloc[position, frame.columns.get_loc("ETH_z")] = -3.0
    frame.iloc[10, frame.columns.get_loc("ETH_z")] = 0.0
    result = simulate_window(
        frame,
        "C3AEthResidualReversion",
        "T",
        frame.index[0].isoformat(),
        (frame.index[-1] + pd.Timedelta(hours=4)).isoformat(),
        "1.0x",
        COST_RATES["1.0x"],
    )
    assert len(result.trades) >= 2
    assert result.trades[0].exit_time == frame.index[3].isoformat()
    assert result.trades[1].entry_time == frame.index[9].isoformat()


def test_strongest_laggard_tie_breaks_to_eth() -> None:
    frame = indicator_frame(8)
    frame.iloc[0, frame.columns.get_loc("ETH_z")] = -3.0
    frame.iloc[0, frame.columns.get_loc("SOL_z")] = -3.0
    frame.iloc[2, frame.columns.get_loc("ETH_z")] = 0.0
    result = simulate_window(
        frame,
        "C3AStrongestLaggardResidualReversion",
        "T",
        frame.index[0].isoformat(),
        (frame.index[-1] + pd.Timedelta(hours=4)).isoformat(),
        "1.0x",
        COST_RATES["1.0x"],
    )
    assert result.trades[0].asset == "ETH"


def test_higher_costs_are_monotonic_for_identical_trades() -> None:
    frame = indicator_frame(12)
    frame.iloc[0, frame.columns.get_loc("ETH_z")] = -3.0
    frame.iloc[2, frame.columns.get_loc("ETH_z")] = 0.0
    results = [
        simulate_window(
            frame,
            "C3AEthResidualReversion",
            "T",
            frame.index[0].isoformat(),
            (frame.index[-1] + pd.Timedelta(hours=4)).isoformat(),
            label,
            rate,
        )
        for label, rate in COST_RATES.items()
    ]
    assert [result.final_equity for result in results] == sorted(
        [result.final_equity for result in results], reverse=True
    )


def synthetic_rows() -> dict[str, list[dict[str, object]]]:
    index = pd.date_range(
        "2023-09-01T00:00:00Z",
        "2024-09-30T20:00:00Z",
        freq="4h",
    )
    positions = np.arange(len(index))
    btc_return = 0.0002 + 0.002 * np.sin(positions / 17)
    eth_return = 1.1 * btc_return + 0.003 * np.sin(positions / 7)
    sol_return = 1.3 * btc_return + 0.004 * np.cos(positions / 9)
    for values, starts in (
        (eth_return, (800, 1200, 1600, 2000)),
        (sol_return, (900, 1300, 1700, 2100)),
    ):
        for start in starts:
            values[start : start + 6] -= 0.02
            values[start + 6 : start + 12] += 0.015

    def rows(close: np.ndarray) -> list[dict[str, object]]:
        opened = np.concatenate(([close[0]], close[:-1]))
        return [
            {"date": timestamp, "open": float(open_price), "close": float(close_price)}
            for timestamp, open_price, close_price in zip(index, opened, close, strict=True)
        ]

    return {
        "BTC/USDT": rows(30000 * np.exp(np.cumsum(btc_return))),
        "ETH/USDT": rows(2000 * np.exp(np.cumsum(eth_return))),
        "SOL/USDT": rows(50 * np.exp(np.cumsum(sol_return))),
    }


def test_future_perturbation_cannot_change_earlier_indicators() -> None:
    frame = frame_from_rows(synthetic_rows())
    baseline = compute_indicators(frame)
    cutoff = 1000
    modified = frame.copy()
    modified.iloc[cutoff + 1 :, modified.columns.get_loc("ETH_close")] *= 4.0
    modified.iloc[cutoff + 1 :, modified.columns.get_loc("SOL_close")] *= 0.25
    perturbed = compute_indicators(modified)
    pd.testing.assert_series_equal(
        baseline.iloc[: cutoff + 1]["ETH_z"],
        perturbed.iloc[: cutoff + 1]["ETH_z"],
    )
    pd.testing.assert_series_equal(
        baseline.iloc[: cutoff + 1]["SOL_z"],
        perturbed.iloc[: cutoff + 1]["SOL_z"],
    )


def test_screen_emits_exact_frozen_row_counts_and_safety_decision() -> None:
    frame = frame_from_rows(synthetic_rows())
    cells, comparators, decision = run_screen(frame)
    assert len(cells) == 27
    assert len(comparators) == 36
    assert {cell.policy_id for cell in cells} == set(POLICY_IDS)
    assert decision["economic_result"] in {"SELECTED", "REJECTED"}
    assert decision["confirmation_opened"] is False
    assert decision["c3b_state"] == "CLOSED"
    assert decision["holdout_state"] == "HOLDOUT_CLOSED"
    assert decision["live"] == "FORBIDDEN"
