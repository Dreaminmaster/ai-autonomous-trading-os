#!/usr/bin/env python3
"""Verify postprocessed C4A universe and full rebalance-ledger evidence."""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

try:
    import scripts.c4a_evidence as evidence
    import scripts.c4a_evidence_postprocess as postprocess
    import scripts.c4a_finalizer_core as core
    import scripts.c4a_reference_runtime as reference
except ModuleNotFoundError:  # pragma: no cover
    import c4a_evidence as evidence  # type: ignore
    import c4a_evidence_postprocess as postprocess  # type: ignore
    import c4a_finalizer_core as core  # type: ignore
    import c4a_reference_runtime as reference  # type: ignore

RESULTS = evidence.RESULTS
FINAL_PATH = RESULTS / "final_evidence.json"


class C4AFinalizerExtensionError(RuntimeError):
    pass


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _load_market() -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for pair in reference.CANDIDATE_PAIRS:
        rows = evidence.read_json(
            RESULTS / "input_candles" / f"{pair.replace('/', '_')}_4h.json"
        )
        if not isinstance(rows, list) or len(rows) != 2376:
            raise C4AFinalizerExtensionError(f"invalid retained candles for {pair}")
        if any(not isinstance(row, Mapping) for row in rows):
            raise C4AFinalizerExtensionError(f"non-object retained candle for {pair}")
        output[pair] = [dict(row) for row in rows]
    return output


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return postprocess.load_jsonl(path)


def verify_universe(recomputed: Mapping[str, Any]) -> list[str]:
    expected_candidates = [
        {**dict(row), "formation_row_count": 732}
        for row in recomputed["universe"]["candidates"]
    ]
    expected_selected = [row for row in expected_candidates if row["selected"] is True]
    retained_candidates = evidence.read_json(RESULTS / "candidate_universe.json")
    retained_selected = evidence.read_json(RESULTS / "selected_universe.json")
    core.compare("postprocessed_candidate_universe", retained_candidates, expected_candidates)
    core.compare("postprocessed_selected_universe", retained_selected, expected_selected)
    hashes = evidence.read_json(RESULTS / "universe_hashes.json")
    if not isinstance(hashes, Mapping):
        raise C4AFinalizerExtensionError("universe hashes must be an object")
    expected_hashes = {
        "candidate_count": 12,
        "selected_count": 8,
        "candidate_universe_canonical_sha256": postprocess.canonical_sha256(expected_candidates),
        "selected_universe_canonical_sha256": postprocess.canonical_sha256(expected_selected),
    }
    for key, expected in expected_hashes.items():
        if hashes.get(key) != expected:
            raise C4AFinalizerExtensionError(f"universe hash mismatch: {key}")
    if hashes.get("stage") != "C4A" or hashes.get("holdout_state") != "HOLDOUT_CLOSED" or hashes.get("live") != "FORBIDDEN":
        raise C4AFinalizerExtensionError("universe hash safety-state drift")
    return [
        "candidate_universe_rows:12_INDEPENDENT_MATCH",
        "selected_universe_rows:8_INDEPENDENT_MATCH",
        "universe_canonical_hashes:INDEPENDENT_MATCH",
    ]


