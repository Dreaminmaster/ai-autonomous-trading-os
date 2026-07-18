#!/usr/bin/env python3
"""Independently recompute and verify retained C3A primitive evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Mapping

from atos.c3a_residual_reversion import PAIR_ORDER, prepare_market, run_screen, validate_config


IMPL = Path(__file__).resolve().parents[1]
RESULTS = IMPL / "freqtrade_data/backtest_results/c3a_residual_mean_reversion"
FINAL_PATH = RESULTS / "final_evidence.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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


def canonical(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def require_equal(label: str, retained: Any, recomputed: Any, checks: list[str]) -> None:
    if canonical(retained) != canonical(recomputed):
        raise C3AFinalizerError(f"retained {label} does not match independent recomputation")
    checks.append(f"{label}:MATCH")


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
    for item in files:
        if not isinstance(item, Mapping):
            raise C3AFinalizerError("manifest file entry must be an object")
        path = RESULTS / str(item.get("path", ""))
        if not path.is_file():
            raise C3AFinalizerError(f"manifest file missing: {path}")
        if path.stat().st_size != int(item.get("size", -1)):
            raise C3AFinalizerError(f"manifest size mismatch: {path}")
        if sha256_file(path) != item.get("sha256"):
            raise C3AFinalizerError(f"manifest hash mismatch: {path}")
    checks.append(f"manifest_files:{len(files)}")


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
    checks.append("pointers:63")
    checks.append("exports:63")


def load_market() -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for pair in PAIR_ORDER:
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
        verify_pointers(checks)

        config = read_json(RESULTS / "config.json")
        if not isinstance(config, Mapping):
            raise C3AFinalizerError("retained config must be an object")
        validate_config(config)
        checks.append("config:VALID")

        candles = load_market()
        market = prepare_market(candles)
        if market.index.max().isoformat() >= "2024-10-01T00:00:00+00:00":
            raise C3AFinalizerError("retained primitive market crosses the C3A boundary")
        checks.append("market_boundary:PASS")
        recomputed = run_screen(market, config)

        retained_policy_rows = read_json(RESULTS / "policy_rows.json")
        retained_comparator_rows = read_json(RESULTS / "comparator_rows.json")
        retained_policy_aggregates = read_json(RESULTS / "policy_aggregates.json")
        retained_comparator_aggregates = read_json(RESULTS / "comparator_aggregates.json")
        retained_decision = read_json(RESULTS / "decision.json")
        require_equal("policy_rows", retained_policy_rows, recomputed["policy_rows"], checks)
        require_equal("comparator_rows", retained_comparator_rows, recomputed["comparator_rows"], checks)
        require_equal("policy_aggregates", retained_policy_aggregates, recomputed["policy_aggregates"], checks)
        require_equal(
            "comparator_aggregates",
            retained_comparator_aggregates,
            recomputed["comparator_aggregates"],
            checks,
        )
        require_equal("decision", retained_decision, recomputed["decision"], checks)

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
        "C3B_CLOSED / HOLDOUT_CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"C3A finalizer failure: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
