#!/usr/bin/env python3
"""Independently recompute and finalize exact-source C3A evidence."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping

from atos.c3a_residual import frame_from_rows, run_screen
from atos.profitability_diagnostics import discover_candle_file, load_candles

IMPL = Path(__file__).resolve().parents[1]
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RESULTS = IMPL / "freqtrade_data/backtest_results/c3a_residual_mean_reversion"
RUNTIME = IMPL / "freqtrade_data/c3a_runtime"
CONFIG_PATH = IMPL / "config/c3a_residual_mean_reversion.json"
BOUNDARY_PATH = RUNTIME / "c3a_data_boundary.json"
COVERAGE_PATH = RUNTIME / "c3a_data_coverage.json"
INVENTORY_PATH = RESULTS / "source_inventory.json"
FINAL_PATH = RESULTS / "final_evidence.json"
MANIFEST_PATH = RESULTS / "manifest.json"


class C3AFinalizerError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C3AFinalizerError(f"invalid JSON {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def exact_sha(name: str) -> str:
    value = os.environ.get(name, "")
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise C3AFinalizerError(f"{name} must be an exact lowercase SHA")
    return value


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def check(condition: bool, name: str, checks: list[str]) -> None:
    if not condition:
        raise C3AFinalizerError(name)
    checks.append(name)


def load_frame():
    rows = {
        pair: load_candles(discover_candle_file(DATA_DIR, pair, "4h"))
        for pair in ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    }
    return frame_from_rows(rows)


def validate_pointer(pointer: Path, checks: list[str]) -> Path:
    payload = read_json(pointer)
    check(isinstance(payload, Mapping), f"pointer object:{pointer}", checks)
    result = pointer.parent / str(payload.get("latest_result", ""))
    check(result.is_file(), f"pointer result exists:{pointer}", checks)
    check(payload.get("sha256") == sha256(result), f"pointer hash:{pointer}", checks)
    check(payload.get("status") == "PASS", f"pointer status:{pointer}", checks)
    return result


def build_manifest() -> dict[str, Any]:
    entries = []
    for path in sorted(RESULTS.rglob("*")):
        if path.is_file() and path not in {FINAL_PATH, MANIFEST_PATH}:
            entries.append(
                {
                    "path": str(path.relative_to(RESULTS)),
                    "sha256": sha256(path),
                    "size": path.stat().st_size,
                }
            )
    return {
        "schema_version": 1,
        "stage": "C3A",
        "status": "PASS",
        "file_count": len(entries),
        "entries": entries,
        "confirmation_opened": False,
        "c3b_state": "CLOSED",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def main() -> int:
    source_sha = exact_sha("C3A_SOURCE_SHA")
    merge_ref_sha = exact_sha("C3A_MERGE_REF_SHA")
    checks: list[str] = []
    errors: list[str] = []

    try:
        config = read_json(CONFIG_PATH)
        boundary = read_json(BOUNDARY_PATH)
        coverage = read_json(COVERAGE_PATH)
        inventory = read_json(INVENTORY_PATH)
        policy_rows = read_json(RESULTS / "policy_rows.json")
        comparator_rows = read_json(RESULTS / "comparator_rows.json")
        decision = read_json(RESULTS / "decision.json")
        index = read_json(RESULTS / "result_index.json")

        for name, payload in (
            ("config", config),
            ("boundary", boundary),
            ("coverage", coverage),
            ("inventory", inventory),
            ("decision", decision),
            ("index", index),
        ):
            check(isinstance(payload, Mapping), f"{name}:object", checks)

        check(config.get("stage") == "C3A", "config:stage", checks)
        check(config.get("confirmation_opened") is False, "config:confirmation_closed", checks)
        check(config.get("c3b_state") == "CLOSED", "config:c3b_closed", checks)
        check(config.get("holdout_state") == "HOLDOUT_CLOSED", "config:holdout_closed", checks)
        check(config.get("live") == "FORBIDDEN", "config:live_forbidden", checks)

        for name, payload in (("boundary", boundary), ("coverage", coverage), ("inventory", inventory)):
            check(payload.get("status") == "PASS", f"{name}:status", checks)
            check(payload.get("source_head_sha") == source_sha, f"{name}:source", checks)
            check(payload.get("confirmation_opened") is False, f"{name}:confirmation", checks)
            check(payload.get("c3b_state") == "CLOSED", f"{name}:c3b", checks)
            check(payload.get("holdout_state") == "HOLDOUT_CLOSED", f"{name}:holdout", checks)
            check(payload.get("live") == "FORBIDDEN", f"{name}:live", checks)

        check(isinstance(policy_rows, list) and len(policy_rows) == 27, "policy_rows:27", checks)
        check(
            isinstance(comparator_rows, list) and len(comparator_rows) == 36,
            "comparator_rows:36",
            checks,
        )
        check(index.get("policy_rows") == 27, "index:policy_rows", checks)
        check(index.get("comparator_rows") == 36, "index:comparator_rows", checks)
        pointers = sorted(RESULTS.rglob(".last_result.json"))
        check(len(pointers) == 63, "pointers:63", checks)
        exports = [validate_pointer(pointer, checks) for pointer in pointers]
        check(len({path.resolve() for path in exports}) == 63, "exports:63_unique", checks)

        frame = load_frame()
        recomputed_cells, recomputed_comparators, recomputed_decision = run_screen(frame)
        recomputed_rows = [cell.row() for cell in recomputed_cells]
        check(canonical(policy_rows) == canonical(recomputed_rows), "policy_rows:independent_recompute", checks)
        check(
            canonical(comparator_rows) == canonical(recomputed_comparators),
            "comparator_rows:independent_recompute",
            checks,
        )
        for key in (
            "economic_result",
            "selected_policy",
            "eligible_policy_ids",
            "policy_aggregates",
            "confirmation_opened",
            "c3b_state",
            "holdout_state",
            "live",
        ):
            check(
                canonical(decision.get(key)) == canonical(recomputed_decision.get(key)),
                f"decision:{key}:independent_recompute",
                checks,
            )

        check(decision.get("source_head_sha") == source_sha, "decision:source", checks)
        check(decision.get("merge_ref_sha") == merge_ref_sha, "decision:merge_ref", checks)
        check(decision.get("errors") == [], "decision:errors_empty", checks)
        check(decision.get("policy_row_count") == 27, "decision:policy_count", checks)
        check(decision.get("comparator_row_count") == 36, "decision:comparator_count", checks)
        check(decision.get("hidden_pointer_count") == 63, "decision:pointer_count", checks)
        check(decision.get("result_export_count") == 63, "decision:export_count", checks)
        check(decision.get("confirmation_opened") is False, "decision:confirmation_closed", checks)
        check(decision.get("c3b_state") == "CLOSED", "decision:c3b_closed", checks)
        check(decision.get("holdout_state") == "HOLDOUT_CLOSED", "decision:holdout_closed", checks)
        check(decision.get("live") == "FORBIDDEN", "decision:live_forbidden", checks)
        check(
            decision.get("economic_result") in {"SELECTED", "REJECTED"},
            "decision:economic_result",
            checks,
        )
        check(
            (decision.get("selected_policy") is None)
            == (decision.get("economic_result") == "REJECTED"),
            "decision:selected_consistency",
            checks,
        )

        check(inventory.get("path_count") == 20, "inventory:20_paths", checks)
        entries = inventory.get("entries")
        check(isinstance(entries, list) and len(entries) == 20, "inventory:20_entries", checks)
        for entry in entries:
            snapshot = RESULTS / str(entry.get("snapshot_path", ""))
            check(snapshot.is_file(), f"inventory:snapshot:{entry.get('path')}", checks)
            check(entry.get("snapshot_sha256") == sha256(snapshot), f"inventory:hash:{entry.get('path')}", checks)

        manifest = build_manifest()
        write_json(MANIFEST_PATH, manifest)
        check(manifest["file_count"] > 0, "manifest:nonempty", checks)

        final = {
            "schema_version": 1,
            "stage": "C3A",
            "status": "PASS",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "economic_result": decision["economic_result"],
            "selected_policy": decision["selected_policy"],
            "policy_row_count": 27,
            "comparator_row_count": 36,
            "hidden_pointer_count": 63,
            "result_export_count": 63,
            "source_inventory_path_count": 20,
            "manifest_file_count": manifest["file_count"],
            "check_count": len(checks),
            "checks": checks,
            "errors": [],
            "confirmation_opened": False,
            "c3b_state": "CLOSED",
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        }
        write_json(FINAL_PATH, final)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        final = {
            "schema_version": 1,
            "stage": "C3A",
            "status": "FAIL",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "check_count": len(checks),
            "checks": checks,
            "errors": errors,
            "confirmation_opened": False,
            "c3b_state": "CLOSED",
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        }
        write_json(FINAL_PATH, final)
        raise

    print(
        f"C3A finalizer PASS: {final['check_count']} checks / "
        f"{final['economic_result']} / C3B CLOSED / HOLDOUT CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
