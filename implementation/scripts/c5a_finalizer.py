#!/usr/bin/env python3
"""Independently recompute and finalize C5A evidence."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any, Mapping

try:
    import scripts.c5a_evidence as evidence
    import scripts.c5a_reference_recompute as reference
except ModuleNotFoundError:  # pragma: no cover
    import c5a_evidence as evidence  # type: ignore
    import c5a_reference_recompute as reference  # type: ignore

RESULTS = evidence.RESULTS
ROOT = evidence.ROOT
FINAL_PATH = RESULTS / "final_evidence.json"
REL_TOL = 1e-10
ABS_TOL = 1e-10


class C5AFinalizerError(RuntimeError):
    pass


def compare(path: str, left: Any, right: Any) -> None:
    if isinstance(left, bool) or isinstance(right, bool):
        if left is not right:
            raise C5AFinalizerError(f"{path} boolean mismatch")
        return
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if not math.isclose(float(left), float(right), rel_tol=REL_TOL, abs_tol=ABS_TOL):
            raise C5AFinalizerError(f"{path} numeric mismatch: {left} != {right}")
        return
    if isinstance(left, Mapping) and isinstance(right, Mapping):
        if set(left) != set(right):
            raise C5AFinalizerError(f"{path} key mismatch: {set(left) ^ set(right)}")
        for key in left:
            compare(f"{path}.{key}", left[key], right[key])
        return
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            raise C5AFinalizerError(f"{path} length mismatch")
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            compare(f"{path}[{index}]", a, b)
        return
    if left != right:
        raise C5AFinalizerError(f"{path} mismatch: {left!r} != {right!r}")


def _verify_manifest(payload: Mapping[str, Any], source_sha: str, merge_sha: str) -> int:
    if payload.get("stage") != "C5A":
        raise C5AFinalizerError("manifest stage mismatch")
    if payload.get("source_head_sha") != source_sha or payload.get("merge_ref_sha") != merge_sha:
        raise C5AFinalizerError("manifest exact-SHA mismatch")
    files = payload.get("files")
    if not isinstance(files, list) or int(payload.get("file_count", -1)) != len(files):
        raise C5AFinalizerError("manifest count mismatch")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, Mapping):
            raise C5AFinalizerError("manifest entry is not an object")
        relative = str(item.get("path", ""))
        if not relative or relative in seen:
            raise C5AFinalizerError("manifest duplicate or empty path")
        seen.add(relative)
        path = RESULTS / relative
        if not path.is_file() or path.stat().st_size != int(item.get("size", -1)):
            raise C5AFinalizerError(f"manifest file/size mismatch: {relative}")
        if evidence.sha256_file(path) != item.get("sha256"):
            raise C5AFinalizerError(f"manifest hash mismatch: {relative}")
    return len(files)


def _verify_sources(source_sha: str) -> int:
    inventory = evidence.read_json(RESULTS / "source_inventory.json")
    snapshots = evidence.read_json(RESULTS / "source_snapshot_index.json")
    if not isinstance(inventory, Mapping) or inventory.get("status") != "PASS":
        raise C5AFinalizerError("source inventory not PASS")
    if not isinstance(snapshots, Mapping) or snapshots.get("status") != "PASS":
        raise C5AFinalizerError("source snapshots not PASS")
    if inventory.get("source_head_sha") != source_sha or snapshots.get("source_head_sha") != source_sha:
        raise C5AFinalizerError("source exact-SHA mismatch")
    files = inventory.get("files")
    snapshot_rows = snapshots.get("snapshots")
    if not isinstance(files, list) or not isinstance(snapshot_rows, list) or len(files) != len(snapshot_rows):
        raise C5AFinalizerError("source/snapshot count mismatch")
    by_source = {
        str(item["source_path"]): item
        for item in snapshot_rows
        if isinstance(item, Mapping)
    }
    for item in files:
        relative = str(item["path"])
        snapshot = by_source.get(relative)
        if snapshot is None:
            raise C5AFinalizerError(f"missing source snapshot: {relative}")
        source_path = ROOT / relative
        snapshot_path = RESULTS / str(snapshot["snapshot_path"])
        digest = str(item["sha256"])
        if (
            not source_path.is_file()
            or not snapshot_path.is_file()
            or evidence.sha256_file(source_path) != digest
            or evidence.sha256_file(snapshot_path) != digest
        ):
            raise C5AFinalizerError(f"source/snapshot hash mismatch: {relative}")
    return len(files)


def _verify_pointers() -> None:
    pointers = sorted(RESULTS.rglob(".last_result.json"))
    exports = sorted(path for path in RESULTS.rglob("result.json") if path.is_file())
    if len(pointers) != 30 or len(exports) != 30:
        raise C5AFinalizerError("expected exactly 30 pointers and 30 exports")
    referenced = set()
    for pointer in pointers:
        payload = evidence.read_json(pointer)
        result = pointer.parent / "result.json"
        if not isinstance(payload, Mapping) or payload.get("latest") != "result.json":
            raise C5AFinalizerError(f"invalid pointer: {pointer}")
        if not result.is_file() or evidence.sha256_file(result) != payload.get("sha256"):
            raise C5AFinalizerError(f"pointer hash mismatch: {pointer}")
        referenced.add(result.resolve())
    if referenced != {path.resolve() for path in exports}:
        raise C5AFinalizerError("pointer/export set mismatch")


def _load_retained_datasets() -> dict[str, Any]:
    datasets: dict[str, Any] = {"spot": {}, "swap": {}, "mark": {}}
    for spot in reference.SPOT_INSTRUMENTS:
        rows = evidence.read_json(RESULTS / "input_public" / "spot" / f"{spot}.json")
        if not isinstance(rows, list) or len(rows) != 2940:
            raise C5AFinalizerError(f"invalid retained spot input: {spot}")
        datasets["spot"][spot] = rows
    for swap in reference.SWAP_INSTRUMENTS:
        for section in ("swap", "mark"):
            rows = evidence.read_json(RESULTS / "input_public" / section / f"{swap}.json")
            if not isinstance(rows, list) or len(rows) != 2940:
                raise C5AFinalizerError(f"invalid retained {section} input: {swap}")
            datasets[section][swap] = rows
    return datasets


def main() -> int:
    source_sha = evidence.exact_sha("C5A_SOURCE_SHA")
    merge_sha = evidence.exact_sha("C5A_MERGE_REF_SHA")
    checks: list[str] = []
    errors: list[str] = []
    try:
        manifest = evidence.read_json(RESULTS / "manifest.json")
        if not isinstance(manifest, Mapping):
            raise C5AFinalizerError("manifest must be an object")
        checks.append(f"initial_manifest_files:{_verify_manifest(manifest, source_sha, merge_sha)}")
        checks.append(f"source_inventory:{_verify_sources(source_sha)}")
        _verify_pointers()
        checks.extend(("pointers:30", "exports:30"))

        config = evidence.read_json(RESULTS / "config.json")
        if not isinstance(config, Mapping):
            raise C5AFinalizerError("retained config must be an object")
        datasets = _load_retained_datasets()
        recomputed = reference.reference_run_screen(datasets, config)
        compare("calibration", evidence.read_json(RESULTS / "calibration.json"), recomputed["calibration"])
        compare("policy_rows", evidence.read_json(RESULTS / "policy_rows.json"), recomputed["policy_rows"])
        compare("comparator_rows", evidence.read_json(RESULTS / "comparator_rows.json"), recomputed["comparator_rows"])
        compare("policy_aggregates", evidence.read_json(RESULTS / "policy_aggregates.json"), recomputed["policy_aggregates"])
        compare("comparator_aggregates", evidence.read_json(RESULTS / "comparator_aggregates.json"), recomputed["comparator_aggregates"])
        compare("decision", evidence.read_json(RESULTS / "decision.json"), recomputed["decision"])
        checks.extend(
            (
                "calibration:INDEPENDENT_MATCH",
                "policy_rows:12_INDEPENDENT_MATCH",
                "comparator_rows:18_INDEPENDENT_MATCH",
                "policy_aggregates:6_INDEPENDENT_MATCH",
                "comparator_aggregates:9_INDEPENDENT_MATCH",
                "decision:INDEPENDENT_MATCH",
            )
        )

        summary = evidence.read_json(RESULTS / "run_summary.json")
        if not isinstance(summary, Mapping) or summary.get("status") != "PASS" or summary.get("errors") != []:
            raise C5AFinalizerError("run summary is not a clean PASS")
        expected_counts = {
            "public_series_count": 9,
            "rows_per_public_series": 2940,
            "calibration_row_count": 117,
            "calibration_observations_per_asset_field": 39,
            "policy_row_count": 12,
            "comparator_row_count": 18,
            "result_pointer_count": 30,
            "result_export_count": 30,
            "policy_aggregate_count": 6,
            "comparator_aggregate_count": 9,
            "decision_count": 156,
            "per_asset_signal_row_count": 468,
            "weekly_bucket_count": 156,
            "weekly_psr_observations": 26,
            "selectable_candidate_count": 1,
        }
        for key, expected in expected_counts.items():
            if int(summary.get(key, -1)) != expected:
                raise C5AFinalizerError(f"run summary count mismatch: {key}")
        if summary.get("source_head_sha") != source_sha or summary.get("merge_ref_sha") != merge_sha:
            raise C5AFinalizerError("run summary exact-SHA mismatch")
        if summary.get("economic_result") != recomputed["decision"]["economic_result"]:
            raise C5AFinalizerError("run summary economic result mismatch")
        if summary.get("selected_policy") != recomputed["decision"]["selected_policy"]:
            raise C5AFinalizerError("run summary selected policy mismatch")
        if (
            summary.get("confirmation_opened") is not False
            or summary.get("holdout_state") != "HOLDOUT_CLOSED"
            or summary.get("paper_state") != "PAPER_CLOSED"
            or summary.get("shadow_state") != "SHADOW_CLOSED"
            or summary.get("live") != "FORBIDDEN"
        ):
            raise C5AFinalizerError("run summary safety-state drift")
        checks.append("run_summary:PASS")
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")

    payload = {
        "schema_version": 1,
        "stage": "C5A",
        "status": "PASS" if not errors else "EVIDENCE_FAILURE",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_sha,
        "independent_reference": "implementation/scripts/c5a_reference_recompute.py",
        "checks_passed": len(checks),
        "checks": checks,
        "errors": errors,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "paper_state": "PAPER_CLOSED",
        "shadow_state": "SHADOW_CLOSED",
        "live": "FORBIDDEN",
    }
    evidence.write_json(FINAL_PATH, payload)
    if errors:
        raise C5AFinalizerError(errors[0])
    print(f"C5A final evidence PASS: {len(checks)} independent checks")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"C5A finalizer failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
