#!/usr/bin/env python3
"""Run the frozen C6A development-only economic screen.

This runner has no downloader and no authenticated exchange path.  It consumes
only hash-bound canonical public primitives prepared by the preceding C6A
guards, executes the exact 60-cell matrix, independently replays funding and
turnover for the two delta-neutral policies, and writes a complete manifest.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping, Sequence

from atos.c6a_aggregate import AggregateResult, aggregate_window_results, decide_candidate
from atos.c6a_comparators import simulate_cash_window, simulate_spot_buy_hold_window
from atos.c6a_contract import C6AError, validate_config
from atos.c6a_evidence import (
    COST_LABELS,
    POLICY_IDS,
    WINDOW_IDS,
    build_manifest,
    manifest_payload,
    validate_decision,
    validate_result_matrix,
    write_json_atomic,
)
from atos.c6a_io import load_canonical_inputs
from atos.c6a_metrics import weekly_statistics
from atos.c6a_replay import replay_window_events, verify_window_replay
from atos.c6a_simulation import simulate_policy_window
from scripts import c6a_program_guard

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = IMPL / "config/c6a_market_neutral_funding_carry.json"
DEFAULT_PREPARE_REPORT = IMPL / "freqtrade_data/c6a_runtime/c6a_prepare_report.json"
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_results"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ZERO = Decimal("0")


class C6AScreenError(RuntimeError):
    pass


def _exact_source_sha() -> str:
    value = os.environ.get("C6A_SOURCE_SHA", os.environ.get("GITHUB_SHA", ""))
    if not SHA_RE.fullmatch(value):
        raise C6AScreenError(
            "C6A_SOURCE_SHA must be an exact lowercase 40-character SHA"
        )
    return value


def _read_object(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6AScreenError(f"unable to load {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C6AScreenError(f"{label} must be a JSON object")
    return payload


def _decision_payload(decision, *, source_sha: str) -> dict[str, Any]:
    payload = {
        "schema_version": 1,
        "stage": "C6A",
        "status": decision.status,
        "selected_policy": decision.selected_policy,
        "source_head_sha": source_sha,
        "checks": dict(decision.checks),
        "margins": {key: str(value) for key, value in decision.margins.items()},
        "rejection_reasons": list(decision.rejection_reasons),
        "confirmation_opened": False,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }
    validate_decision(payload)
    return payload


def _descriptive_aggregate(
    results: Sequence[Mapping[str, Any]], *, policy_id: str, cost_label: str
) -> dict[str, Any]:
    by_window = {str(row.get("window_id")): row for row in results}
    if set(by_window) != set(WINDOW_IDS):
        raise C6AScreenError(f"{policy_id}/{cost_label} window set mismatch")
    final = [Decimal(str(by_window[window]["final_equity"])) for window in WINDOW_IDS]
    weekly = [
        Decimal(str(bucket["weekly_return"]))
        for window in WINDOW_IDS
        for bucket in by_window[window]["weekly_buckets"]
    ]
    if len(weekly) != 130:
        raise C6AScreenError(f"{policy_id}/{cost_label} weekly count mismatch")
    try:
        statistics = asdict(weekly_statistics(weekly))
        statistics_error = None
    except C6AError as exc:
        statistics = None
        statistics_error = str(exc)
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "policy_id": policy_id,
        "cost_label": cost_label,
        "aggregate_return": str(sum(final, ZERO) / Decimal("5000") - Decimal("1")),
        "window_returns": {
            window: str(Decimal(str(by_window[window]["net_return"])))
            for window in WINDOW_IDS
        },
        "weekly_returns": [str(value) for value in weekly],
        "statistics": statistics,
        "statistics_error": statistics_error,
        "maximum_drawdown": str(
            max(Decimal(str(by_window[window]["maximum_drawdown"])) for window in WINDOW_IDS)
        ),
        "annualized_one_way_turnover": str(
            sum(
                Decimal(str(by_window[window]["annualized_one_way_turnover"]))
                for window in WINDOW_IDS
            )
            / Decimal("5")
        ),
        "selectable": False,
        "c6b_state": "C6B_CLOSED",
        "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
        "live": "FORBIDDEN",
    }


def run_screen(
    *,
    config: Mapping[str, Any],
    prepare_report: Mapping[str, Any],
    output_dir: Path,
    source_sha: str,
) -> dict[str, Any]:
    validate_config(config)
    authority = c6a_program_guard.verify_authorities(c6a_program_guard.ROOT, config)
    authority["source_head_sha"] = source_sha
    authority["verified_before_economic_read"] = True
    market, funding, metadata = load_canonical_inputs(prepare_report)

    staging = output_dir.with_name(output_dir.name + ".staging")
    if staging.exists():
        shutil.rmtree(staging)
    if output_dir.exists():
        raise C6AScreenError(f"refusing to overwrite C6A result directory: {output_dir}")
    staging.mkdir(parents=True)

    results: list[dict[str, Any]] = []
    neutral_results: dict[tuple[str, str], list[dict[str, Any]]] = {}
    neutral_replays: dict[tuple[str, str], list[Any]] = {}
    try:
        for policy_id in POLICY_IDS:
            for cost_label in COST_LABELS:
                current_results: list[dict[str, Any]] = []
                current_replays: list[Any] = []
                for window in config["windows"]:
                    if policy_id in {
                        "C6AMarketNeutralFundingCarry",
                        "AlwaysOnDeltaNeutralComparator",
                    }:
                        row = simulate_policy_window(
                            market,
                            funding,
                            metadata,
                            policy_id=policy_id,
                            window=window,
                            cost_label=cost_label,
                            config=config,
                        )
                        replay = replay_window_events(
                            events=row["events"], market=market, scored_weeks=26
                        )
                        verify_window_replay(result=row, replay=replay)
                        current_replays.append(replay)
                    elif policy_id == "CashComparator":
                        row = simulate_cash_window(
                            window=window, cost_label=cost_label, config=config
                        )
                    elif policy_id == "SpotBuyAndHoldComparator":
                        row = simulate_spot_buy_hold_window(
                            market,
                            metadata,
                            window=window,
                            cost_label=cost_label,
                            config=config,
                        )
                    else:  # pragma: no cover - POLICY_IDS is frozen
                        raise C6AScreenError(f"unknown policy: {policy_id}")
                    current_results.append(row)
                    results.append(row)
                    cell = (
                        staging
                        / "cells"
                        / policy_id
                        / cost_label
                        / f"{window['id']}.json"
                    )
                    write_json_atomic(cell, row)
                if policy_id in {
                    "C6AMarketNeutralFundingCarry",
                    "AlwaysOnDeltaNeutralComparator",
                }:
                    neutral_results[(policy_id, cost_label)] = current_results
                    neutral_replays[(policy_id, cost_label)] = current_replays

        matrix = validate_result_matrix(results)
        write_json_atomic(staging / "result_matrix.json", matrix)

        candidate_aggregates: dict[str, AggregateResult] = {}
        always_on_aggregates: dict[str, AggregateResult] = {}
        aggregates: list[dict[str, Any]] = []
        for cost_label in COST_LABELS:
            candidate = aggregate_window_results(
                neutral_results[("C6AMarketNeutralFundingCarry", cost_label)],
                neutral_replays[("C6AMarketNeutralFundingCarry", cost_label)],
            )
            always_on = aggregate_window_results(
                neutral_results[("AlwaysOnDeltaNeutralComparator", cost_label)],
                neutral_replays[("AlwaysOnDeltaNeutralComparator", cost_label)],
            )
            candidate_aggregates[cost_label] = candidate
            always_on_aggregates[cost_label] = always_on
            for aggregate in (candidate, always_on):
                payload = aggregate.to_dict()
                aggregates.append(payload)
                write_json_atomic(
                    staging
                    / "aggregates"
                    / aggregate.policy_id
                    / f"{cost_label}.json",
                    payload,
                )
            for policy_id in ("CashComparator", "SpotBuyAndHoldComparator"):
                descriptive = _descriptive_aggregate(
                    [
                        row
                        for row in results
                        if row["policy_id"] == policy_id
                        and row["cost_label"] == cost_label
                    ],
                    policy_id=policy_id,
                    cost_label=cost_label,
                )
                aggregates.append(descriptive)
                write_json_atomic(
                    staging / "aggregates" / policy_id / f"{cost_label}.json",
                    descriptive,
                )

        decision = decide_candidate(
            candidate_by_cost=candidate_aggregates,
            always_on_expected=always_on_aggregates["1.0x"],
            config=config,
        )
        decision_json = _decision_payload(decision, source_sha=source_sha)
        write_json_atomic(staging / "decision.json", decision_json)
        write_json_atomic(staging / "program_guard.json", authority)
        write_json_atomic(staging / "prepare_report.snapshot.json", prepare_report)
        summary = {
            "schema_version": 1,
            "stage": "C6A",
            "status": "PASS",
            "source_head_sha": source_sha,
            "economic_result": decision.status,
            "selected_policy": decision.selected_policy,
            "result_cell_count": len(results),
            "aggregate_count": len(aggregates),
            "weekly_bucket_count": sum(len(row["weekly_buckets"]) for row in results),
            "candidate_rejection_reasons": list(decision.rejection_reasons),
            "confirmation_opened": False,
            "c6b_state": "C6B_CLOSED",
            "c5b_state": "C5B_CLOSED_AND_UNTOUCHED",
            "holdout_state": "HOLDOUT_CLOSED",
            "paper_state": "PAPER_CLOSED",
            "shadow_state": "SHADOW_CLOSED",
            "live": "FORBIDDEN",
        }
        write_json_atomic(staging / "run_summary.json", summary)
        entries = build_manifest(staging)
        write_json_atomic(staging / "manifest.json", manifest_payload(entries))
        staging.replace(output_dir)
        return summary
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--prepare-report", type=Path, default=DEFAULT_PREPARE_REPORT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    source_sha = _exact_source_sha()
    config = _read_object(args.config, "C6A config")
    prepare_report = _read_object(args.prepare_report, "C6A prepare report")
    try:
        summary = run_screen(
            config=config,
            prepare_report=prepare_report,
            output_dir=args.output_dir,
            source_sha=source_sha,
        )
    except C6AError as exc:
        raise C6AScreenError(str(exc)) from exc
    print(
        "C6A screen complete: "
        f"{summary['economic_result']} / selected={summary['selected_policy']} / "
        "C6B remains closed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
