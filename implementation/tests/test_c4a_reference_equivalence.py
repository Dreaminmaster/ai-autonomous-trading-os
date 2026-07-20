from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from atos.c4a_cross_sectional_runtime import run_screen
from scripts.c4a_reference_recompute import CANDIDATE_PAIRS, reference_run_screen

CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "config/c4a_large_liquid_cross_sectional_momentum.json"
)


def _config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


def _candles() -> dict[str, list[dict[str, float | str]]]:
    index = pd.date_range("2023-09-01T00:00:00Z", "2024-09-30T20:00:00Z", freq="4h")
    output: dict[str, list[dict[str, float | str]]] = {}
    positions = np.arange(len(index), dtype=float)
    for offset, pair in enumerate(CANDIDATE_PAIRS):
        close = (40 + 8 * offset) * np.exp(
            0.000035 * (offset - 5) * positions
            + 0.018 * np.sin(positions / (17 + offset / 3) + offset)
            + 0.006 * np.cos(positions / 7 + offset / 2)
        )
        open_price = np.r_[close[0], close[:-1]] * (
            1 + 0.00035 * np.sin(positions / 9 + offset)
        )
        high = np.maximum(open_price, close) * (1.002 + 0.0001 * (offset % 3))
        low = np.minimum(open_price, close) * (0.998 - 0.0001 * (offset % 2))
        volume = 800 * (13 - offset) * (
            1 + 0.025 * np.cos(positions / 19 + offset)
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


def _compare(left: Any, right: Any, path: str = "root") -> None:
    if isinstance(left, bool) or isinstance(right, bool):
        assert left is right, path
        return
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        assert math.isclose(float(left), float(right), rel_tol=1e-10, abs_tol=1e-10), (
            path,
            left,
            right,
        )
        return
    if isinstance(left, dict) and isinstance(right, dict):
        assert set(left) == set(right), (path, set(left) ^ set(right))
        for key in left:
            _compare(left[key], right[key], f"{path}.{key}")
        return
    if isinstance(left, list) and isinstance(right, list):
        assert len(left) == len(right), (path, len(left), len(right))
        for index, (left_item, right_item) in enumerate(zip(left, right, strict=True)):
            _compare(left_item, right_item, f"{path}[{index}]")
        return
    assert left == right, (path, left, right)


def _production_policy_core(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "policy_id": row["policy_id"],
        "window_id": row["window_id"],
        "cost_label": row["cost_label"],
        "starting_equity": row["starting_equity"],
        "final_equity": row["final_equity"],
        "net_return": row["net_return"],
        "maximum_drawdown": row["maximum_drawdown"],
        "economic_bars": row["economic_bars"],
        "exposed_bars": row["exposed_bars"],
        "exposure_ratio": row["exposure_ratio"],
        "scheduled_decision_count": row["scheduled_decision_count"],
        "scheduled_active_rebalance_count": row["scheduled_active_rebalance_count"],
        "traded_rebalance_count": row["traded_rebalance_count"],
        "closed_asset_lot_count": row["closed_asset_lot_count"],
        "turnover_contributions": row["turnover_contributions"],
        "annualized_one_way_turnover": row["annualized_one_way_turnover"],
        "equity_returns": row["equity_returns"],
        "asset_contributions": row["asset_contributions"],
        "full_week_returns": row["full_week_returns"],
        "full_week_pnl": row["full_week_pnl"],
        "terminal_stub_net_pnl": row["terminal_stub_net_pnl"],
        "decisions": row["signals"],
    }


def _production_comparator_core(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "comparator_id": row["comparator_id"],
        "window_id": row["window_id"],
        "cost_label": row["cost_label"],
        "final_equity": row["final_equity"],
        "net_return": row["net_return"],
        "maximum_drawdown": row["maximum_drawdown"],
        "equity_returns": row["equity_returns"],
    }


def _aggregate_core(row: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "policy_id",
        "cost_label",
        "window_returns",
        "minimum_window_net_return",
        "median_window_net_return",
        "positive_windows",
        "aggregate_net_return",
        "aggregate_sharpe",
        "maximum_window_drawdown",
        "scheduled_active_rebalance_count",
        "minimum_window_active_rebalances",
        "closed_asset_lot_count",
        "exposure_ratio",
        "annualized_one_way_turnover",
        "asset_contributions",
        "positive_asset_count",
        "maximum_asset_positive_pnl_share",
        "maximum_window_positive_pnl_share",
        "maximum_week_positive_pnl_share",
        "maximum_top_three_week_positive_pnl_share",
        "full_week_returns",
        "full_week_pnl",
        "window_net_pnl",
        "week_and_stub_net_pnl",
    )
    result = {key: row[key] for key in keys}
    for key in (
        "weekly_mean",
        "weekly_std",
        "sr_weekly_raw",
        "sr_weekly_annualized",
        "skewness",
        "ordinary_kurtosis",
        "dsr_trial_policy_order",
        "dsr_trial_raw_sharpes",
        "sigma_sr_raw",
        "sr_star_raw",
        "dsr_radicand",
        "dsr_z_score",
        "within_stage_dsr_probability",
    ):
        if key in row:
            result[key] = row[key]
    return result


def _decision_core(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "economic_result": row["economic_result"],
        "selected_policy": row["selected_policy"],
        "eligible_ranking": row["eligible_ranking"],
        "policy_decisions": {
            policy: {
                "policy_id": item["policy_id"],
                "eligible": item["eligible"],
                "rejection_reasons": item["rejection_reasons"],
            }
            for policy, item in row["policy_decisions"].items()
        },
        "confirmation_opened": row["confirmation_opened"],
        "holdout_state": row["holdout_state"],
        "live": row["live"],
    }


def test_plain_array_reference_matches_all_frozen_cells_and_decision() -> None:
    candles = _candles()
    config = _config()
    production = run_screen(candles, config)
    reference = reference_run_screen(candles, config)

    _compare(production["universe"], reference["universe"], "universe")

    production_rows = {
        (row["policy_id"], row["window_id"], row["cost_label"]): _production_policy_core(row)
        for row in production["policy_rows"]
    }
    reference_rows = {
        (row["policy_id"], row["window_id"], row["cost_label"]): row
        for row in reference["policy_rows"]
    }
    assert len(production_rows) == len(reference_rows) == 27
    for key in production_rows:
        _compare(production_rows[key], reference_rows[key], f"policy_rows.{key}")

    production_comparators = {
        (row["comparator_id"], row["window_id"], row["cost_label"]): _production_comparator_core(row)
        for row in production["comparator_rows"]
    }
    reference_comparators = {
        (row["comparator_id"], row["window_id"], row["cost_label"]): row
        for row in reference["comparator_rows"]
    }
    assert len(production_comparators) == len(reference_comparators) == 36
    for key in production_comparators:
        _compare(production_comparators[key], reference_comparators[key], f"comparators.{key}")

    production_aggregates = {
        (row["policy_id"], row["cost_label"]): _aggregate_core(row)
        for row in production["policy_aggregates"]
    }
    reference_aggregates = {
        (row["policy_id"], row["cost_label"]): row
        for row in reference["policy_aggregates"]
    }
    assert len(production_aggregates) == len(reference_aggregates) == 9
    for key in production_aggregates:
        _compare(production_aggregates[key], reference_aggregates[key], f"aggregates.{key}")

    _compare(
        production["comparator_aggregates"],
        reference["comparator_aggregates"],
        "comparator_aggregates",
    )
    _compare(_decision_core(production["decision"]), reference["decision"], "decision")
