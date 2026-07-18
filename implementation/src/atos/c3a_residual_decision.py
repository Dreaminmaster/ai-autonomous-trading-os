from __future__ import annotations

from statistics import median
from typing import Any, Sequence

import numpy as np
import pandas as pd

from .c3a_residual_common import (
    ANNUAL_BARS, COST_RATES, POLICY_IDS, STARTING_EQUITY, WINDOWS, CellResult, C3AError,
    _positive_share, _profit_factor, _sharpe, _top_positive_share,
)
from .c3a_residual_indicators import compute_indicators
from .c3a_residual_simulation import comparator_cell, simulate_window


def aggregate_policy(cells: Sequence[CellResult], policy_id: str) -> dict[str, Any]:
    expected = sorted(
        (cell for cell in cells if cell.policy_id == policy_id and cell.cost_label == "1.0x"),
        key=lambda cell: cell.window_id,
    )
    stressed = sorted(
        (cell for cell in cells if cell.policy_id == policy_id and cell.cost_label == "1.5x"),
        key=lambda cell: cell.window_id,
    )
    if len(expected) != 3 or len(stressed) != 3:
        raise C3AError(f"incomplete policy cells for {policy_id}")
    expected_returns = [cell.net_return for cell in expected]
    aggregate_return = float(np.prod([1.0 + value for value in expected_returns]) - 1.0)
    stressed_return = float(np.prod([1.0 + cell.net_return for cell in stressed]) - 1.0)
    all_trades = [trade for cell in expected for trade in cell.trades]
    all_returns = [value for cell in expected for value in cell.returns]
    all_turnover = [value for cell in expected for value in cell.turnover_contributions]
    total_bars = sum(cell.bars for cell in expected)
    asset_net = {
        asset: sum(trade.net_pnl for trade in all_trades if trade.asset == asset)
        for asset in ("ETH", "SOL")
    }
    positive_asset_share = _positive_share(asset_net.values())
    aggregate_profit_factor = _profit_factor(all_trades)
    aggregate_sharpe = _sharpe(all_returns)
    positive_windows = sum(value > 0 for value in expected_returns)
    window_share = _positive_share([cell.final_equity - STARTING_EQUITY for cell in expected])
    single_trade_share = _top_positive_share((trade.net_pnl for trade in all_trades), 1)
    top_three_share = _top_positive_share((trade.net_pnl for trade in all_trades), 3)
    annualized_turnover = sum(all_turnover) * ANNUAL_BARS / total_bars
    exposure = sum(cell.exposure * cell.bars for cell in expected) / total_bars
    profit_factor_pass = (
        aggregate_profit_factor == "Infinity"
        or (
            isinstance(aggregate_profit_factor, (int, float))
            and float(aggregate_profit_factor) >= 1.15
        )
    )
    gates = {
        "minimum_positive_windows": positive_windows >= 2,
        "positive_median_window_return": median(expected_returns) > 0,
        "positive_aggregate_expected_return": aggregate_return > 0,
        "nonnegative_aggregate_1_5x_return": stressed_return >= 0,
        "minimum_aggregate_sharpe": aggregate_sharpe is not None and aggregate_sharpe >= 0.75,
        "minimum_aggregate_profit_factor": profit_factor_pass,
        "maximum_window_drawdown": max(cell.max_drawdown for cell in expected) <= 0.12,
        "minimum_closed_trades": len(all_trades) >= 18,
        "minimum_closed_trades_per_window": min(cell.closed_trades for cell in expected) >= 4,
        "maximum_exposure": exposure <= 0.45,
        "maximum_annualized_one_way_turnover": annualized_turnover <= 36.0,
        "maximum_window_positive_pnl_share": window_share <= 0.70,
        "maximum_single_trade_positive_pnl_share": single_trade_share <= 0.25,
        "maximum_top_three_positive_pnl_share": top_three_share <= 0.55,
    }
    if policy_id == "C3AStrongestLaggardResidualReversion":
        gates.update(
            {
                "positive_eth_contribution": asset_net["ETH"] > 0,
                "positive_sol_contribution": asset_net["SOL"] > 0,
                "maximum_asset_positive_pnl_share": positive_asset_share <= 0.75,
            }
        )
    return {
        "policy_id": policy_id,
        "eligible": all(gates.values()),
        "gates": gates,
        "positive_windows": positive_windows,
        "median_window_net_return": median(expected_returns),
        "minimum_window_net_return": min(expected_returns),
        "aggregate_expected_net_return": aggregate_return,
        "aggregate_1_5x_net_return": stressed_return,
        "aggregate_sharpe": aggregate_sharpe,
        "aggregate_profit_factor": aggregate_profit_factor,
        "maximum_window_drawdown": max(cell.max_drawdown for cell in expected),
        "closed_trades": len(all_trades),
        "minimum_closed_trades_per_window": min(cell.closed_trades for cell in expected),
        "exposure": exposure,
        "annualized_one_way_turnover": annualized_turnover,
        "maximum_window_positive_pnl_share": window_share,
        "maximum_single_trade_positive_pnl_share": single_trade_share,
        "maximum_top_three_positive_pnl_share": top_three_share,
        "asset_net_contribution": asset_net,
        "maximum_asset_positive_pnl_share": positive_asset_share,
        "window_returns": {cell.window_id: cell.net_return for cell in expected},
    }


def decide(cells: Sequence[CellResult]) -> dict[str, Any]:
    aggregates = [aggregate_policy(cells, policy_id) for policy_id in POLICY_IDS]
    eligible = [item for item in aggregates if item["eligible"]]
    eligible.sort(
        key=lambda item: (
            -item["minimum_window_net_return"],
            -item["median_window_net_return"],
            -item["aggregate_1_5x_net_return"],
            item["maximum_window_drawdown"],
            item["annualized_one_way_turnover"],
            item["policy_id"],
        )
    )
    selected = eligible[0]["policy_id"] if eligible else None
    return {
        "stage": "C3A",
        "status": "PASS",
        "economic_result": "SELECTED" if selected else "REJECTED",
        "selected_policy": selected,
        "eligible_policy_ids": [item["policy_id"] for item in eligible],
        "policy_aggregates": aggregates,
        "confirmation_opened": False,
        "c3b_state": "CLOSED",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def run_screen(frame: pd.DataFrame) -> tuple[list[CellResult], list[dict[str, Any]], dict[str, Any]]:
    indicators = compute_indicators(frame)
    cells: list[CellResult] = []
    for policy_id in POLICY_IDS:
        for window_id, start, end in WINDOWS:
            for cost_label, cost_rate in COST_RATES.items():
                cells.append(
                    simulate_window(
                        indicators,
                        policy_id,
                        window_id,
                        start,
                        end,
                        cost_label,
                        cost_rate,
                    )
                )
    comparators: list[dict[str, Any]] = []
    for comparator_id in ("Cash", "BTCBuyAndHold", "ETHBuyAndHold", "SOLBuyAndHold"):
        for window_id, start, end in WINDOWS:
            for cost_label, cost_rate in COST_RATES.items():
                comparators.append(
                    comparator_cell(
                        frame,
                        comparator_id,
                        window_id,
                        start,
                        end,
                        cost_label,
                        cost_rate,
                    )
                )
    if len(cells) != 27 or len(comparators) != 36:
        raise C3AError("C3A row-count contract violated")
    decision = decide(cells)
    return cells, comparators, decision
