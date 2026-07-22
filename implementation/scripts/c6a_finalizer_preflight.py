#!/usr/bin/env python3
"""Strict shape preflight before independent C6A finalization.

This checker performs no economic calculation.  It guarantees that the full
60-cell production matrix, all weekly buckets, all delta-neutral decisions,
all 12 aggregates, and the closed-state decision exist with exact counts before
the heavier independent primitive recomputation begins.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping

from atos.c6a_contract import C6AError
from atos.c6a_evidence import verify_manifest, write_json_atomic

IMPL = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = IMPL / "freqtrade_data/c6a_results"
DEFAULT_OUTPUT = IMPL / "freqtrade_data/c6a_runtime/c6a_finalizer_preflight.json"
POLICY_IDS = (
    "C6AMarketNeutralFundingCarry",
    "AlwaysOnDeltaNeutralComparator",
    "CashComparator",
    "SpotBuyAndHoldComparator",
)
COST_LABELS = ("1.0x", "1.5x", "2.0x")
WINDOW_IDS = ("W1", "W2", "W3", "W4", "W5")
DELTA_NEUTRAL = {
    "C6AMarketNeutralFundingCarry",
    "AlwaysOnDeltaNeutralComparator",
}


class C6AFinalizerPreflightError(RuntimeError):
    pass


def _read(path: Path, label: str) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C6AFinalizerPreflightError(f"unable to load {label}: {exc}") from exc
    if not isinstance(payload, Mapping):
        raise C6AFinalizerPreflightError(f"{label} must be an object")
    return payload


def preflight(result_dir: Path) -> dict[str, Any]:
    manifest = _read(result_dir / "manifest.json", "C6A manifest")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise C6AFinalizerPreflightError("C6A manifest entries missing")
    try:
        verify_manifest(result_dir, entries)
    except C6AError as exc:
        raise C6AFinalizerPreflightError(str(exc)) from exc
    cells = 0
    weekly_rows = 0
    decision_rows = 0
    event_rows = 0
    for policy in POLICY_IDS:
        for cost in COST_LABELS:
            for window in WINDOW_IDS:
                label = f"{policy}/{cost}/{window}"
                payload = _read(
                    result_dir / "cells" / policy / cost / f"{window}.json",
                    f"C6A cell {label}",
                )
                if (
                    payload.get("status") != "PASS"
                    or payload.get("policy_id") != policy
                    or payload.get("cost_label") != cost
                    or payload.get("window_id") != window
                ):
                    raise C6AFinalizerPreflightError(
                        f"C6A cell identity/status mismatch: {label}"
                    )
                weeks = payload.get("weekly_buckets")
                if not isinstance(weeks, list) or len(weeks) != 26:
                    raise C6AFinalizerPreflightError(
                        f"C6A cell must retain exactly 26 weekly rows: {label}"
                    )
                decisions = payload.get("decisions")
                expected_decisions = 26 if policy in DELTA_NEUTRAL else 0
                if not isinstance(decisions, list) or len(decisions) != expected_decisions:
                    raise C6AFinalizerPreflightError(
                        f"C6A decision-row count mismatch: {label}"
                    )
                events = payload.get("events")
                if not isinstance(events, list):
                    raise C6AFinalizerPreflightError(
                        f"C6A retained event list missing: {label}"
                    )
                if (
                    payload.get("c5b_state") != "C5B_CLOSED_AND_UNTOUCHED"
                    or payload.get("holdout_state") != "HOLDOUT_CLOSED"
                    or payload.get("paper_state") != "PAPER_CLOSED"
                    or payload.get("shadow_state") != "SHADOW_CLOSED"
                    or payload.get("live") != "FORBIDDEN"
                ):
                    raise C6AFinalizerPreflightError(
                        f"C6A cell safety-state drift: {label}"
                    )
                cells += 1
                weekly_rows += len(weeks)
                decision_rows += len(decisions)
                event_rows += len(events)
    aggregates = 0
    for policy in POLICY_IDS:
        for cost in COST_LABELS:
            payload = _read(
                result_dir / "aggregates" / policy / f"{cost}.json",
                f"C6A aggregate {policy}/{cost}",
            )
            if (
                payload.get("status") != "PASS"
                or payload.get("policy_id") != policy
                or payload.get("cost_label") != cost
            ):
                raise C6AFinalizerPreflightError(
                    f"C6A aggregate identity/status mismatch: {policy}/{cost}"
                )
            aggregates += 1
    decision = _read(result_dir / "decision.json", "C6A decision")
    if decision.get("status") not in {"SELECTED", "REJECTED"}:
        raise C6AFinalizerPreflightError("C6A decision status is invalid")
    if decision.get("status") == "REJECTED" and decision.get("selected_policy") is not None:
        raise C6AFinalizerPreflightError(
            "rejected C6A decision must retain null selected policy"
        )
    if (
        decision.get("c6b_state") != "C6B_CLOSED"
        or decision.get("c5b_state") != "C5B_CLOSED_AND_UNTOUCHED"
        or decision.get("holdout_state") != "HOLDOUT_CLOSED"
        or decision.get("paper_state") != "PAPER_CLOSED"
        or decision.get("shadow_state") != "SHADOW_CLOSED"
        or decision.get("live") != "FORBIDDEN"
    ):
        raise C6AFinalizerPreflightError("C6A decision safety-state drift")
    if cells != 60 or aggregates != 12 or weekly_rows != 1560 or decision_rows != 780:
        raise C6AFinalizerPreflightError(
            "C6A evidence shape mismatch: "
            f"cells={cells} aggregates={aggregates} weeks={weekly_rows} "
            f"decisions={decision_rows}"
        )
    return {
        "schema_version": 1,
        "stage": "C6A",
        "status": "PASS",
        "manifest_entry_count": int(manifest.get("entry_count", -1)),
        "cell_count": cells,
        "aggregate_count": aggregates,
        "weekly_row_count": weekly_rows,
        "decision_row_count": decision_rows,
        "event_row_count": event_rows,
        "economic_result": decision["status"],
        "selected_policy": decision.get("selected_policy"),
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
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    report = preflight(args.results)
    write_json_atomic(args.output, report)
    print(
        "C6A finalizer preflight PASS: 60 cells / 12 aggregates / "
        "1560 weeks / 780 decisions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
