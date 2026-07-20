"""C5A metrics, comparators, gates, and screen orchestration."""
from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

import numpy as np
from scipy.stats import kurtosis, norm, skew

from .c5a_contract import (
    ABLATION_ID,
    ANNUAL_4H_BARS,
    CANDIDATE_ID,
    COMPARATORS,
    COST_LABELS,
    SECONDS_PER_YEAR,
    SPOT_INSTRUMENTS,
    C5AError,
    C5AMarket,
    _timestamp,
    build_calibration,
    prepare_market,
    validate_config,
)
from .c5a_policy import solve_post_cost
from .c5a_simulation import _max_drawdown, simulate_policy_half


def _sharpe_4h(values: Sequence[float]) -> float | None:
    array = np.asarray(values, dtype=float)
    if len(array) < 2 or not np.isfinite(array).all():
        return None
    mean_value = float(np.mean(array))
    deviation = float(np.std(array, ddof=1))
    if deviation == 0:
        if mean_value == 0:
            return 0.0
        return None
    return mean_value / deviation * math.sqrt(ANNUAL_4H_BARS)


def _positive_share(values: Sequence[float], top: int = 1) -> float | None:
    positive = sorted((float(value) for value in values if float(value) > 0), reverse=True)
    total = sum(positive)
    return None if total <= 0 else sum(positive[:top]) / total


def _weekly_psr(values: Sequence[float]) -> dict[str, float]:
    array = np.asarray(values, dtype=float)
    if len(array) != 26 or not np.isfinite(array).all():
        raise C5AError("C5A PSR requires exactly 26 finite weekly returns")
    mean_value = float(np.mean(array))
    deviation = float(np.std(array, ddof=1))
    if deviation == 0:
        if mean_value != 0:
            raise C5AError("nonzero weekly mean with zero variance")
        return {
            "weekly_mean": 0.0,
            "weekly_std": 0.0,
            "sr_weekly_raw": 0.0,
            "sr_weekly_annualized": 0.0,
            "skewness": 0.0,
            "ordinary_kurtosis": 3.0,
            "psr_radicand": 1.0,
            "psr_z_score": 0.0,
            "weekly_psr": 0.0,
        }
    raw = mean_value / deviation
    skewness = float(skew(array, bias=False))
    ordinary = float(kurtosis(array, fisher=False, bias=False))
    radicand = 1.0 - skewness * raw + ((ordinary - 1.0) / 4.0) * raw * raw
    if not math.isfinite(radicand) or radicand <= 0:
        raise C5AError("invalid C5A PSR radicand")
    z_score = raw * math.sqrt(25) / math.sqrt(radicand)
    probability = float(norm.cdf(z_score))
    return {
        "weekly_mean": mean_value,
        "weekly_std": deviation,
        "sr_weekly_raw": raw,
        "sr_weekly_annualized": raw * math.sqrt(52),
        "skewness": skewness,
        "ordinary_kurtosis": ordinary,
        "psr_radicand": radicand,
        "psr_z_score": z_score,
        "weekly_psr": probability,
    }


