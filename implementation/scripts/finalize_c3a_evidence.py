#!/usr/bin/env python3
"""Independently recompute and verify retained C3A primitive evidence."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

try:  # pytest package import versus direct workflow execution.
    import scripts.c3a_reference_recompute as reference
except ModuleNotFoundError:  # pragma: no cover
    import c3a_reference_recompute as reference  # type: ignore


IMPL = Path(__file__).resolve().parents[1]
ROOT = IMPL.parent
RESULTS = IMPL / "freqtrade_data/backtest_results/c3a_residual_mean_reversion"
FINAL_PATH = RESULTS / "final_evidence.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
FLOAT_REL_TOL = 1e-10
FLOAT_ABS_TOL = 1e-12


class C3AFinalizerError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C3AFinalizerError(f"unable to hash {path}: {exc}") from exc


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C3AFinalizerError(f"invalid JSON {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    temporary.replace(path)


def exact_sha(name: str) -> str:
    value = os.environ.get(name, "")
    if not SHA_RE.fullmatch(value):
        raise C3AFinalizerError(f"{name} must be an exact lowercase 40-character SHA")
    return value


def _compare(path: str, retained: Any, recomputed: Any) -> None:
    if isinstance(retained, bool) or isinstance(recomputed, bool):
        if retained is not recomputed:
            raise C3AFinalizerError(f"retained {path} boolean mismatch")
        return
    if isinstance(retained, (int, float)) and isinstance(recomputed, (int, float)):
        left = float(retained)
        right = float(recomputed)
        if not math.isfinite(left) or not math.isfinite(right):
            if left != right:
                raise C3AFinalizerError(f"retained {path} non-finite mismatch")
        elif not math.isclose(left, right, rel_tol=FLOAT_REL_TOL, abs_tol=FLOAT_ABS_TOL):
            raise C3AFinalizerError(f"retained {path} numeric mismatch: {left} != {right}")
        return
    if isinstance(retained, Mapping) and isinstance(recomputed, Mapping):
        if set(retained) != set(recomputed):
            raise C3AFinalizerError(f"retained {path} key mismatch")
        for key in retained:
            _compare(f"{path}.{key}", retained[key], recomputed[key])
        return
    if isinstance(retained, list) and isinstance(recomputed, list):
        if len(retained) != len(recomputed):
            raise C3AFinalizerError(f"retained {path} length mismatch")
        for index, (left, right) in enumerate(zip(retained, recomputed)):
            _compare(f"{path}[{index}]", left, right)
        return
    if retained != recomputed:
        raise C3AFinalizerError(f"retained {path} mismatch")


def require_equal(label: str, retained: Any, recomputed: Any, checks: list[str]) -> None:
    _compare(label, retained, recomputed)
    checks.append(f"{label}:INDEPENDENT_MATCH")


def verify_manifest(manifest: Mapping[str, Any], source_sha: str, merge_ref_sha: str, checks: list[str]) -> None:
    if manifest.get("stage") != "C3A":
        raise C3AFinalizerError("manifest stage mismatch")
    if manifest.get("source_head_sha") != source_sha or manifest.get("merge_ref_sha") != merge_ref_sha:
        raise C3AFinalizerError("manifest exact-SHA binding mismatch")
    if manifest.get("holdout_state") != "HOLDOUT_CLOSED" or manifest.get("live") != "FORBIDDEN":
        raise C3AFinalizerError("manifest safety state drift")
    files = manifest.get("files")
    if not isinstance(files, list) or int(manifest.get("file_count", -1)) != len(files):
        raise C3AFinalizerError("manifest file count mismatch")
    indexed: set[str] = set()
    for item in files:
        if not isinstance(item, Mapping):
            raise C3AFinalizerError("manifest file entry must be an object")
        relative = str(item.get("path", ""))
        if not relative or relative in indexed:
            raise C3AFinalizerError("manifest contains empty or duplicate path")
        indexed.add(relative)
        path = RESULTS / relative
        if not path.is_file():
            raise C3AFinalizerError(f"manifest file missing: {path}")
        if path.stat().st_size != int(item.get("size", -1)):
            raise C3AFinalizerError(f"manifest size mismatch: {path}")
        if sha256_file(path) != item.get("sha256"):
            raise C3AFinalizerError(f"manifest hash mismatch: {path}")
    checks.append(f"manifest_files:{len(files)}")


def verify_source_inventory(source_sha: str, checks: list[str]) -> None:
    payload = read_json(RESULTS / "source_inventory.json")
    if not isinstance(payload, Mapping) or payload.get("status") != "PASS":
        raise C3AFinalizerError("source inventory is not PASS")
    if payload.get("source_head_sha") != source_sha:
        raise C3AFinalizerError("source inventory SHA mismatch")
    if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
        raise C3AFinalizerError("source inventory safety drift")
    files = payload.get("files")
    if not isinstance(files, list) or int(payload.get("file_count", -1)) != len(files):
        raise C3AFinalizerError("source inventory count mismatch")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, Mapping):
            raise C3AFinalizerError("source inventory entry must be an object")
        relative = str(item.get("path", ""))
        if not relative or relative in seen:
            raise C3AFinalizerError("source inventory contains empty or duplicate path")
        seen.add(relative)
        path = ROOT / relative
        if not path.is_file():
            raise C3AFinalizerError(f"inventoried source missing: {relative}")
        if path.stat().st_size != int(item.get("size", -1)):
            raise C3AFinalizerError(f"inventoried source size mismatch: {relative}")
        if sha256_file(path) != item.get("sha256"):
            raise C3AFinalizerError(f"inventoried source hash mismatch: {relative}")
    checks.append(f"source_inventory:{len(files)}")


def verify_pointers(checks: list[str]) -> None:
    pointers = sorted(RESULTS.rglob(".last_result.json"))
    exports = sorted(path for path in RESULTS.rglob("result.json") if path.is_file())
    if len(pointers) != 63 or len(exports) != 63:
        raise C3AFinalizerError("expected exactly 63 hidden pointers and 63 result exports")
    referenced: set[Path] = set()
    for pointer in pointers:
        payload = read_json(pointer)
        if not isinstance(payload, Mapping) or payload.get("latest") != "result.json":
            raise C3AFinalizerError(f"invalid result pointer: {pointer}")
        result_path = pointer.parent / "result.json"
        if not result_path.is_file() or sha256_file(result_path) != payload.get("sha256"):
            raise C3AFinalizerError(f"pointer hash mismatch: {pointer}")
        referenced.add(result_path.resolve())
    if referenced != {path.resolve() for path in exports}:
        raise C3AFinalizerError("pointer/export set mismatch")
    checks.extend(("pointers:63", "exports:63"))


def load_market() -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for pair in reference.PAIR_ORDER:
        path = RESULTS / "input_candles" / f"{pair.replace('/', '_')}_4h.json"
        payload = read_json(path)
        if not isinstance(payload, list) or not payload:
            raise C3AFinalizerError(f"invalid retained candles for {pair}")
        result[pair] = [dict(row) for row in payload if isinstance(row, Mapping)]
        if len(result[pair]) != len(payload):
            raise C3AFinalizerError(f"non-object retained candle for {pair}")
    return result


def main() -> int:
    source_sha = exact_sha("C3A_SOURCE_SHA")
    merge_ref_sha = exact_sha("C3A_MERGE_REF_SHA")
    checks: list[str] = []
    errors: list[str] = []
    try:
        manifest = read_json(RESULTS / "manifest.json")
        if not isinstance(manifest, Mapping):
            raise C3AFinalizerError("manifest must be an object")
        verify_manifest(manifest, source_sha, merge_ref_sha, checks)
        verify_source_inventory(source_sha, checks)
        verify_pointers(checks)

        config = read_json(RESULTS / "config.json")
        if not isinstance(config, Mapping):
            raise C3AFinalizerError("retained config must be an object")
        reference.verify_config(config)
        checks.append("config:INDEPENDENT_VALID")

        candles = load_market()
        market = reference.reference_prepare_market(candles)
        if max(market.timestamps) >= reference._timestamp("2024-10-01T00:00:00Z"):
            raise C3AFinalizerError("retained primitive market crosses the C3A boundary")
        checks.append("market_boundary:PASS")
        recomputed = reference.reference_run_screen(market, config)

        require_equal("policy_rows", read_json(RESULTS / "policy_rows.json"), recomputed["policy_rows"], checks)
        require_equal("comparator_rows", read_json(RESULTS / "comparator_rows.json"), recomputed["comparator_rows"], checks)
        require_equal(
            "policy_aggregates",
            read_json(RESULTS / "policy_aggregates.json"),
            recomputed["policy_aggregates"],
            checks,
        )
        require_equal(
            "comparator_aggregates",
            read_json(RESULTS / "comparator_aggregates.json"),
            recomputed["comparator_aggregates"],
            checks,
        )
        require_equal("decision", read_json(RESULTS / "decision.json"), recomputed["decision"], checks)

        summary = read_json(RESULTS / "run_summary.json")
        if not isinstance(summary, Mapping):
            raise C3AFinalizerError("run summary must be an object")
        if summary.get("source_head_sha") != source_sha or summary.get("merge_ref_sha") != merge_ref_sha:
            raise C3AFinalizerError("run summary exact-SHA mismatch")
        if summary.get("errors") != [] or summary.get("status") != "PASS":
            raise C3AFinalizerError("run summary is not a clean PASS")
        expected_counts = {
            "policy_row_count": 27,
            "comparator_row_count": 36,
            "result_pointer_count": 63,
            "result_export_count": 63,
            "policy_aggregate_count": 9,
            "comparator_aggregate_count": 12,
        }
        for key, expected in expected_counts.items():
            if int(summary.get(key, -1)) != expected:
                raise C3AFinalizerError(f"run summary count mismatch: {key}")
        if summary.get("economic_result") != recomputed["decision"]["economic_result"]:
            raise C3AFinalizerError("run summary economic decision mismatch")
        if summary.get("selected_policy") != recomputed["decision"]["selected_policy"]:
            raise C3AFinalizerError("run summary selected policy mismatch")
        if summary.get("confirmation_opened") is not False:
            raise C3AFinalizerError("C3B was opened without a separate contract")
        if summary.get("holdout_state") != "HOLDOUT_CLOSED" or summary.get("live") != "FORBIDDEN":
            raise C3AFinalizerError("run summary safety state drift")
        checks.append("run_summary:PASS")
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")

    payload = {
        "schema_version": 1,
        "stage": "C3A",
        "status": "PASS" if not errors else "EVIDENCE_FAILURE",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_ref_sha,
        "independent_reference": "scripts/c3a_reference_recompute.py",
        "checks_passed": len(checks),
        "checks": checks,
        "errors": errors,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    write_json(FINAL_PATH, payload)
    if errors:
        raise C3AFinalizerError(errors[0])
    print(
        f"C3A final evidence PASS: {len(checks)} checks / "
        "independent reference / C3B_CLOSED / HOLDOUT_CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"C3A finalizer failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