def verify_rebalance_ledger(
    recomputed: Mapping[str, Any],
    market: reference.ReferenceMarket,
    config: Mapping[str, Any],
) -> tuple[int, list[str]]:
    ledger = _load_jsonl(RESULTS / "rebalance_ledger.jsonl")
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in ledger:
        key = (str(row["policy_id"]), str(row["window_id"]), str(row["cost_label"]))
        groups[key].append(row)
    reference_rows = {
        (str(row["policy_id"]), str(row["window_id"]), str(row["cost_label"])): row
        for row in recomputed["policy_rows"]
    }
    if set(groups) != set(reference_rows) or len(groups) != 27:
        raise C4AFinalizerExtensionError("rebalance-ledger cell set mismatch")
    timestamp_index = {stamp.isoformat(): index for index, stamp in enumerate(market.timestamps)}
    selected_pairs = [str(pair) for pair in recomputed["universe"]["selected_pairs"]]
    verified_entries = 0
    for key, reference_row in reference_rows.items():
        entries = sorted(groups[key], key=lambda item: int(item["cell_sequence"]))
        if [int(item["cell_sequence"]) for item in entries] != list(range(len(entries))):
            raise C4AFinalizerExtensionError(f"ledger sequence mismatch: {key}")
        decisions = {
            str(item["execution_time"]): item
            for item in reference_row["decisions"]
        }
        quantities = {pair: 0.0 for pair in selected_pairs}
        cash = float(config["starting_equity"])
        decision_times_seen: set[str] = set()
        for entry in entries:
            timestamp = _timestamp(str(entry["time"]))
            index = timestamp_index.get(timestamp.isoformat())
            if index is None:
                raise C4AFinalizerExtensionError(f"ledger timestamp absent from market: {timestamp}")
            kind = str(entry["kind"])
            price_field = "close" if kind == "TERMINAL_LIQUIDATION" else "open"
            if entry.get("price_field") != price_field:
                raise C4AFinalizerExtensionError(f"ledger price-field mismatch: {key}")
            prices = {
                pair: float(
                    market.closes[pair][index]
                    if price_field == "close"
                    else market.opens[pair][index]
                )
                for pair in selected_pairs
            }
            current_values = {pair: quantities[pair] * prices[pair] for pair in selected_pairs}
            equity_before = cash + sum(current_values.values())
            if kind == "TERMINAL_LIQUIDATION":
                target_weights: dict[str, float] = {}
            else:
                decision = decisions.get(timestamp.isoformat())
                if decision is None:
                    raise C4AFinalizerExtensionError(f"ledger decision missing in reference: {key}/{timestamp}")
                target_weights = {
                    str(pair): float(weight)
                    for pair, weight in decision["target_weights"].items()
                }
                decision_times_seen.add(timestamp.isoformat())
            solved = reference.reference_solve_post_cost(
                equity_before,
                current_values,
                target_weights,
                float(config["cost_rates"][key[2]]),
            )
            quantities_after = {
                pair: solved["target_values"][pair] / prices[pair]
                if solved["target_values"][pair] > 0
                else 0.0
                for pair in selected_pairs
            }
            expected = {
                "fee_rate": float(config["cost_rates"][key[2]]),
                "prices": prices,
                "quantities_before": quantities,
                "current_values": current_values,
                "target_weights": target_weights,
                "target_values": solved["target_values"],
                "trade_deltas": solved["trade_deltas"],
                "fees": solved["fees"],
                "total_fee": solved["total_fee"],
                "equity_before": equity_before,
                "equity_after": solved["equity_after"],
                "cash_after": solved["cash"],
                "quantities_after": quantities_after,
                "solver_residual": equity_before - solved["total_fee"] - solved["equity_after"],
            }
            for field, expected_value in expected.items():
                core.compare(f"rebalance_ledger.{key}.{entry['cell_sequence']}.{field}", entry[field], expected_value)
            if kind == "TERMINAL_LIQUIDATION":
                if entry.get("solver_iterations") is not None:
                    core.compare(
                        f"rebalance_ledger.{key}.{entry['cell_sequence']}.solver_iterations",
                        int(entry["solver_iterations"]),
                        int(solved["iterations"]),
                    )
            else:
                core.compare(
                    f"rebalance_ledger.{key}.{entry['cell_sequence']}.solver_iterations",
                    int(entry["solver_iterations"]),
                    int(solved["iterations"]),
                )
            if entry.get("confirmation_opened") is not False or entry.get("holdout_state") != "HOLDOUT_CLOSED" or entry.get("live") != "FORBIDDEN":
                raise C4AFinalizerExtensionError(f"ledger safety-state drift: {key}")
            cash = float(solved["cash"])
            quantities = quantities_after
            verified_entries += 1
        if decision_times_seen != set(decisions):
            raise C4AFinalizerExtensionError(f"ledger omits scheduled decisions: {key}")
        if any(value != 0.0 for value in quantities.values()):
            raise C4AFinalizerExtensionError(f"ledger cell does not finish in cash: {key}")
    return verified_entries, [
        "rebalance_ledger_cells:27_INDEPENDENT_MATCH",
        f"rebalance_ledger_entries:{verified_entries}_INDEPENDENT_MATCH",
        "rebalance_ledger_post_cost_roots:INDEPENDENT_MATCH",
    ]


def main() -> int:
    source_sha = evidence.exact_sha("C4A_SOURCE_SHA")
    merge_ref_sha = evidence.exact_sha("C4A_MERGE_REF_SHA")
    final = evidence.read_json(FINAL_PATH)
    errors: list[str] = []
    extension_checks: list[str] = []
    try:
        if not isinstance(final, dict) or final.get("status") != "PASS" or final.get("errors") != []:
            raise C4AFinalizerExtensionError("base independent final evidence is not PASS")
        if final.get("source_head_sha") != source_sha or final.get("merge_ref_sha") != merge_ref_sha:
            raise C4AFinalizerExtensionError("base final evidence exact-SHA mismatch")
        config = evidence.read_json(RESULTS / "config.json")
        if not isinstance(config, Mapping):
            raise C4AFinalizerExtensionError("retained config must be an object")
        candles = _load_market()
        market = reference.reference_prepare_market(candles)
        recomputed = reference.reference_run_screen(candles, config)
        extension_checks.extend(verify_universe(recomputed))
        ledger_count, ledger_checks = verify_rebalance_ledger(recomputed, market, config)
        extension_checks.extend(ledger_checks)
        summary = evidence.read_json(RESULTS / "run_summary.json")
        if not isinstance(summary, Mapping):
            raise C4AFinalizerExtensionError("run summary must be an object")
        if summary.get("evidence_postprocess_status") != "PASS" or summary.get("universe_hashes_present") is not True:
            raise C4AFinalizerExtensionError("run summary postprocess state mismatch")
        if int(summary.get("rebalance_ledger_entry_count", -1)) != ledger_count:
            raise C4AFinalizerExtensionError("run summary ledger count mismatch")
        extension_checks.append("run_summary_postprocess:PASS")
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")

    if not isinstance(final, dict):
        final = {}
    base_checks = list(final.get("checks", []))
    final.update(
        {
            "schema_version": 1,
            "stage": "C4A",
            "status": "PASS" if not errors else "EVIDENCE_FAILURE",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "checks": base_checks + extension_checks,
            "checks_passed": len(base_checks) + len(extension_checks),
            "postprocess_extension_checks": extension_checks,
            "errors": errors,
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        }
    )
    evidence.write_json(FINAL_PATH, final)
    if errors:
        raise C4AFinalizerExtensionError(errors[0])
    print(
        f"C4A finalizer extensions PASS: {len(extension_checks)} checks / "
        "universe hashes / full rebalance ledger"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"C4A finalizer extension failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
