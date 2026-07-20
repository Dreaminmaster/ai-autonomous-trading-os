"""Corrected independent finalization core for C4A authoritative evidence."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Mapping

try:
    import scripts.c4a_evidence as evidence
    import scripts.c4a_reference_runtime as reference
except ModuleNotFoundError:  # pragma: no cover
    import c4a_evidence as evidence  # type: ignore
    import c4a_reference_runtime as reference  # type: ignore

RESULTS = evidence.RESULTS
ROOT = evidence.ROOT
FINAL_PATH = RESULTS / "final_evidence.json"
REL_TOL = 1e-10
ABS_TOL = 1e-10


class C4AFinalizerError(RuntimeError):
    pass


def compare(path: str, left: Any, right: Any) -> None:
    if isinstance(left, bool) or isinstance(right, bool):
        if left is not right:
            raise C4AFinalizerError(f"{path} boolean mismatch")
        return
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if not math.isclose(float(left), float(right), rel_tol=REL_TOL, abs_tol=ABS_TOL):
            raise C4AFinalizerError(f"{path} numeric mismatch: {left} != {right}")
        return
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            raise C4AFinalizerError(f"{path} key mismatch: {set(left) ^ set(right)}")
        for key in left:
            compare(f"{path}.{key}", left[key], right[key])
        return
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            raise C4AFinalizerError(f"{path} length mismatch: {len(left)} != {len(right)}")
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            compare(f"{path}[{index}]", a, b)
        return
    if left != right:
        raise C4AFinalizerError(f"{path} mismatch: {left!r} != {right!r}")


def policy_core(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "policy_id", "window_id", "cost_label", "starting_equity", "final_equity",
        "net_return", "maximum_drawdown", "economic_bars", "exposed_bars", "exposure_ratio",
        "scheduled_decision_count", "scheduled_active_rebalance_count", "traded_rebalance_count",
        "closed_asset_lot_count", "turnover_contributions", "annualized_one_way_turnover",
        "equity_returns", "asset_contributions", "full_week_returns", "full_week_pnl",
        "terminal_stub_net_pnl",
    )
    return {**{key: row[key] for key in keys}, "decisions": row["signals"]}


def comparator_core(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: row[key]
        for key in (
            "comparator_id", "window_id", "cost_label", "final_equity",
            "net_return", "maximum_drawdown", "equity_returns",
        )
    }


def aggregate_core(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "policy_id", "cost_label", "window_returns", "minimum_window_net_return",
        "median_window_net_return", "positive_windows", "aggregate_net_return",
        "aggregate_sharpe", "maximum_window_drawdown", "scheduled_active_rebalance_count",
        "minimum_window_active_rebalances", "closed_asset_lot_count", "exposure_ratio",
        "annualized_one_way_turnover", "asset_contributions", "positive_asset_count",
        "maximum_asset_positive_pnl_share", "maximum_window_positive_pnl_share",
        "maximum_week_positive_pnl_share", "maximum_top_three_week_positive_pnl_share",
        "full_week_returns", "full_week_pnl", "window_net_pnl", "week_and_stub_net_pnl",
    )
    result = {key: row[key] for key in keys}
    for key in (
        "weekly_mean", "weekly_std", "sr_weekly_raw", "sr_weekly_annualized",
        "skewness", "ordinary_kurtosis", "dsr_trial_policy_order", "dsr_trial_raw_sharpes",
        "sigma_sr_raw", "sr_star_raw", "dsr_radicand", "dsr_z_score",
        "within_stage_dsr_probability",
    ):
        if key in row:
            result[key] = row[key]
    return result


def decision_core(row: Mapping[str, Any]) -> dict[str, Any]:
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


def verify_manifest(payload: Mapping[str, Any], source_sha: str, merge_sha: str) -> int:
    if payload.get("stage") != "C4A":
        raise C4AFinalizerError("manifest stage mismatch")
    if payload.get("source_head_sha") != source_sha or payload.get("merge_ref_sha") != merge_sha:
        raise C4AFinalizerError("manifest exact-SHA mismatch")
    files = payload.get("files")
    if not isinstance(files, list) or int(payload.get("file_count", -1)) != len(files):
        raise C4AFinalizerError("manifest count mismatch")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, Mapping):
            raise C4AFinalizerError("manifest entry must be an object")
        relative = str(item.get("path", ""))
        if not relative or relative in seen:
            raise C4AFinalizerError("manifest empty or duplicate path")
        seen.add(relative)
        path = RESULTS / relative
        if not path.is_file() or path.stat().st_size != int(item.get("size", -1)):
            raise C4AFinalizerError(f"manifest file or size mismatch: {relative}")
        if evidence.sha256_file(path) != item.get("sha256"):
            raise C4AFinalizerError(f"manifest hash mismatch: {relative}")
    return len(files)


def verify_sources(source_sha: str) -> int:
    inventory = evidence.read_json(RESULTS / "source_inventory.json")
    snapshots = evidence.read_json(RESULTS / "source_snapshot_index.json")
    if not isinstance(inventory, Mapping) or inventory.get("status") != "PASS":
        raise C4AFinalizerError("source inventory is not PASS")
    if not isinstance(snapshots, Mapping) or snapshots.get("status") != "PASS":
        raise C4AFinalizerError("source snapshot index is not PASS")
    if inventory.get("source_head_sha") != source_sha or snapshots.get("source_head_sha") != source_sha:
        raise C4AFinalizerError("source exact-SHA mismatch")
    files = inventory.get("files")
    snapshot_rows = snapshots.get("snapshots")
    if not isinstance(files, list) or not isinstance(snapshot_rows, list) or len(files) != len(snapshot_rows):
        raise C4AFinalizerError("source/snapshot count mismatch")
    by_source = {str(item["source_path"]): item for item in snapshot_rows if isinstance(item, Mapping)}
    for item in files:
        relative = str(item["path"])
        source = ROOT / relative
        snapshot_item = by_source.get(relative)
        if snapshot_item is None:
            raise C4AFinalizerError(f"snapshot missing: {relative}")
        snapshot = RESULTS / str(snapshot_item["snapshot_path"])
        digest = str(item["sha256"])
        if not source.is_file() or not snapshot.is_file():
            raise C4AFinalizerError(f"source/snapshot file missing: {relative}")
        if evidence.sha256_file(source) != digest or evidence.sha256_file(snapshot) != digest:
            raise C4AFinalizerError(f"source/snapshot hash mismatch: {relative}")
    return len(files)


def verify_pointers() -> None:
    pointers = sorted(RESULTS.rglob(".last_result.json"))
    exports = sorted(path for path in RESULTS.rglob("result.json") if path.is_file())
    if len(pointers) != 63 or len(exports) != 63:
        raise C4AFinalizerError("expected exactly 63 pointers and 63 exports")
    referenced = set()
    for pointer in pointers:
        payload = evidence.read_json(pointer)
        result = pointer.parent / "result.json"
        if not isinstance(payload, Mapping) or payload.get("latest") != "result.json":
            raise C4AFinalizerError(f"invalid pointer: {pointer}")
        if not result.is_file() or evidence.sha256_file(result) != payload.get("sha256"):
            raise C4AFinalizerError(f"pointer hash mismatch: {pointer}")
        referenced.add(result.resolve())
    if referenced != {path.resolve() for path in exports}:
        raise C4AFinalizerError("pointer/export set mismatch")


def load_market() -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = {}
    for pair in reference.CANDIDATE_PAIRS:
        rows = evidence.read_json(RESULTS / "input_candles" / f"{pair.replace('/', '_')}_4h.json")
        if not isinstance(rows, list) or len(rows) != 2376 or any(not isinstance(row, Mapping) for row in rows):
            raise C4AFinalizerError(f"invalid retained candles for {pair}")
        output[pair] = [dict(row) for row in rows]
    return output


def main() -> int:
    source_sha = evidence.exact_sha("C4A_SOURCE_SHA")
    merge_sha = evidence.exact_sha("C4A_MERGE_REF_SHA")
    checks: list[str] = []
    errors: list[str] = []
    try:
        manifest = evidence.read_json(RESULTS / "manifest.json")
        if not isinstance(manifest, Mapping):
            raise C4AFinalizerError("manifest must be an object")
        checks.append(f"manifest_files:{verify_manifest(manifest, source_sha, merge_sha)}")
        checks.append(f"source_inventory:{verify_sources(source_sha)}")
        verify_pointers()
        checks.extend(("pointers:63", "exports:63"))

        config = evidence.read_json(RESULTS / "config.json")
        if not isinstance(config, Mapping):
            raise C4AFinalizerError("retained config must be an object")
        reference.verify_config(config)
        recomputed = reference.reference_run_screen(load_market(), config)
        checks.append("config:INDEPENDENT_VALID")

        compare(
            "candidate_universe",
            evidence.read_json(RESULTS / "candidate_universe.json"),
            recomputed["universe"]["candidates"],
        )
        compare(
            "selected_universe",
            evidence.read_json(RESULTS / "selected_universe.json"),
            recomputed["universe"]["selected_pairs"],
        )
        checks.extend(("candidate_universe:INDEPENDENT_MATCH", "selected_universe:INDEPENDENT_MATCH"))

        retained_policy = evidence.read_json(RESULTS / "policy_rows.json")
        retained_comparators = evidence.read_json(RESULTS / "comparator_rows.json")
        left_policy = {
            (row["policy_id"], row["window_id"], row["cost_label"]): policy_core(row)
            for row in retained_policy
        }
        right_policy = {
            (row["policy_id"], row["window_id"], row["cost_label"]): row
            for row in recomputed["policy_rows"]
        }
        left_comparators = {
            (row["comparator_id"], row["window_id"], row["cost_label"]): comparator_core(row)
            for row in retained_comparators
        }
        right_comparators = {
            (row["comparator_id"], row["window_id"], row["cost_label"]): row
            for row in recomputed["comparator_rows"]
        }
        compare("policy_rows", left_policy, right_policy)
        compare("comparator_rows", left_comparators, right_comparators)
        checks.extend(("policy_rows:27_INDEPENDENT_MATCH", "comparator_rows:36_INDEPENDENT_MATCH"))

        left_aggregates = {
            (row["policy_id"], row["cost_label"]): aggregate_core(row)
            for row in evidence.read_json(RESULTS / "policy_aggregates.json")
        }
        right_aggregates = {
            (row["policy_id"], row["cost_label"]): row
            for row in recomputed["policy_aggregates"]
        }
        compare("policy_aggregates", left_aggregates, right_aggregates)
        compare(
            "comparator_aggregates",
            evidence.read_json(RESULTS / "comparator_aggregates.json"),
            recomputed["comparator_aggregates"],
        )
        compare(
            "decision",
            decision_core(evidence.read_json(RESULTS / "decision.json")),
            recomputed["decision"],
        )
        checks.extend(
            (
                "policy_aggregates:9_INDEPENDENT_MATCH",
                "comparator_aggregates:12_INDEPENDENT_MATCH",
                "decision:INDEPENDENT_MATCH",
            )
        )

        summary = evidence.read_json(RESULTS / "run_summary.json")
        expected_counts = {
            "candidate_pair_count": 12,
            "selected_universe_count": 8,
            "policy_row_count": 27,
            "comparator_row_count": 36,
            "result_pointer_count": 63,
            "result_export_count": 63,
            "policy_aggregate_count": 9,
            "comparator_aggregate_count": 12,
            "weekly_schedule_count": 120,
            "weekly_signal_row_count": 960,
            "dsr_observations_per_policy": 39,
        }
        if not isinstance(summary, Mapping) or summary.get("status") != "PASS" or summary.get("errors") != []:
            raise C4AFinalizerError("run summary is not a clean PASS")
        if summary.get("source_head_sha") != source_sha or summary.get("merge_ref_sha") != merge_sha:
            raise C4AFinalizerError("run summary exact-SHA mismatch")
        for key, expected in expected_counts.items():
            if int(summary.get(key, -1)) != expected:
                raise C4AFinalizerError(f"run summary count mismatch: {key}")
        if summary.get("economic_result") != recomputed["decision"]["economic_result"]:
            raise C4AFinalizerError("run summary economic-result mismatch")
        if summary.get("selected_policy") != recomputed["decision"]["selected_policy"]:
            raise C4AFinalizerError("run summary selected-policy mismatch")
        if summary.get("confirmation_opened") is not False or summary.get("holdout_state") != "HOLDOUT_CLOSED" or summary.get("live") != "FORBIDDEN":
            raise C4AFinalizerError("run summary safety drift")
        checks.append("run_summary:PASS")
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")

    payload = {
        "schema_version": 1,
        "stage": "C4A",
        "status": "PASS" if not errors else "EVIDENCE_FAILURE",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_sha,
        "independent_reference": "scripts/c4a_reference_recompute.py + scripts/c4a_reference_runtime.py",
        "checks_passed": len(checks),
        "checks": checks,
        "errors": errors,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    evidence.write_json(FINAL_PATH, payload)
    if errors:
        raise C4AFinalizerError(errors[0])
    print(
        f"C4A final evidence PASS: {len(checks)} checks / independent reference / "
        "C4B_CLOSED / HOLDOUT_CLOSED / LIVE FORBIDDEN"
    )
    return 0