def aggregate_policy(
    rows: Sequence[Mapping[str, Any]],
    *,
    policy_id: str,
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    selected = [
        row for row in rows
        if row["policy_id"] == policy_id and row["cost_label"] == cost_label
    ]
    by_window = {str(row["window_id"]): row for row in selected}
    ordered = [by_window[str(window["id"])] for window in config["screen_windows"]]
    if len(ordered) != 2:
        raise C5AError("C5A aggregate requires two half windows")
    half_returns = {row["window_id"]: float(row["net_return"]) for row in ordered}
    half_pnl = [float(row["final_equity"]) - float(config["starting_equity"]) for row in ordered]
    returns_4h = [float(value) for row in ordered for value in row["equity_returns"]]
    weekly_returns = [float(value) for row in ordered for value in row["weekly_returns"]]
    weekly_pnl = [float(value) for row in ordered for value in row["weekly_pnl"]]
    contributions = {
        spot: sum(float(row["asset_contributions"][spot]) for row in ordered)
        for spot in SPOT_INSTRUMENTS
    }
    duration_years = sum(
        (_timestamp(window["end"]) - _timestamp(window["start"])).total_seconds()
        for window in config["screen_windows"]
    ) / SECONDS_PER_YEAR
    result = {
        "schema_version": 1,
        "stage": "C5A",
        "status": "PASS",
        "policy_id": policy_id,
        "cost_label": cost_label,
        "half_returns": half_returns,
        "aggregate_net_return": math.prod(1.0 + value for value in half_returns.values()) - 1.0,
        "aggregate_sharpe_4h": _sharpe_4h(returns_4h),
        "maximum_half_drawdown": max(float(row["maximum_drawdown"]) for row in ordered),
        "annualized_one_way_turnover": sum(
            sum(float(value) for value in row["turnover_contributions"])
            for row in ordered
        ) / duration_years,
        "exposure_ratio": sum(int(row["exposed_bars"]) for row in ordered)
        / sum(int(row["economic_bars"]) for row in ordered),
        "active_rebalance_count": sum(int(row["active_rebalance_count"]) for row in ordered),
        "minimum_half_active_rebalances": min(
            int(row["active_rebalance_count"]) for row in ordered
        ),
        "asset_contributions": contributions,
        "positive_asset_count": sum(value > 0 for value in contributions.values()),
        "maximum_positive_half_pnl_share": _positive_share(half_pnl),
        "maximum_positive_asset_pnl_share": _positive_share(list(contributions.values())),
        "maximum_positive_week_pnl_share": _positive_share(weekly_pnl),
        "maximum_top_three_positive_week_pnl_share": _positive_share(weekly_pnl, top=3),
        "weekly_returns": weekly_returns,
        "weekly_pnl": weekly_pnl,
        "half_pnl": half_pnl,
        "window_rows": [dict(row) for row in ordered],
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    result.update(_weekly_psr(weekly_returns))
    if abs(sum(contributions.values()) - sum(half_pnl)) > 1e-9:
        raise C5AError("aggregate C5A contribution reconciliation failure")
    return result


def simulate_comparator_half(
    market: C5AMarket,
    *,
    comparator_id: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    if comparator_id not in COMPARATORS:
        raise C5AError("unknown C5A comparator")
    start, end = _timestamp(window["start"]), _timestamp(window["end"])
    indices = [index for index, stamp in enumerate(market.timestamps) if start <= stamp < end]
    if len(indices) != 546:
        raise C5AError("comparator half-window count mismatch")
    starting = float(config["starting_equity"])
    if comparator_id == "cash":
        return {
            "comparator_id": comparator_id,
            "window_id": str(window["id"]),
            "cost_label": cost_label,
            "starting_equity": starting,
            "final_equity": starting,
            "net_return": 0.0,
            "maximum_drawdown": 0.0,
            "equity_returns": [0.0] * len(indices),
            "weekly_returns": [0.0] * 13,
            "weekly_pnl": [0.0] * 13,
            "status": "PASS",
        }
    instruments = (
        ("BTC-USDT",)
        if comparator_id == "btc_buy_hold"
        else SPOT_INSTRUMENTS
    )
    target_weights = {spot: 1.0 / len(instruments) for spot in instruments}
    first_index = indices[0]
    first_prices = {spot: float(market.spot_open[spot][first_index]) for spot in SPOT_INSTRUMENTS}
    solved = solve_post_cost(
        starting,
        {spot: 0.0 for spot in SPOT_INSTRUMENTS},
        target_weights,
        float(config["cost_rates"][cost_label]),
    )
    quantities = {
        spot: solved["target_values"][spot] / first_prices[spot]
        if solved["target_values"][spot] > 0
        else 0.0
        for spot in SPOT_INSTRUMENTS
    }
    cash = float(solved["cash"])
    equity_curve = [starting]
    weekly_returns: list[float] = []
    weekly_pnl: list[float] = []
    week_start = starting
    for local_index, index in enumerate(indices):
        close_prices = {spot: float(market.spot_close[spot][index]) for spot in SPOT_INSTRUMENTS}
        equity = cash + sum(quantities[spot] * close_prices[spot] for spot in SPOT_INSTRUMENTS)
        if local_index == len(indices) - 1:
            current = {spot: quantities[spot] * close_prices[spot] for spot in SPOT_INSTRUMENTS}
            out = solve_post_cost(
                equity, current, {}, float(config["cost_rates"][cost_label])
            )
            equity = float(out["equity_after"])
        equity_curve.append(equity)
        timestamp = market.timestamps[index]
        if timestamp.weekday() == 6 and timestamp.hour == 20:
            weekly_pnl.append(equity - week_start)
            weekly_returns.append(equity / week_start - 1.0)
            week_start = equity
    if len(weekly_returns) != 13:
        raise C5AError("comparator weekly count mismatch")
    return {
        "comparator_id": comparator_id,
        "window_id": str(window["id"]),
        "cost_label": cost_label,
        "starting_equity": starting,
        "final_equity": equity_curve[-1],
        "net_return": equity_curve[-1] / starting - 1.0,
        "maximum_drawdown": _max_drawdown(equity_curve),
        "equity_returns": [
            equity_curve[index] / equity_curve[index - 1] - 1.0
            for index in range(1, len(equity_curve))
        ],
        "weekly_returns": weekly_returns,
        "weekly_pnl": weekly_pnl,
        "status": "PASS",
    }


def aggregate_comparator(
    rows: Sequence[Mapping[str, Any]],
    *,
    comparator_id: str,
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    selected = [
        row for row in rows
        if row["comparator_id"] == comparator_id and row["cost_label"] == cost_label
    ]
    by_window = {str(row["window_id"]): row for row in selected}
    ordered = [by_window[str(window["id"])] for window in config["screen_windows"]]
    returns = {row["window_id"]: float(row["net_return"]) for row in ordered}
    return {
        "comparator_id": comparator_id,
        "cost_label": cost_label,
        "half_returns": returns,
        "aggregate_net_return": math.prod(1.0 + value for value in returns.values()) - 1.0,
        "maximum_half_drawdown": max(float(row["maximum_drawdown"]) for row in ordered),
        "status": "PASS",
    }


def decide(
    aggregates: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    by_key = {
        (str(row["policy_id"]), str(row["cost_label"])): row for row in aggregates
    }
    expected = by_key[(CANDIDATE_ID, "1.0x")]
    stress = by_key[(CANDIDATE_ID, "1.5x")]
    ablation = by_key[(ABLATION_ID, "1.0x")]
    gate = config["gate"]
    reasons: list[str] = []
    half_returns = expected["half_returns"]
    checks = [
        (any(float(value) <= float(gate["minimum_half_return_exclusive"]) for value in half_returns.values()), "half_returns"),
        (float(expected["aggregate_net_return"]) <= float(gate["minimum_aggregate_expected_return_exclusive"]), "aggregate_expected_return"),
        (float(stress["aggregate_net_return"]) < float(gate["minimum_aggregate_1_5x_return"]), "aggregate_1_5x_return"),
        (expected["aggregate_sharpe_4h"] is None or float(expected["aggregate_sharpe_4h"]) < float(gate["minimum_aggregate_sharpe"]), "aggregate_sharpe"),
        (float(expected["weekly_psr"]) < float(gate["minimum_weekly_psr"]), "weekly_psr"),
        (float(expected["maximum_half_drawdown"]) > float(gate["maximum_half_drawdown"]), "maximum_half_drawdown"),
        (float(expected["annualized_one_way_turnover"]) > float(gate["maximum_annualized_one_way_turnover"]), "turnover"),
        (float(expected["exposure_ratio"]) > float(gate["maximum_exposure_ratio"]), "exposure"),
        (int(expected["active_rebalance_count"]) < int(gate["minimum_active_rebalances"]), "active_rebalances"),
        (int(expected["minimum_half_active_rebalances"]) < int(gate["minimum_active_rebalances_per_half"]), "minimum_half_active_rebalances"),
        (int(expected["positive_asset_count"]) < int(gate["minimum_positive_assets"]), "positive_assets"),
    ]
    reasons.extend(reason for failed, reason in checks if failed)
    for key, threshold, reason in (
        ("maximum_positive_half_pnl_share", "maximum_positive_half_pnl_share", "half_concentration"),
        ("maximum_positive_asset_pnl_share", "maximum_positive_asset_pnl_share", "asset_concentration"),
        ("maximum_positive_week_pnl_share", "maximum_positive_week_pnl_share", "week_concentration"),
        ("maximum_top_three_positive_week_pnl_share", "maximum_top_three_positive_week_pnl_share", "top_three_week_concentration"),
    ):
        value = expected[key]
        if value is None or float(value) > float(gate[threshold]):
            reasons.append(reason)

    candidate_sharpe = expected["aggregate_sharpe_4h"]
    ablation_sharpe = ablation["aggregate_sharpe_4h"]
    if candidate_sharpe is None or ablation_sharpe is None or float(candidate_sharpe) <= float(ablation_sharpe):
        reasons.append("incremental_sharpe")
    if float(expected["maximum_half_drawdown"]) > float(ablation["maximum_half_drawdown"]):
        reasons.append("incremental_drawdown")
    if float(expected["annualized_one_way_turnover"]) > float(ablation["annualized_one_way_turnover"]):
        reasons.append("incremental_turnover")

    selected = CANDIDATE_ID if not reasons else None
    return {
        "schema_version": 1,
        "stage": "C5A",
        "economic_result": "SELECTED" if selected else "REJECTED",
        "selected_policy": selected,
        "eligible": not reasons,
        "rejection_reasons": reasons,
        "candidate_expected": dict(expected),
        "candidate_stress_1_5x": dict(stress),
        "price_only_ablation": dict(ablation),
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def run_screen(
    datasets: Mapping[str, Any],
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    market = prepare_market(datasets)
    calibration = build_calibration(market, config)
    policy_rows = [
        simulate_policy_half(
            market,
            calibration,
            policy_id=policy,
            window=window,
            cost_label=cost,
            config=config,
        )
        for policy in (CANDIDATE_ID, ABLATION_ID)
        for window in config["screen_windows"]
        for cost in COST_LABELS
    ]
    comparator_rows = [
        simulate_comparator_half(
            market,
            comparator_id=comparator,
            window=window,
            cost_label=cost,
            config=config,
        )
        for comparator in COMPARATORS
        for window in config["screen_windows"]
        for cost in COST_LABELS
    ]
    if len(policy_rows) != 12 or len(comparator_rows) != 18:
        raise C5AError("C5A frozen cell count mismatch")
    aggregates = [
        aggregate_policy(
            policy_rows, policy_id=policy, cost_label=cost, config=config
        )
        for policy in (CANDIDATE_ID, ABLATION_ID)
        for cost in COST_LABELS
    ]
    comparator_aggregates = [
        aggregate_comparator(
            comparator_rows,
            comparator_id=comparator,
            cost_label=cost,
            config=config,
        )
        for comparator in COMPARATORS
        for cost in COST_LABELS
    ]
    decision = decide(aggregates, config)
    return {
        "schema_version": 1,
        "stage": "C5A",
        "status": "PASS",
        "calibration": calibration,
        "policy_rows": policy_rows,
        "comparator_rows": comparator_rows,
        "policy_aggregates": aggregates,
        "comparator_aggregates": comparator_aggregates,
        "decision": decision,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }
