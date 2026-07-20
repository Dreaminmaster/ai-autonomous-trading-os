from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from atos.c5a_derivatives_crowding import (
    ABLATION_ID,
    CANDIDATE_ID,
    C5AError,
    SPOT_INSTRUMENTS,
    SWAP_INSTRUMENTS,
    build_calibration,
    expected_timestamps,
    one_way_distance,
    prepare_market,
    run_screen,
    signal_snapshot,
    simulate_policy_half,
    solve_post_cost,
    validate_config,
)

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config/c5a_derivatives_crowding_regime.json"


def config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def datasets() -> dict:
    timestamps = expected_timestamps()
    positions = np.arange(len(timestamps), dtype=float)
    spot = {}
    swap = {}
    mark = {}
    for offset, instrument in enumerate(SPOT_INSTRUMENTS):
        base = 100.0 + 50.0 * offset
        close = base * np.exp(
            0.00018 * (offset + 1) * positions
            + 0.018 * np.sin(positions / (23.0 + offset * 3.0) + offset)
        )
        open_price = np.r_[close[0], close[:-1]] * (
            1.0 + 0.0003 * np.sin(positions / 11.0 + offset)
        )
        high = np.maximum(open_price, close) * 1.003
        low = np.minimum(open_price, close) * 0.997
        spot_volume = (1_000_000.0 + 300_000.0 * offset) * (
            1.0 + 0.08 * np.cos(positions / 31.0 + offset)
        )
        spot[instrument] = [
            {
                "date": timestamp.isoformat(),
                "open": float(o),
                "high": float(h),
                "low": float(l),
                "close": float(c),
                "quote_volume": float(v),
            }
            for timestamp, o, h, l, c, v in zip(
                timestamps, open_price, high, low, close, spot_volume, strict=True
            )
        ]
        swap_instrument = SWAP_INSTRUMENTS[offset]
        basis = 0.0008 * np.sin(positions / 37.0 + offset) + 0.0003 * offset
        swap_volume = spot_volume * (
            0.7 + 0.15 * offset + 0.12 * np.sin(positions / 29.0 + offset)
        )
        swap[swap_instrument] = [
            {"date": timestamp.isoformat(), "quote_volume": float(v)}
            for timestamp, v in zip(timestamps, swap_volume, strict=True)
        ]
        mark[swap_instrument] = [
            {"date": timestamp.isoformat(), "close": float(c * (1.0 + b))}
            for timestamp, c, b in zip(timestamps, close, basis, strict=True)
        ]
    return {"spot": spot, "swap": swap, "mark": mark}


@lru_cache(maxsize=1)
def market():
    return prepare_market(datasets())


@lru_cache(maxsize=1)
def calibration():
    return build_calibration(market(), config())


def test_config_and_grid_are_frozen() -> None:
    payload = config()
    validate_config(payload)
    assert len(expected_timestamps()) == 2940
    assert len(calibration()["rows"]) == 117
    drifted = copy.deepcopy(payload)
    drifted["crowding_percentile_threshold"] = 0.81
    with pytest.raises(C5AError, match="configuration drift"):
        validate_config(drifted)


def test_signal_uses_completed_sunday_bar_and_one_candidate() -> None:
    payload = config()
    execution_index = market().timestamps.index(
        next(
            value
            for value in market().timestamps
            if value.isoformat() == "2025-07-07T00:00:00+00:00"
        )
    )
    candidate = signal_snapshot(
        market(), calibration(), execution_index=execution_index,
        policy_id=CANDIDATE_ID, config=payload,
    )
    ablation = signal_snapshot(
        market(), calibration(), execution_index=execution_index,
        policy_id=ABLATION_ID, config=payload,
    )
    assert candidate["signal_time"] == "2025-07-06T20:00:00+00:00"
    assert len(candidate["rows"]) == 3
    assert set(candidate["target_weights"]).issubset(SPOT_INSTRUMENTS)
    assert all(value <= 0.4 + 1e-12 for value in candidate["target_weights"].values())
    assert all(
        row_a["trend_28d"] == row_b["trend_28d"]
        and row_a["rv_28d"] == row_b["rv_28d"]
        for row_a, row_b in zip(candidate["rows"], ablation["rows"], strict=True)
    )


def test_post_cost_solver_and_no_trade_distance() -> None:
    result = solve_post_cost(
        1000.0,
        {spot: 0.0 for spot in SPOT_INSTRUMENTS},
        {"BTC-USDT": 0.4, "ETH-USDT": 0.4},
        0.0015,
    )
    assert abs(1000.0 - result["total_fee"] - result["equity_after"]) < 1e-9
    assert abs(result["cash"] - 0.2 * result["equity_after"]) < 1e-9
    distance = one_way_distance(
        {spot: 0.0 for spot in SPOT_INSTRUMENTS},
        1.0,
        {"BTC-USDT": 0.4, "ETH-USDT": 0.4},
        0.2,
    )
    assert distance == pytest.approx(0.8)


def test_half_reconciles_weeks_contributions_and_terminal_cash() -> None:
    payload = config()
    row = simulate_policy_half(
        market(), calibration(), policy_id=CANDIDATE_ID,
        window=payload["screen_windows"][0], cost_label="1.0x", config=payload,
    )
    assert len(row["weekly_returns"]) == 13
    assert len(row["equity_returns"]) == 546
    assert len(row["decisions"]) == 13
    assert abs(sum(row["asset_contributions"].values()) - (row["final_equity"] - 1000.0)) < 1e-9
    assert abs(sum(row["weekly_pnl"]) - (row["final_equity"] - 1000.0)) < 1e-9
    assert row["events"][-1]["kind"] in {"TERMINAL_LIQUIDATION", "SCHEDULED_REBALANCE"}
    if row["events"][-1]["kind"] == "TERMINAL_LIQUIDATION":
        assert all(value == 0.0 for value in row["events"][-1]["quantities_after"].values())


def test_full_screen_has_frozen_cells_psr_and_closed_safety() -> None:
    result = run_screen(datasets(), config())
    assert len(result["policy_rows"]) == 12
    assert len(result["comparator_rows"]) == 18
    assert len(result["policy_aggregates"]) == 6
    assert len(result["comparator_aggregates"]) == 9
    expected = next(
        row for row in result["policy_aggregates"]
        if row["policy_id"] == CANDIDATE_ID and row["cost_label"] == "1.0x"
    )
    assert len(expected["weekly_returns"]) == 26
    assert 0.0 <= expected["weekly_psr"] <= 1.0
    assert result["decision"]["economic_result"] in {"SELECTED", "REJECTED"}
    assert result["decision"]["confirmation_opened"] is False
    assert result["decision"]["holdout_state"] == "HOLDOUT_CLOSED"
    assert result["decision"]["live"] == "FORBIDDEN"
