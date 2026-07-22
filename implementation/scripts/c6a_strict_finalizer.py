#!/usr/bin/env python3
"""Authoritative strict independent C6A finalizer.

This is the finalizer entry point intended for the temporary authoritative
workflow.  It performs the exact evidence-shape preflight, reconstructs all 60
cells from primitive public inputs, handles economically undefined weekly
statistics as an explicit rejection state rather than an evidence crash,
compares every gate-driving aggregate field, and independently recomputes the
final gate decision.

It imports no production candidate, rounding, ledger, simulation, comparator,
aggregate, statistics, or gate implementation.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c6a_contract import C6AError, validate_config
from atos.c6a_evidence import verify_manifest, write_json_atomic
from atos.c6a_io import load_canonical_inputs
from scripts import c6a_finalizer as comparison
from scripts import c6a_finalizer_preflight
from scripts import c6a_program_guard
from scripts.c6a_reference_comparators import (
    reference_cash_window,
    reference_spot_buy_hold_window,
)
from scripts.c6a_reference_gate import reference_gate
from scripts.c6a_reference_recompute import recompute_window, reference_statistics

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = IMPL / "config/c6a_market_neutral_funding_carry.json"
DEFAULT_PREPARE_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_prepare_report.json"
DEFAULT_RESULTS = IMPL / "freqtrade_data/c6a_results"
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_runtime/c6a_strict_final_evidence.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ZERO = Decimal("0")
ONE = Decimal("1")
POLICY_IDS = comparison.POLICY_IDS
COST_LABELS = comparison.COST_LABELS
WINDOW_IDS = comparison.WINDOW_IDS
NEUTRAL_POLICIES = {
    "C6AMarketNeutralFundingCarry",
    "AlwaysOnDeltaNeutralComparator",
}


class C6AStrictFinalizerError(RuntimeError):
    pass


def _source_sha() -> str:
    value = os.environ.get("C6A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C6AStrictFinalizerError(
            "C6A_SOURCE_SHA must be an exact lowercase 40-character SHA"
        )
    return value


def _read(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6AStrictFinalizerError(f"unable to load {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C6AStrictFinalizerError(f"{label} must be an object")
    return payload


def safe_reference_aggregate(windows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_id = {str(row["window_id"]): row for row in windows}
    if set(by_id) != set(WINDOW_IDS):
        raise C6AStrictFinalizerError("reference aggregate window set mismatch")
    ordered = [by_id[window] for window in WINDOW_IDS]
    identities = {(row["policy_id"], row["cost_label"]) for row in ordered}
    if len(identities) != 1:
        raise C6AStrictFinalizerError("reference aggregate mixes policy or cost")
    weekly_returns = [
        bucket["return"] for row in ordered for bucket in row["weekly"]
    ]
    if len(weekly_returns) != 130:
        raise C6AStrictFinalizerError("reference aggregate weekly count mismatch")
    try:
        statistics = reference_statistics(weekly_returns)
        statistics_error = None
    except C6AError as exc:
        statistics = None
        statistics_error = str(exc)
    final_equities = [row["final_equity"] for row in ordered]
    window_pnl = {
        row["window_id"]: row["final_equity"] - Decimal("1000")
        for row in ordered
    }
    weekly_pnl = {
        f"{row['window_id']}-week-{index:02d}": bucket["pnl"]
        for row in ordered
        for index, bucket in enumerate(row["weekly"])
    }
    if sum(window_pnl.values(), ZERO) != sum(weekly_pnl.values(), ZERO):
        raise C6AStrictFinalizerError("reference window/weekly PnL mismatch")
    asset_pnl = {"BTC": ZERO, "ETH": ZERO}
    for row in ordered:
        for asset in asset_pnl:
            asset_pnl[asset] += row["asset_contributions"][asset]
    spot_cost = sum((row["components"].spot_cost for row in ordered), ZERO)
    swap_cost = sum((row["components"].swap_cost for row in ordered), ZERO)
    receipts = sum(
        (
            max(event["pnl"], ZERO)
            for row in ordered
            for event in row["events"]
            if event["kind"] == "FUNDING"
        ),
        ZERO,
    )
    payments = sum(
        (
            max(-event["pnl"], ZERO)
            for row in ordered
            for event in row["events"]
            if event["kind"] == "FUNDING"
        ),
        ZERO,
    )
    total_costs = spot_cost + swap_cost
    policy_id, cost_label = next(iter(identities))
    return {
        "policy_id": policy_id,
        "cost_label": cost_label,
        "aggregate_return": sum(final_equities, ZERO) / Decimal("5000") - ONE,
        "window_returns": {row["window_id"]: row["net_return"] for row in ordered},
        "window_pnl": window_pnl,
        "weekly_returns": weekly_returns,
        "weekly_pnl": weekly_pnl,
        "statistics": statistics,
        "statistics_error": statistics_error,
        "maximum_drawdown": max(row["maximum_drawdown"] for row in ordered),
        "annualized_one_way_turnover": sum(
            (row["annualized_one_way_turnover"] for row in ordered), ZERO
        )
        / Decimal("5"),
        "gross_funding_receipts": receipts,
        "gross_funding_payments": payments,
        "total_trading_costs": total_costs,
        "funding_cost_coverage": None if total_costs == 0 else receipts / total_costs,
        "active_weeks_total": sum(int(row["active_week_count"]) for row in ordered),
        "active_weeks_by_window": {
            row["window_id"]: int(row["active_week_count"]) for row in ordered
        },
        "active_funding_settlements": sum(
            int(row["active_funding_settlements"]) for row in ordered
        ),
        "collateral_buffer_breaches": sum(
            int(row["collateral_buffer_breaches"]) for row in ordered
        ),
        "hedge_breaches": sum(int(row["hedge_breaches"]) for row in ordered),
        "asset_pnl": asset_pnl,
    }


def _assert_mapping_decimal(
    production: Any, reference: Mapping[str, Decimal], *, label: str
) -> None:
    if not isinstance(production, Mapping) or set(production) != set(reference):
        raise C6AStrictFinalizerError(f"{label} key-set mismatch")
    for key, expected in reference.items():
        comparison._assert_decimal(production[key], expected, f"{label}.{key}")


def compare_neutral_aggregate(
    production: Mapping[str, Any], reference: Mapping[str, Any], *, label: str
) -> None:
    comparison.compare_aggregate(production, reference, label=label)
    _assert_mapping_decimal(
        production.get("window_pnl"), reference["window_pnl"],
        label=f"{label}.window_pnl",
    )
    _assert_mapping_decimal(
        production.get("weekly_pnl"), reference["weekly_pnl"],
        label=f"{label}.weekly_pnl",
    )
    production_weekly = production.get("weekly_returns")
    if not isinstance(production_weekly, list) or len(production_weekly) != 130:
        raise C6AStrictFinalizerError(f"{label}.weekly_returns count mismatch")
    for index, expected in enumerate(reference["weekly_returns"]):
        comparison._assert_decimal(
            production_weekly[index], expected, f"{label}.weekly_returns.{index}"
        )
    for field in (
        "gross_funding_receipts",
        "gross_funding_payments",
        "total_trading_costs",
        "maximum_drawdown",
        "annualized_one_way_turnover",
    ):
        comparison._assert_decimal(
            production.get(field), reference[field], f"{label}.{field}"
        )
    expected_coverage = reference["funding_cost_coverage"]
    if expected_coverage is None:
        if production.get("funding_cost_coverage") is not None:
            raise C6AStrictFinalizerError(
                f"{label}.funding_cost_coverage must be null"
            )
    else:
        comparison._assert_decimal(
            production.get("funding_cost_coverage"),
            expected_coverage,
            f"{label}.funding_cost_coverage",
        )
    for field in (
        "active_weeks_total",
        "active_funding_settlements",
        "collateral_buffer_breaches",
        "hedge_breaches",
    ):
        if int(production.get(field, -1)) != int(reference[field]):
            raise C6AStrictFinalizerError(f"{label}.{field} mismatch")
    production_active = production.get("active_weeks_by_window")
    if production_active != reference["active_weeks_by_window"]:
        raise C6AStrictFinalizerError(
            f"{label}.active_weeks_by_window mismatch"
        )
    _assert_mapping_decimal(
        production.get("asset_pnl"), reference["asset_pnl"],
        label=f"{label}.asset_pnl",
    )
    if production.get("statistics_error") != reference["statistics_error"]:
        raise C6AStrictFinalizerError(f"{label}.statistics_error mismatch")
    if reference["statistics"] is None:
        if production.get("statistics") is not None:
            raise C6AStrictFinalizerError(f"{label}.statistics must be null")


def strict_finalize(
    *,
    config: Mapping[str, Any],
    prepare_report: Mapping[str, Any],
    result_dir: Path,
    source_sha: str,
) -> dict[str, Any]:
    validate_config(config)
    preflight = c6a_finalizer_preflight.preflight(result_dir)
    authority = c6a_program_guard.verify_authorities(c6a_program_guard.ROOT, config)
    manifest = _read(result_dir / "manifest.json", "C6A manifest")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise C6AStrictFinalizerError("C6A manifest entries missing")
    verify_manifest(result_dir, entries)
    run_summary = _read(result_dir / "run_summary.json", "C6A run summary")
    if run_summary.get("source_head_sha") != source_sha:
        raise C6AStrictFinalizerError("C6A run-summary source SHA mismatch")
    market, funding, metadata = load_canonical_inputs(prepare_report)

    references: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    cell_checks: list[dict[str, Any]] = []
    for policy in POLICY_IDS:
        for cost in COST_LABELS:
            for window in config["windows"]:
                window_id = str(window["id"])
                if policy in NEUTRAL_POLICIES:
                    reference = recompute_window(
                        market,
                        funding,
                        metadata,
                        policy_id=policy,
                        window=window,
                        cost_label=cost,
                        config=config,
                    )
                elif policy == "CashComparator":
                    reference = reference_cash_window(
                        window=window, cost_label=cost, config=config
                    )
                else:
                    reference = reference_spot_buy_hold_window(
                        market,
                        metadata,
                        window=window,
                        cost_label=cost,
                        config=config,
                    )
                production = _read(
                    result_dir / "cells" / policy / cost / f"{window_id}.json",
                    f"C6A cell {policy}/{cost}/{window_id}",
                )
                references[(policy, cost, window_id)] = reference
                cell_checks.append(
                    comparison.compare_cell(
                        production,
                        reference,
                        label=f"{policy}/{cost}/{window_id}",
                    )
                )

    aggregate_references: dict[tuple[str, str], Mapping[str, Any]] = {}
    aggregate_checks: list[dict[str, Any]] = []
    for policy in POLICY_IDS:
        for cost in COST_LABELS:
            windows = [references[(policy, cost, window)] for window in WINDOW_IDS]
            if policy in NEUTRAL_POLICIES:
                reference = safe_reference_aggregate(windows)
            else:
                reference = comparison._reference_descriptive_aggregate(
                    windows, policy_id=policy, cost_label=cost
                )
            aggregate_references[(policy, cost)] = reference
            production = _read(
                result_dir / "aggregates" / policy / f"{cost}.json",
                f"C6A aggregate {policy}/{cost}",
            )
            if policy in NEUTRAL_POLICIES:
                compare_neutral_aggregate(
                    production, reference, label=f"{policy}/{cost}"
                )
            else:
                comparison.compare_aggregate(
                    production, reference, label=f"{policy}/{cost}"
                )
            aggregate_checks.append(
                {"aggregate": f"{policy}/{cost}", "status": "PASS"}
            )

    reference_decision = reference_gate(
        candidate_by_cost={
            cost: aggregate_references[("C6AMarketNeutralFundingCarry", cost)]
            for cost in COST_LABELS
        },
        always_on_expected=aggregate_references[
            ("AlwaysOnDeltaNeutralComparator", "1.0x")
        ],
        config=config,
    )
    production_decision = _read(result_dir / "decision.json", "C6A decision")
    if production_decision.get("status") != reference_decision["status"]:
        raise C6AStrictFinalizerError("C6A final decision status mismatch")
    if production_decision.get("selected_policy") != reference_decision[
        "selected_policy"
    ]:
        raise C6AStrictFinalizerError("C6A final selected-policy mismatch")
    if production_decision.get("checks") != reference_decision["checks"]:
        raise C6AStrictFinalizerError("C6A final gate-check map mismatch")
    if tuple(production_decision.get("rejection_reasons", ())) != tuple(
        reference_decision["rejection_reasons"]
    ):
        raise C6AStrictFinalizerError("C6A final rejection-reason mismatch")
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "program_guard_status": authority["status"],
        "preflight_status": preflight["status"],
        "manifest_status": "PASS",
        "manifest_entry_count": int(manifest.get("entry_count", -1)),
        "cell_check_count": len(cell_checks),
        "aggregate_check_count": len(aggregate_checks),
        "weekly_row_count": sum(row["weekly_rows"] for row in cell_checks),
        "decision_row_count": sum(row["decision_rows"] for row in cell_checks),
        "economic_result": reference_decision["status"],
        "selected_policy": reference_decision["selected_policy"],
        "rejection_reasons": list(reference_decision["rejection_reasons"]),
        "undefined_statistics_fail_closed": True,
        "all_gate_driving_aggregate_fields_compared": True,
        "independent_import_boundary": {
            "production_policy_imported": False,
            "production_rounding_imported": False,
            "production_ledger_imported": False,
            "production_simulation_imported": False,
            "production_comparator_imported": False,
            "production_aggregate_imported": False,
            "production_statistics_imported": False,
            "production_gate_imported": False,
        },
        "confirmation_opened": False,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--prepare-report", type=Path, default=DEFAULT_PREPARE_REPORT)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    source_sha = _source_sha()
    config = _read(args.config, "C6A config")
    prepare_report = _read(args.prepare_report, "C6A prepare report")
    try:
        report = strict_finalize(
            config=config,
            prepare_report=prepare_report,
            result_dir=args.results,
            source_sha=source_sha,
        )
    except C6AError as exc:
        raise C6AStrictFinalizerError(str(exc)) from exc
    write_json_atomic(args.output, report)
    print(
        "C6A strict independent finalization PASS: "
        f"{report['economic_result']} / selected={report['selected_policy']} / "
        "all 60 cells and every gate-driving aggregate field verified"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
