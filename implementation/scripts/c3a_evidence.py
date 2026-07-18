#!/usr/bin/env python3
"""Generate the preregistered C3A residual mean-reversion evidence package."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from atos.c3a_residual import CellResult, frame_from_rows, run_screen
from atos.profitability_diagnostics import discover_candle_file, load_candles

IMPL = Path(__file__).resolve().parents[1]
CONFIG_PATH = IMPL / "config/c3a_residual_mean_reversion.json"
DATA_DIR = IMPL / "freqtrade_data/data/okx"
RUNTIME = IMPL / "freqtrade_data/c3a_runtime"
RESULTS = IMPL / "freqtrade_data/backtest_results/c3a_residual_mean_reversion"
BOUNDARY_PATH = RUNTIME / "c3a_data_boundary.json"
COVERAGE_PATH = RUNTIME / "c3a_data_coverage.json"


class C3AEvidenceError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C3AEvidenceError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise C3AEvidenceError(f"expected object in {path}")
    return payload


def exact_sha(name: str) -> str:
    value = os.environ.get(name, "")
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value):
        raise C3AEvidenceError(f"{name} must be an exact lowercase SHA")
    return value


def validate_prerequisites(source_sha: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    config = read_json(CONFIG_PATH)
    boundary = read_json(BOUNDARY_PATH)
    coverage = read_json(COVERAGE_PATH)
    if config.get("stage") != "C3A":
        raise C3AEvidenceError("stage drift")
    if config.get("confirmation_opened") is not False or config.get("c3b_state") != "CLOSED":
        raise C3AEvidenceError("confirmation state drift")
    if config.get("holdout_state") != "HOLDOUT_CLOSED" or config.get("live") != "FORBIDDEN":
        raise C3AEvidenceError("safety state drift")
    for name, payload in (("boundary", boundary), ("coverage", coverage)):
        if payload.get("status") != "PASS" or payload.get("source_head_sha") != source_sha:
            raise C3AEvidenceError(f"{name} status or source mismatch")
        if payload.get("confirmation_opened") is not False or payload.get("c3b_state") != "CLOSED":
            raise C3AEvidenceError(f"{name} confirmation drift")
        if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
            raise C3AEvidenceError(f"{name} safety drift")
    if coverage.get("aligned_timestamp_count", 0) <= 0:
        raise C3AEvidenceError("missing aligned coverage")
    return config, boundary, coverage


def load_frame():
    rows = {
        pair: load_candles(discover_candle_file(DATA_DIR, pair, "4h"))
        for pair in ("BTC/USDT", "ETH/USDT", "SOL/USDT")
    }
    return frame_from_rows(rows)


def retain_result(directory: Path, payload: Mapping[str, Any]) -> tuple[Path, Path]:
    directory.mkdir(parents=True, exist_ok=True)
    result = directory / "result.json"
    write_json(result, dict(payload))
    pointer = directory / ".last_result.json"
    write_json(
        pointer,
        {
            "latest_result": result.name,
            "sha256": sha256(result),
            "status": "PASS",
        },
    )
    return result, pointer


def cell_payload(cell: CellResult, source_sha: str, merge_ref_sha: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "stage": "C3A",
        "kind": "policy",
        "source_head_sha": source_sha,
        "merge_ref_sha": merge_ref_sha,
        "row": cell.row(),
        "trades": [trade.to_dict() for trade in cell.trades],
        "equity": list(cell.equity),
        "returns": list(cell.returns),
        "turnover_contributions": list(cell.turnover_contributions),
        "confirmation_opened": False,
        "c3b_state": "CLOSED",
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
        "status": "PASS",
    }


def main() -> int:
    source_sha = exact_sha("C3A_SOURCE_SHA")
    merge_ref_sha = exact_sha("C3A_MERGE_REF_SHA")
    config, boundary, coverage = validate_prerequisites(source_sha)
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    RESULTS.mkdir(parents=True, exist_ok=True)
    frame = load_frame()
    cells, comparators, decision = run_screen(frame)
    policy_rows = [cell.row() for cell in cells]
    if len(policy_rows) != 27:
        raise C3AEvidenceError("C3A must retain exactly 27 policy rows")
    if len(comparators) != 36:
        raise C3AEvidenceError("C3A must retain exactly 36 comparator rows")

    pointers: list[str] = []
    exports: list[str] = []
    trade_ledgers: dict[str, Any] = {}
    equity_series: dict[str, Any] = {}

    for cell in cells:
        key = f"{cell.policy_id}/{cell.window_id}/{cell.cost_label}"
        directory = RESULTS / "policy" / cell.policy_id / cell.window_id / cell.cost_label
        result, pointer = retain_result(directory, cell_payload(cell, source_sha, merge_ref_sha))
        exports.append(str(result.relative_to(RESULTS)))
        pointers.append(str(pointer.relative_to(RESULTS)))
        trade_ledgers[key] = [trade.to_dict() for trade in cell.trades]
        equity_series[key] = list(cell.equity)

    for row in comparators:
        key = f"{row['comparator_id']}/{row['window_id']}/{row['cost_label']}"
        directory = (
            RESULTS
            / "comparator"
            / str(row["comparator_id"])
            / str(row["window_id"])
            / str(row["cost_label"])
        )
        payload = {
            "schema_version": 1,
            "stage": "C3A",
            "kind": "comparator",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "row": row,
            "confirmation_opened": False,
            "c3b_state": "CLOSED",
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
            "status": "PASS",
        }
        result, pointer = retain_result(directory, payload)
        exports.append(str(result.relative_to(RESULTS)))
        pointers.append(str(pointer.relative_to(RESULTS)))
        trade_ledgers[key] = []
        equity_series[key] = []

    if len(pointers) != 63 or len(exports) != 63:
        raise C3AEvidenceError("C3A must retain exactly 63 pointers and exports")

    decision.update(
        {
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "policy_row_count": len(policy_rows),
            "comparator_row_count": len(comparators),
            "hidden_pointer_count": len(pointers),
            "result_export_count": len(exports),
            "boundary_sha256": sha256(BOUNDARY_PATH),
            "coverage_sha256": sha256(COVERAGE_PATH),
            "config_sha256": sha256(CONFIG_PATH),
            "errors": [],
        }
    )
    write_json(RESULTS / "policy_rows.json", policy_rows)
    write_json(RESULTS / "comparator_rows.json", comparators)
    write_json(RESULTS / "trade_ledgers.json", trade_ledgers)
    write_json(RESULTS / "equity_series.json", equity_series)
    write_json(RESULTS / "decision.json", decision)
    write_json(
        RESULTS / "result_index.json",
        {
            "schema_version": 1,
            "stage": "C3A",
            "source_head_sha": source_sha,
            "merge_ref_sha": merge_ref_sha,
            "policy_rows": len(policy_rows),
            "comparator_rows": len(comparators),
            "pointers": sorted(pointers),
            "exports": sorted(exports),
            "confirmation_opened": False,
            "c3b_state": "CLOSED",
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
            "status": "PASS",
        },
    )
    shutil.copy2(CONFIG_PATH, RESULTS / "c3a_residual_mean_reversion.json")
    shutil.copy2(BOUNDARY_PATH, RESULTS / "c3a_data_boundary.json")
    shutil.copy2(COVERAGE_PATH, RESULTS / "c3a_data_coverage.json")
    print(
        f"C3A evidence PASS: {len(policy_rows)} policy rows / "
        f"{len(comparators)} comparator rows / {len(pointers)} pointers / "
        f"{decision['economic_result']} / C3B CLOSED / HOLDOUT CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
