#!/usr/bin/env python3
"""Independently recompute and finalize exact-source C2A evidence."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from atos.c2a_allocation_runtime import (
    COST_LABELS,
    PAIR_ORDER,
    POLICIES,
    aggregate_comparator,
    aggregate_policy,
    decide,
    prepare_market,
    simulate_buy_hold,
    simulate_window,
    validate_config,
)


IMPL = Path(__file__).resolve().parents[1]
RESULTS = IMPL / "freqtrade_data/backtest_results/c2a_low_turnover_allocation"
CONFIG_PATH = IMPL / "config/c2a_low_turnover_allocation.json"
FINAL_PATH = RESULTS / "final_evidence.json"
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


class C2AFinalizationError(RuntimeError):
    pass


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C2AFinalizationError(f"invalid JSON {path}: {exc}") from exc


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise C2AFinalizationError(f"unable to hash {path}: {exc}") from exc


def exact_sha(name: str) -> str:
    value = os.environ.get(name, "")
    if not SHA_RE.fullmatch(value):
        raise C2AFinalizationError(f"{name} must be an exact lowercase SHA")
    return value


def compact(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"daily", "events"}}


def require_equal(actual: Any, expected: Any, label: str, checks: list[str]) -> None:
    if actual != expected:
        raise C2AFinalizationError(f"{label} mismatch")
    checks.append(label)


def verify_manifest(checks: list[str]) -> None:
    manifest = read_json(RESULTS / "manifest.json")
    if not isinstance(manifest, Mapping):
        raise C2AFinalizationError("manifest must be an object")
    files = manifest.get("files")
    if not isinstance(files, list) or manifest.get("file_count") != len(files):
        raise C2AFinalizationError("manifest count mismatch")
    for entry in files:
        if not isinstance(entry, Mapping):
            raise C2AFinalizationError("invalid manifest entry")
        path = RESULTS / str(entry.get("path", ""))
        if not path.is_file() or entry.get("sha256") != sha256(path):
            raise C2AFinalizationError(f"manifest hash mismatch: {path}")
        checks.append(f"manifest:{entry['path']}")


def verify_pointers(checks: list[str]) -> None:
    pointers = sorted(RESULTS.rglob(".last_result.json"))
    if len(pointers) != 54:
        raise C2AFinalizationError(f"expected 54 retained pointers, found {len(pointers)}")
    for pointer in pointers:
        payload = read_json(pointer)
        if not isinstance(payload, Mapping):
            raise C2AFinalizationError(f"invalid pointer {pointer}")
        latest = payload.get("latest")
        if not isinstance(latest, str) or Path(latest).name != latest:
            raise C2AFinalizationError(f"unsafe pointer target {pointer}")
        target = pointer.parent / latest
        if not target.is_file() or payload.get("sha256") != sha256(target):
            raise C2AFinalizationError(f"pointer hash mismatch {pointer}")
        checks.append(f"pointer:{pointer.relative_to(RESULTS)}")


def load_snapshot() -> dict[str, list[dict[str, Any]]]:
    payload: dict[str, list[dict[str, Any]]] = {}
    for pair in PAIR_ORDER:
        rows = read_json(RESULTS / "input_candles" / f"{pair.replace('/', '_')}_1d.json")
        if not isinstance(rows, list) or not all(isinstance(row, Mapping) for row in rows):
            raise C2AFinalizationError(f"invalid retained candles for {pair}")
        payload[pair] = [dict(row) for row in rows]
    return payload


def main() -> int:
    source_sha = exact_sha("C2A_SOURCE_SHA")
    merge_ref_sha = exact_sha("C2A_MERGE_REF_SHA")
    checks: list[str] = []

    config = read_json(CONFIG_PATH)
    retained_config = read_json(RESULTS / "config.json")
    if not isinstance(config, Mapping) or not isinstance(retained_config, Mapping):
        raise C2AFinalizationError("config must be an object")
    validate_config(config)
    require_equal(retained_config, config, "config:retained_exact", checks)

    summary = read_json(RESULTS / "run_summary.json")
    if not isinstance(summary, Mapping):
        raise C2AFinalizationError("run summary must be an object")
    required_summary = {
        "status": "PASS",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_ref_sha,
        "economic_row_count": 27,
        "comparator_row_count": 27,
        "policy_aggregate_count": 9,
        "comparator_aggregate_count": 9,
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "errors": [],
    }
    for key, expected in required_summary.items():
        require_equal(summary.get(key), expected, f"summary:{key}", checks)

    inventory = read_json(RESULTS / "source_inventory.json")
    if not isinstance(inventory, Mapping):
        raise C2AFinalizationError("source inventory must be an object")
    require_equal(inventory.get("status"), "PASS", "inventory:status", checks)
    require_equal(inventory.get("source_head_sha"), source_sha, "inventory:source_sha", checks)
    require_equal(inventory.get("confirmation_opened"), False, "inventory:confirmation", checks)
    require_equal(inventory.get("holdout_state"), "HOLDOUT_CLOSED", "inventory:holdout", checks)
    require_equal(inventory.get("live"), "FORBIDDEN", "inventory:live", checks)

    verify_manifest(checks)
    verify_pointers(checks)

    market = prepare_market(load_snapshot())
    if market.index.max().isoformat() >= "2024-10-01T00:00:00+00:00":
        raise C2AFinalizationError("retained market crosses the C2A boundary")
    checks.append("market:boundary_closed")

    recomputed_policy = [
        simulate_window(
            market,
            policy=policy,
            window=window,
            cost_label=cost_label,
            config=config,
        )
        for policy in POLICIES
        for window in config["screen_windows"]
        for cost_label in COST_LABELS
    ]
    retained_economic = read_json(RESULTS / "economic_rows.json")
    require_equal(
        retained_economic,
        [compact(row) for row in recomputed_policy],
        "economic_rows:independent_recompute",
        checks,
    )
    if len(recomputed_policy) != 27:
        raise C2AFinalizationError("independent economic row count mismatch")

    recomputed_comparators = [
        simulate_buy_hold(
            market,
            comparator_id=comparator,
            window=window,
            cost_label=cost_label,
            config=config,
        )
        for comparator in ("cash", "btc_buy_hold", "equal_weight_buy_hold")
        for window in config["screen_windows"]
        for cost_label in COST_LABELS
    ]
    require_equal(
        read_json(RESULTS / "comparator_rows.json"),
        recomputed_comparators,
        "comparator_rows:independent_recompute",
        checks,
    )

    policy_aggregates = [
        aggregate_policy(
            recomputed_policy,
            policy=policy,
            cost_label=cost_label,
            config=config,
        )
        for policy in POLICIES
        for cost_label in COST_LABELS
    ]
    comparator_aggregates = [
        aggregate_comparator(recomputed_comparators, comparator, cost_label)
        for comparator in ("cash", "btc_buy_hold", "equal_weight_buy_hold")
        for cost_label in COST_LABELS
    ]
    require_equal(
        read_json(RESULTS / "policy_aggregates.json"),
        policy_aggregates,
        "policy_aggregates:independent_recompute",
        checks,
    )
    require_equal(
        read_json(RESULTS / "comparator_aggregates.json"),
        comparator_aggregates,
        "comparator_aggregates:independent_recompute",
        checks,
    )
    recomputed_decision = decide(policy_aggregates, comparator_aggregates, config)
    require_equal(
        read_json(RESULTS / "decision.json"),
        recomputed_decision,
        "decision:independent_recompute",
        checks,
    )
    require_equal(
        summary.get("economic_result"),
        recomputed_decision["economic_result"],
        "summary:economic_result",
        checks,
    )
    require_equal(
        summary.get("selected_policy"),
        recomputed_decision["selected_policy"],
        "summary:selected_policy",
        checks,
    )

    final = {
        "schema_version": 1,
        "stage": "C2A",
        "status": "PASS",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_ref_sha,
        "economic_result": recomputed_decision["economic_result"],
        "selected_policy": recomputed_decision["selected_policy"],
        "check_count": len(checks),
        "checks": checks,
        "errors": [],
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }
    write_json(FINAL_PATH, final)
    print(
        f"C2A final evidence PASS: {len(checks)} checks / "
        f"{final['economic_result']} / selected={final['selected_policy']} / "
        "CONFIRMATION_CLOSED / HOLDOUT_CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
