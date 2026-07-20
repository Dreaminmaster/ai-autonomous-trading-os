"""Narrow contract-hardening layer for the frozen C4A research engine.

The base engine contains the economic implementation.  This module adds the
post-design erratum checks and evidence fields without changing signals,
portfolio targets, costs, gates, or ranking.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

import pandas as pd

from . import c4a_cross_sectional_momentum as _base

C4AError = _base.C4AError
CANDIDATE_PAIRS = _base.CANDIDATE_PAIRS
POLICIES = _base.POLICIES
COMPARATORS = _base.COMPARATORS
COST_LABELS = _base.COST_LABELS

_ORIGINAL_VALIDATE_CONFIG = _base.validate_config
_ORIGINAL_SIMULATE_WINDOW = _base.simulate_window
_ORIGINAL_AGGREGATE_POLICY = _base.aggregate_policy

EXPECTED_CONTRACT_PATHS = [
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_LARGE_LIQUID_CROSS_SECTIONAL_MOMENTUM_CONTRACT_V1.md",
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_UNIVERSE_AND_MULTIPLE_TESTING_ADDENDUM_V1.md",
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_WEEKLY_BOUNDARY_CLARIFICATION_V1.md",
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_DSR_AND_UNIVERSE_SCOPE_CLARIFICATION_V1.md",
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_ACCOUNTING_AND_CONTRIBUTION_CLARIFICATION_V1.md",
    "docs/architecture/phase-c/c4a-large-liquid-cross-sectional-momentum/C4A_EXPOSURE_ERRATUM_V1.md",
]
EXPECTED_RESERVED_WINDOWS = [
    {"id": "C1", "start": "2024-10-01T00:00:00Z", "end": "2025-01-01T00:00:00Z"},
    {"id": "C2", "start": "2025-01-01T00:00:00Z", "end": "2025-04-01T00:00:00Z"},
    {"id": "C3", "start": "2025-04-01T00:00:00Z", "end": "2025-07-01T00:00:00Z"},
]
EXPECTED_GATE = {
    "minimum_positive_windows": 2,
    "minimum_aggregate_sharpe": 0.75,
    "minimum_within_stage_dsr_probability": 0.90,
    "maximum_window_drawdown_ratio": 0.15,
    "minimum_active_rebalances": 12,
    "minimum_active_rebalances_per_window": 3,
    "minimum_closed_asset_lots": 18,
    "maximum_annualized_one_way_turnover": 18.0,
    "maximum_exposure_ratio": 0.90,
    "minimum_positive_assets": 4,
    "maximum_window_positive_pnl_share": 0.70,
    "maximum_asset_positive_pnl_share": 0.45,
    "maximum_week_positive_pnl_share": 0.25,
    "maximum_top_three_week_positive_pnl_share": 0.55,
}
EXPECTED_SELECTION_ORDER = [
    "minimum_window_net_return_desc",
    "within_stage_dsr_probability_desc",
    "median_window_net_return_desc",
    "aggregate_1_5x_net_return_desc",
    "maximum_window_drawdown_asc",
    "annualized_one_way_turnover_asc",
    "policy_id_asc",
]


def validate_config(config: Mapping[str, Any]) -> None:
    _ORIGINAL_VALIDATE_CONFIG(config)
    if config.get("contract_paths") != EXPECTED_CONTRACT_PATHS:
        raise C4AError("C4A contract path drift")
    if config.get("reserved_confirmation_windows") != EXPECTED_RESERVED_WINDOWS:
        raise C4AError("C4A reserved confirmation drift")
    if config.get("gate") != EXPECTED_GATE:
        raise C4AError("C4A gate drift")
    if config.get("selection_order") != EXPECTED_SELECTION_ORDER:
        raise C4AError("C4A selection-order drift")


def _event_by_time(row: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    events: dict[str, Mapping[str, Any]] = {}
    for event in row["events"]:
        if event.get("kind") in {"SCHEDULED_REBALANCE", "FORCED_CASH"}:
            events[str(event["time"])] = event
    return events


def _retain_forced_stub_signal(
    row: dict[str, Any],
    market: Any,
    *,
    selected_pairs: Sequence[str],
    policy: str,
    config: Mapping[str, Any],
) -> None:
    if row["window_id"] != "S3":
        return
    forced = [item for item in row["signals"] if item.get("forced_cash")]
    if len(forced) != 1:
        raise C4AError("missing unique forced-stub signal record")
    audit = _base.signal_snapshot(
        market,
        execution_time=pd.Timestamp("2024-09-30T00:00:00Z"),
        selected_pairs=selected_pairs,
        policy=policy,
        config=config,
    )
    record = forced[0]
    pre_override_targets = dict(audit["target_weights"])
    rows = []
    for item in audit["rows"]:
        enriched = dict(item)
        enriched["pre_boundary_selected_target"] = bool(item["selected_target"])
        enriched["selected_target"] = False
        rows.append(enriched)
    record.update(audit)
    record["risk_on_before_boundary_override"] = bool(audit["risk_on"])
    record["pre_boundary_target_weights"] = pre_override_targets
    record["chosen_pairs"] = []
    record["target_weights"] = {}
    record["risk_on"] = False
    record["forced_cash"] = True
    record["rows"] = rows


def _enrich_week_evidence(row: dict[str, Any]) -> None:
    events = _event_by_time(row)
    for week in row["full_weeks"]:
        event = events.get(str(week["execution_time"]))
        if event is None:
            raise C4AError("missing weekly rebalance evidence")
        week["pre_trade_open_equity"] = float(event["equity_before"])
        week["monday_rebalance_fee"] = float(event["total_fee"])
        week["post_trade_equity"] = float(event["equity_after"])
    stub = None
    if row["window_id"] == "S3":
        forced = [event for event in row["events"] if event.get("kind") == "FORCED_CASH"]
        if len(forced) != 1:
            raise C4AError("missing unique S3 forced-cash event")
        event = forced[0]
        start_equity = float(event["equity_before"]) - float(event["boundary_gap_pnl"])
        stub = {
            "start_time": "2024-09-29T20:00:00+00:00",
            "start_equity": start_equity,
            "execution_time": str(event["time"]),
            "pre_trade_open_equity": float(event["equity_before"]),
            "boundary_gap_pnl": float(event["boundary_gap_pnl"]),
            "forced_liquidation_fee": float(event["total_fee"]),
            "post_trade_equity": float(event["equity_after"]),
            "end_time": str(row["marks"][-1]["time"]),
            "final_equity": float(row["final_equity"]),
            "net_pnl": float(row["terminal_stub_net_pnl"]),
        }
    row["terminal_stub"] = stub
    bucket_pnl = sum(float(item["net_pnl"]) for item in row["full_weeks"])
    bucket_pnl += float(row["terminal_stub_net_pnl"])
    window_pnl = float(row["final_equity"]) - float(row["starting_equity"])
    if abs(bucket_pnl - window_pnl) > 1e-9:
        raise C4AError("weekly contribution reconciliation failure")


def simulate_window(
    market: Any,
    *,
    selected_pairs: Sequence[str],
    policy: str,
    window: Mapping[str, Any],
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    row = _ORIGINAL_SIMULATE_WINDOW(
        market,
        selected_pairs=selected_pairs,
        policy=policy,
        window=window,
        cost_label=cost_label,
        config=config,
    )
    _retain_forced_stub_signal(
        row,
        market,
        selected_pairs=selected_pairs,
        policy=policy,
        config=config,
    )
    _enrich_week_evidence(row)
    return row


def aggregate_policy(
    rows: Sequence[Mapping[str, Any]],
    *,
    policy: str,
    cost_label: str,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    validate_config(config)
    result = _ORIGINAL_AGGREGATE_POLICY(
        rows,
        policy=policy,
        cost_label=cost_label,
        config=config,
    )
    window_rows = result["window_rows"]
    window_pnl = sum(
        float(row["final_equity"]) - float(config["starting_equity"])
        for row in window_rows
    )
    bucket_pnl = sum(float(value) for value in result["full_week_pnl"])
    bucket_pnl += sum(float(row["terminal_stub_net_pnl"]) for row in window_rows)
    if abs(window_pnl - bucket_pnl) > 1e-9:
        raise C4AError("aggregate week/stub reconciliation failure")
    result["window_net_pnl"] = window_pnl
    result["week_and_stub_net_pnl"] = bucket_pnl
    return result


# Patch the base module once so its public orchestration uses the hardened
# contract functions while preserving the independently testable base code.
_base.validate_config = validate_config
_base.simulate_window = simulate_window
_base.aggregate_policy = aggregate_policy

prepare_market = _base.prepare_market
expected_grid = _base.expected_grid
select_universe = _base.select_universe
scheduled_decisions = _base.scheduled_decisions
signal_snapshot = _base.signal_snapshot
solve_post_cost_equity = _base.solve_post_cost_equity
simulate_comparator = _base.simulate_comparator
aggregate_comparator = _base.aggregate_comparator
attach_within_stage_dsr = _base.attach_within_stage_dsr
decide = _base.decide
run_screen = _base.run_screen
