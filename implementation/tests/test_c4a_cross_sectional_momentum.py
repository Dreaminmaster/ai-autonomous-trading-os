from __future__ import annotations

import copy
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from atos.c4a_cross_sectional_runtime import (
    CANDIDATE_PAIRS,
    C4AError,
    POLICIES,
    prepare_market,
    run_screen,
    select_universe,
    signal_snapshot,
    simulate_window,
    solve_post_cost_equity,
    validate_config,
)

CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "config/c4a_large_liquid_cross_sectional_momentum.json"
)


def load_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def synthetic_candles() -> dict[str, list[dict[str, float | str]]]:
    index = pd.date_range(
        "2023-09-01T00:00:00Z",
        "2024-09-30T20:00:00Z",
        freq="4h",
    )
    output: dict[str, list[dict[str, float | str]]] = {}
    for offset, pair in enumerate(CANDIDATE_PAIRS):
        positions = np.arange(len(index))
        close = (50 + 10 * offset) * np.exp(
            0.00003 * (offset - 5) * positions
            + 0.02 * np.sin(positions / 20 + offset)
        )
        open_price = np.r_[close[0], close[:-1]] * (
            1 + 0.0002 * np.sin(positions / 7 + offset)
        )
        high = np.maximum(open_price, close) * 1.002
        low = np.minimum(open_price, close) * 0.998
        volume = np.full(len(index), 1000 * (13 - offset), dtype=float) * (
            1 + 0.01 * np.cos(positions / 13 + offset)
        )
        output[pair] = [
            {
                "date": timestamp.isoformat(),
                "open": float(open_value),
                "high": float(high_value),
                "low": float(low_value),
                "close": float(close_value),
                "volume": float(volume_value),
            }
            for timestamp, open_value, high_value, low_value, close_value, volume_value
            in zip(index, open_price, high, low, close, volume, strict=True)
        ]
    return output


@lru_cache(maxsize=1)
def synthetic_market() -> pd.DataFrame:
    return prepare_market(synthetic_candles())


def test_config_is_exact_and_fail_closed() -> None:
    config = load_config()
    validate_config(config)
    drifted = copy.deepcopy(config)
    drifted["gate"]["minimum_positive_windows"] = 1
    with pytest.raises(C4AError, match="gate drift"):
        validate_config(drifted)
    assert config["confirmation_opened"] is False
    assert config["holdout_state"] == "HOLDOUT_CLOSED"
    assert config["live"] == "FORBIDDEN"


def test_post_cost_solver_preserves_identity_and_target_cash() -> None:
    result = solve_post_cost_equity(
        equity_before=1000,
        current_values={"A": 0, "B": 0},
        target_weights={"A": 0.45, "B": 0.45},
        fee_rate=0.0015,
    )
    assert abs(1000 - result["total_fee"] - result["equity_after"]) < 1e-9
    assert abs(result["cash"] - 0.1 * result["equity_after"]) < 1e-9


def test_formation_universe_and_first_signal_are_deterministic() -> None:
    config = load_config()
    market = synthetic_market()
    universe = select_universe(market, config)
    assert len(universe["selected_pairs"]) == 8
    assert universe["formation_rows"] == 732
    snapshot = signal_snapshot(
        market,
        execution_time=pd.Timestamp("2024-01-01T00:00:00Z"),
        selected_pairs=universe["selected_pairs"],
        policy=POLICIES[0],
        config=config,
    )
    assert snapshot["signal_time"] == "2023-12-31T20:00:00+00:00"
    assert len(snapshot["rows"]) == 8


def test_independent_window_reconciles_costs_lots_and_full_weeks() -> None:
    config = load_config()
    market = synthetic_market()
    selected = select_universe(market, config)["selected_pairs"]
    row = simulate_window(
        market,
        selected_pairs=selected,
        policy=POLICIES[0],
        window=config["screen_windows"][0],
        cost_label="1.0x",
        config=config,
    )
    assert len(row["full_week_returns"]) == 13
    assert len(row["equity_returns"]) == 546
    assert abs(
        sum(row["asset_contributions"].values())
        - (row["final_equity"] - 1000)
    ) < 1e-8
    assert row["marks"][-1]["post_close_quantities"] == {
        pair: 0.0 for pair in selected
    }
    assert abs(
        sum(row["full_week_pnl"])
        + row["terminal_stub_net_pnl"]
        - (row["final_equity"] - 1000)
    ) < 1e-9
    assert {
        "pre_trade_open_equity",
        "monday_rebalance_fee",
        "post_trade_equity",
    }.issubset(row["full_weeks"][0])
    assert all(lot["exit_time"] for lot in row["closed_lots"])


def test_s3_forces_cash_and_keeps_stub_out_of_dsr_sample() -> None:
    config = load_config()
    market = synthetic_market()
    selected = select_universe(market, config)["selected_pairs"]
    row = simulate_window(
        market,
        selected_pairs=selected,
        policy=POLICIES[1],
        window=config["screen_windows"][2],
        cost_label="1.0x",
        config=config,
    )
    assert len(row["full_week_returns"]) == 13
    assert row["scheduled_decision_count"] == 14
    assert row["terminal_stub"] is not None
    assert row["terminal_stub"]["execution_time"] == "2024-09-30T00:00:00+00:00"
    assert row["marks"][-1]["bar_exposed"] is False


def test_full_screen_has_frozen_rows_and_within_stage_dsr() -> None:
    result = run_screen(synthetic_candles(), load_config())
    assert len(result["policy_rows"]) == 27
    assert len(result["comparator_rows"]) == 36
    assert result["decision"]["economic_result"] in {"SELECTED", "REJECTED"}
    expected = [
        row for row in result["policy_aggregates"] if row["cost_label"] == "1.0x"
    ]
    assert len(expected) == 3
    for row in expected:
        assert len(row["full_week_returns"]) == 39
        assert 0 <= row["within_stage_dsr_probability"] <= 1
        assert row["dsr_trial_policy_order"] == list(POLICIES)
        assert abs(row["window_net_pnl"] - row["week_and_stub_net_pnl"]) < 1e-9
