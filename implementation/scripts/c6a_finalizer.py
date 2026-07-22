#!/usr/bin/env python3
"""Independently finalize a completed C6A result directory.

The finalizer reconstructs all 60 cells from canonical primitive public inputs
without importing production policy, rounding, ledger, simulation, comparator,
aggregate, statistics, or gate modules.  It verifies the production manifest,
window accounting, decisions, aggregate metrics, and final gate decision.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c6a_contract import C6AError, validate_config
from atos.c6a_evidence import ManifestEntry, verify_manifest, write_json_atomic
from atos.c6a_io import load_canonical_inputs
from scripts import c6a_program_guard
from scripts.c6a_reference_comparators import (
    reference_cash_window,
    reference_spot_buy_hold_window,
)
from scripts.c6a_reference_gate import reference_gate
from scripts.c6a_reference_recompute import aggregate_reference, recompute_window

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = IMPL / "config/c6a_market_neutral_funding_carry.json"
DEFAULT_PREPARE_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_prepare_report.json"
DEFAULT_RESULTS = IMPL / "freqtrade_data/c6a_results"
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_runtime/c6a_final_evidence.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DECIMAL_TOLERANCE = Decimal("1e-12")
FLOAT_TOLERANCE = 1e-12
POLICY_IDS = (
    "C6AMarketNeutralFundingCarry",
    "AlwaysOnDeltaNeutralComparator",
    "CashComparator",
    "SpotBuyAndHoldComparator",
)
COST_LABELS = ("1.0x", "1.5x", "2.0x")
WINDOW_IDS = ("W1", "W2", "W3", "W4", "W5")


class C6AFinalizerError(RuntimeError):
    pass


def _exact_source_sha() -> str:
    value = os.environ.get("C6A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C6AFinalizerError(
            "C6A_SOURCE_SHA must be an exact lowercase 40-character SHA"
        )
    return value


def _read_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6AFinalizerError(f"unable to load {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C6AFinalizerError(f"{label} must be a JSON object")
    return payload


def _decimal(value: Any, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:  # noqa: BLE001 - converted to evidence error
        raise C6AFinalizerError(f"invalid decimal {label}: {value!r}") from exc
    if not result.is_finite():
        raise C6AFinalizerError(f"non-finite decimal {label}")
    return result


def _assert_decimal(actual: Any, expected: Decimal, label: str) -> None:
    observed = _decimal(actual, label)
    if abs(observed - expected) > DECIMAL_TOLERANCE:
        raise C6AFinalizerError(
            f"{label} mismatch: production={observed} reference={expected}"
        )


def _assert_float(actual: Any, expected: float, label: str) -> None:
    try:
        observed = float(actual)
    except (TypeError, ValueError) as exc:
        raise C6AFinalizerError(f"invalid float {label}: {actual!r}") from exc
    if abs(observed - expected) > FLOAT_TOLERANCE:
        raise C6AFinalizerError(
            f"{label} mismatch: production={observed} reference={expected}"
        )


def _component_reference(value: Any, field: str) -> Decimal:
    if isinstance(value, Mapping):
        return _decimal(value[field], field)
    return getattr(value, field)


def compare_cell(
    production: Mapping[str, Any], reference: Mapping[str, Any], *, label: str
) -> dict[str, Any]:
    for field in (
        "policy_id",
        "window_id",
        "cost_label",
    ):
        if str(production.get(field)) != str(reference[field]):
            raise C6AFinalizerError(f"{label} {field} mismatch")
    for field in (
        "starting_equity",
        "final_equity",
        "net_return",
        "maximum_drawdown",
        "annualized_one_way_turnover",
    ):
        _assert_decimal(production.get(field), reference[field], f"{label}.{field}")
    for field in (
        "active_week_count",
        "active_funding_settlements",
        "collateral_buffer_breaches",
        "hedge_breaches",
    ):
        if int(production.get(field, -1)) != int(reference[field]):
            raise C6AFinalizerError(f"{label}.{field} mismatch")
    production_assets = production.get("asset_contributions")
    if not isinstance(production_assets, Mapping) or set(production_assets) != {"BTC", "ETH"}:
        raise C6AFinalizerError(f"{label}.asset_contributions invalid")
    for asset in ("BTC", "ETH"):
        _assert_decimal(
            production_assets[asset], reference["asset_contributions"][asset],
            f"{label}.asset_contributions.{asset}",
        )
    production_components = production.get("components")
    if not isinstance(production_components, Mapping):
        raise C6AFinalizerError(f"{label}.components missing")
    for field in (
        "spot_price_pnl",
        "perpetual_price_pnl",
        "funding_pnl",
        "spot_cost",
        "swap_cost",
    ):
        _assert_decimal(
            production_components.get(field),
            _component_reference(reference["components"], field),
            f"{label}.components.{field}",
        )
    production_weeks = production.get("weekly_buckets")
    reference_weeks = reference["weekly"]
    if not isinstance(production_weeks, list) or len(production_weeks) != len(reference_weeks) != 26:
        raise C6AFinalizerError(f"{label}.weekly count mismatch")
    for index, (observed, expected) in enumerate(
        zip(production_weeks, reference_weeks, strict=True)
    ):
        _assert_decimal(observed.get("weekly_pnl"), expected["pnl"], f"{label}.week{index}.pnl")
        _assert_decimal(
            observed.get("weekly_return"), expected["return"],
            f"{label}.week{index}.return",
        )
        if bool(observed.get("active")) != bool(expected["active"]):
            raise C6AFinalizerError(f"{label}.week{index}.active mismatch")
        if bool(observed.get("risk_exit")) != bool(expected["risk_exit"]):
            raise C6AFinalizerError(f"{label}.week{index}.risk mismatch")
        _assert_decimal(
            observed.get("reconciliation_residual", "0"),
            Decimal("0"),
            f"{label}.week{index}.reconciliation",
        )
    if reference["policy_id"] in {
        "C6AMarketNeutralFundingCarry",
        "AlwaysOnDeltaNeutralComparator",
    }:
        production_decisions = production.get("decisions")
        reference_decisions = reference["decisions"]
        if not isinstance(production_decisions, list) or len(production_decisions) != 26:
            raise C6AFinalizerError(f"{label}.decision count mismatch")
        for index, (observed, expected) in enumerate(
            zip(production_decisions, reference_decisions, strict=True)
        ):
            if observed.get("time") != expected["time"].isoformat():
                raise C6AFinalizerError(f"{label}.decision{index}.time mismatch")
            if tuple(observed.get("eligible_assets", ())) != expected["eligible_assets"]:
                raise C6AFinalizerError(
                    f"{label}.decision{index}.eligible-assets mismatch"
                )
            _assert_decimal(
                observed.get("target_scale"), expected["scale"],
                f"{label}.decision{index}.scale",
            )
            _assert_decimal(
                observed.get("solver_residual_cash"), expected["residual_cash"],
                f"{label}.decision{index}.residual",
            )
            targets = observed.get("targets")
            if not isinstance(targets, list) or len(targets) != 2:
                raise C6AFinalizerError(f"{label}.decision{index}.targets invalid")
            target_map = {str(row.get("spot_instrument")): row for row in targets}
            for spot, expected_target in expected["targets"].items():
                actual_target = target_map.get(spot)
                if actual_target is None:
                    raise C6AFinalizerError(
                        f"{label}.decision{index}.{spot} target missing"
                    )
                if actual_target.get("action") != expected_target["action"]:
                    raise C6AFinalizerError(
                        f"{label}.decision{index}.{spot}.action mismatch"
                    )
                for production_field, reference_field in (
                    ("spot_quantity", "spot_quantity"),
                    ("perpetual_base_quantity", "swap_quantity"),
                    ("dedicated_collateral", "collateral"),
                    ("hedge_error", "hedge_error"),
                ):
                    _assert_decimal(
                        actual_target.get(production_field),
                        expected_target[reference_field],
                        f"{label}.decision{index}.{spot}.{production_field}",
                    )
    return {
        "cell": label,
        "status": "PASS",
        "weekly_rows": 26,
        "decision_rows": 26 if reference["policy_id"] in {
            "C6AMarketNeutralFundingCarry",
            "AlwaysOnDeltaNeutralComparator",
        } else 0,
    }


def _load_cells(result_dir: Path) -> dict[tuple[str, str, str], Mapping[str, Any]]:
    cells: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    for policy in POLICY_IDS:
        for cost in COST_LABELS:
            for window in WINDOW_IDS:
                path = result_dir / "cells" / policy / cost / f"{window}.json"
                cells[(policy, cost, window)] = _read_object(
                    path, f"C6A cell {policy}/{cost}/{window}"
                )
    return cells


def _reference_descriptive_aggregate(
    windows: Sequence[Mapping[str, Any]], *, policy_id: str, cost_label: str
) -> dict[str, Any]:
    by_id = {str(row["window_id"]): row for row in windows}
    ordered = [by_id[window] for window in WINDOW_IDS]
    weekly = [bucket["return"] for row in ordered for bucket in row["weekly"]]
    final = sum((row["final_equity"] for row in ordered), Decimal("0"))
    return {
        "policy_id": policy_id,
        "cost_label": cost_label,
        "aggregate_return": final / Decimal("5000") - Decimal("1"),
        "window_returns": {row["window_id"]: row["net_return"] for row in ordered},
        "weekly_returns": weekly,
        "maximum_drawdown": max(row["maximum_drawdown"] for row in ordered),
        "annualized_one_way_turnover": sum(
            (row["annualized_one_way_turnover"] for row in ordered), Decimal("0")
        ) / Decimal("5"),
    }


def compare_aggregate(
    production: Mapping[str, Any], reference: Mapping[str, Any], *, label: str
) -> None:
    if production.get("policy_id") != reference["policy_id"] or production.get(
        "cost_label"
    ) != reference["cost_label"]:
        raise C6AFinalizerError(f"{label} aggregate identity mismatch")
    for field in (
        "aggregate_return",
        "maximum_drawdown",
        "annualized_one_way_turnover",
    ):
        _assert_decimal(production.get(field), reference[field], f"{label}.{field}")
    observed_windows = production.get("window_returns")
    if not isinstance(observed_windows, Mapping):
        raise C6AFinalizerError(f"{label}.window_returns missing")
    for window, value in reference["window_returns"].items():
        _assert_decimal(
            observed_windows.get(window), value, f"{label}.window_returns.{window}"
        )
    production_statistics = production.get("statistics")
    reference_statistics = reference.get("statistics")
    if reference_statistics is not None:
        if not isinstance(production_statistics, Mapping):
            raise C6AFinalizerError(f"{label}.statistics missing")
        for field in (
            "mean",
            "sample_std",
            "weekly_sharpe",
            "annualized_weekly_sharpe",
            "unbiased_skewness",
            "unbiased_ordinary_kurtosis",
            "psr_numerator",
            "psr_denominator",
            "psr_z_score",
            "psr_probability",
        ):
            _assert_float(
                production_statistics.get(field),
                float(reference_statistics[field]),
                f"{label}.statistics.{field}",
            )


def finalize(
    *,
    config: Mapping[str, Any],
    prepare_report: Mapping[str, Any],
    result_dir: Path,
    source_sha: str,
) -> dict[str, Any]:
    validate_config(config)
    authority = c6a_program_guard.verify_authorities(c6a_program_guard.ROOT, config)
    manifest = _read_object(result_dir / "manifest.json", "C6A result manifest")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise C6AFinalizerError("C6A result manifest entries missing")
    verify_manifest(result_dir, entries)
    run_summary = _read_object(result_dir / "run_summary.json", "C6A run summary")
    if run_summary.get("source_head_sha") != source_sha:
        raise C6AFinalizerError("C6A run summary source SHA mismatch")
    if (
        run_summary.get("result_cell_count") != 60
        or run_summary.get("aggregate_count") != 12
        or run_summary.get("weekly_bucket_count") != 1560
    ):
        raise C6AFinalizerError("C6A run summary evidence count mismatch")
    market, funding, metadata = load_canonical_inputs(prepare_report)
    production_cells = _load_cells(result_dir)
    reference_cells: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    cell_checks: list[dict[str, Any]] = []
    for policy in POLICY_IDS:
        for cost in COST_LABELS:
            for window in config["windows"]:
                window_id = str(window["id"])
                if policy in {
                    "C6AMarketNeutralFundingCarry",
                    "AlwaysOnDeltaNeutralComparator",
                }:
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
                key = (policy, cost, window_id)
                reference_cells[key] = reference
                cell_checks.append(
                    compare_cell(
                        production_cells[key],
                        reference,
                        label=f"{policy}/{cost}/{window_id}",
                    )
                )

    reference_aggregates: dict[tuple[str, str], Mapping[str, Any]] = {}
    aggregate_checks: list[dict[str, Any]] = []
    for policy in POLICY_IDS:
        for cost in COST_LABELS:
            windows = [reference_cells[(policy, cost, window)] for window in WINDOW_IDS]
            if policy in {
                "C6AMarketNeutralFundingCarry",
                "AlwaysOnDeltaNeutralComparator",
            }:
                reference = aggregate_reference(windows)
            else:
                reference = _reference_descriptive_aggregate(
                    windows, policy_id=policy, cost_label=cost
                )
            reference_aggregates[(policy, cost)] = reference
            production = _read_object(
                result_dir / "aggregates" / policy / f"{cost}.json",
                f"C6A aggregate {policy}/{cost}",
            )
            compare_aggregate(production, reference, label=f"{policy}/{cost}")
            aggregate_checks.append(
                {"aggregate": f"{policy}/{cost}", "status": "PASS"}
            )

    reference_decision = reference_gate(
        candidate_by_cost={
            cost: reference_aggregates[("C6AMarketNeutralFundingCarry", cost)]
            for cost in COST_LABELS
        },
        always_on_expected=reference_aggregates[
            ("AlwaysOnDeltaNeutralComparator", "1.0x")
        ],
        config=config,
    )
    production_decision = _read_object(result_dir / "decision.json", "C6A decision")
    if production_decision.get("status") != reference_decision["status"]:
        raise C6AFinalizerError("C6A final decision status mismatch")
    if production_decision.get("selected_policy") != reference_decision["selected_policy"]:
        raise C6AFinalizerError("C6A selected-policy mismatch")
    if production_decision.get("checks") != reference_decision["checks"]:
        raise C6AFinalizerError("C6A gate-check map mismatch")
    if tuple(production_decision.get("rejection_reasons", ())) != tuple(
        reference_decision["rejection_reasons"]
    ):
        raise C6AFinalizerError("C6A rejection-reason mismatch")
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "program_guard_status": authority["status"],
        "manifest_status": "PASS",
        "manifest_entry_count": int(manifest.get("entry_count", -1)),
        "cell_check_count": len(cell_checks),
        "aggregate_check_count": len(aggregate_checks),
        "weekly_row_count": sum(row["weekly_rows"] for row in cell_checks),
        "decision_row_count": sum(row["decision_rows"] for row in cell_checks),
        "cell_checks": cell_checks,
        "aggregate_checks": aggregate_checks,
        "economic_result": reference_decision["status"],
        "selected_policy": reference_decision["selected_policy"],
        "rejection_reasons": list(reference_decision["rejection_reasons"]),
        "numeric_decimal_tolerance": str(DECIMAL_TOLERANCE),
        "numeric_float_tolerance": FLOAT_TOLERANCE,
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
    parser.add_argument("--result-dir", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    source_sha = _exact_source_sha()
    config = _read_object(args.config, "C6A config")
    prepare_report = _read_object(args.prepare_report, "C6A prepare report")
    try:
        payload = finalize(
            config=config,
            prepare_report=prepare_report,
            result_dir=args.result_dir,
            source_sha=source_sha,
        )
    except C6AError as exc:
        raise C6AFinalizerError(str(exc)) from exc
    write_json_atomic(args.output, payload)
    print(
        "C6A independent finalization PASS: "
        f"{payload['economic_result']} / selected={payload['selected_policy']} / "
        "60 cells independently reconstructed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
