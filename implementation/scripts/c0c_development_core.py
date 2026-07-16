#!/usr/bin/env python3
"""Preregistered C0C research primitives. Holdout stays closed."""
from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from atos.c0b_export import discover_authoritative_export
from atos.c0c_walk_forward import (
    parse_hyperopt_list_output,
    sha256_file,
    summarize_export,
    validate_config,
    validate_parameter_file,
    validate_recursive_analysis_log,
    equal_weight_buy_hold,
)
from atos.profitability_diagnostics import discover_candle_file, load_candles

IMPL = Path(__file__).resolve().parents[1]
os.chdir(IMPL)

CONFIG_PATH = Path("config/c0c_cost_aware_ema.json")
STRATEGY_PATH = Path("freqtrade_data/strategies/c0c_cost_aware_ema.py")
PARAM_PATH = STRATEGY_PATH.with_suffix(".json")
DATA_DIR = Path("freqtrade_data/data/okx")
RESULTS = Path("freqtrade_data/backtest_results/c0c_development")
HYPEROPT_RESULTS = Path("freqtrade_data/hyperopt_results")
RUNTIME = Path("freqtrade_data/c0c_runtime")


def timerange(start: str, end: str) -> str:
    return start.replace("-", "") + "-" + end.replace("-", "")


def log_tail(path: Path, lines: int = 100) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError as exc:
        return f"unable to read {path}: {exc}"


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def run(command: list[str], log_path: Path, command_path: Path | None = None) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "argv": command,
        "shell_escaped": shlex.join(command),
        "cwd": str(Path.cwd()),
        "started_at": datetime.now(UTC).isoformat(),
        "returncode": None,
    }
    if command_path is not None:
        _write_json(command_path, record)
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(command, stdout=handle, stderr=subprocess.STDOUT, text=True, check=False)
    record["completed_at"] = datetime.now(UTC).isoformat()
    record["returncode"] = result.returncode
    if command_path is not None:
        _write_json(command_path, record)
    if result.returncode:
        print(log_tail(log_path))
        raise SystemExit(result.returncode)


def prepare_runtime_config(pairs: list[str]) -> Path:
    source = Path("freqtrade_data/config.dryrun.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("dry_run") is not True:
        raise SystemExit("C0C requires dry_run=true")
    for key in (
        "stoploss", "minimal_roi", "trailing_stop", "trailing_stop_positive",
        "trailing_stop_positive_offset", "trailing_only_offset_is_reached",
        "use_exit_signal", "exit_profit_only", "ignore_roi_if_entry_signal",
    ):
        payload.pop(key, None)
    payload["exchange"]["pair_whitelist"] = pairs
    payload["max_open_trades"] = len(pairs)
    payload["api_server"]["enabled"] = False
    RUNTIME.mkdir(parents=True, exist_ok=True)
    destination = RUNTIME / "config.c0c.json"
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return destination


def capture_freqtrade_version() -> dict[str, Any]:
    log_path = RESULTS / "freqtrade_version.txt"
    command_path = RESULTS / "freqtrade_version.command.json"
    run(["freqtrade", "--version"], log_path, command_path)
    value = log_path.read_text(encoding="utf-8", errors="replace").strip()
    if not value or "freqtrade" not in value.lower():
        raise SystemExit("unable to prove Freqtrade version")
    return {
        "value": value,
        "path": str(log_path),
        "sha256": sha256_file(log_path),
        "command_path": str(command_path),
        "command_sha256": sha256_file(command_path),
    }


def run_startup_analysis(*, config: dict[str, Any], runtime_config: Path) -> dict[str, Any]:
    startup = config["startup_analysis"]
    pair_reports: list[dict[str, Any]] = []
    for pair in startup["pairs"]:
        slug = pair.replace("/", "_")
        log_path = RESULTS / f"recursive_analysis_{slug}.log"
        command_path = RESULTS / f"recursive_analysis_{slug}.command.json"
        command = [
            "freqtrade", "recursive-analysis",
            "--config", str(runtime_config),
            "--userdir", "freqtrade_data",
            "--datadir", str(DATA_DIR),
            "--strategy-path", "freqtrade_data/strategies",
            "--strategy", config["strategy"],
            "--pairs", pair,
            "--timeframe", config["timeframe"],
            "--timerange", startup["timerange"],
            "--startup-candle", *[str(value) for value in startup["startup_candidates"]],
            "--no-color",
        ]
        run(command, log_path, command_path)
        parsed = validate_recursive_analysis_log(
            log_path,
            startup_count=int(startup["selected_startup_candles"]),
            required_indicators=startup["required_indicators"],
            max_variance_pct=float(startup["max_variance_pct"]),
        )
        parsed["pair"] = pair
        pair_reports.append({
            "pair": pair,
            "log_path": str(log_path),
            "log_sha256": sha256_file(log_path),
            "command_path": str(command_path),
            "command_sha256": sha256_file(command_path),
            "result": parsed,
        })
    report = {
        "status": "PASS",
        "startup_candle_count": int(startup["selected_startup_candles"]),
        "max_variance_pct": float(startup["max_variance_pct"]),
        "pairs": pair_reports,
    }
    report_path = RESULTS / "recursive_analysis_report.json"
    _write_json(report_path, report)
    return {
        "report_path": str(report_path),
        "report_sha256": sha256_file(report_path),
        "result": report,
    }


def clean_hyperopt_outputs() -> None:
    PARAM_PATH.unlink(missing_ok=True)
    if HYPEROPT_RESULTS.exists():
        shutil.rmtree(HYPEROPT_RESULTS)
    HYPEROPT_RESULTS.mkdir(parents=True, exist_ok=True)


def _discover_hyperopt_result_file() -> Path:
    candidates = [
        path for path in HYPEROPT_RESULTS.iterdir()
        if path.is_file()
        and path.name != "last_result.json"
        and not path.name.endswith(".lock")
        and path.suffix.lower() in {".fthypt", ".pickle", ".pkl"}
    ]
    if len(candidates) != 1:
        raise SystemExit(f"expected one authoritative hyperopt result file, found {[p.name for p in candidates]}")
    return candidates[0]


def _safe_slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    if not result:
        raise SystemExit("candidate id produced empty path slug")
    return result


def run_hyperopt(
    *, fold: dict[str, Any], config: dict[str, Any], runtime_config: Path, fold_dir: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    clean_hyperopt_outputs()
    hyper = config["hyperopt"]
    log_path = fold_dir / "hyperopt.log"
    command_path = fold_dir / "hyperopt.command.json"
    command = [
        "freqtrade", "hyperopt",
        "--config", str(runtime_config),
        "--userdir", "freqtrade_data",
        "--datadir", str(DATA_DIR),
        "--strategy-path", "freqtrade_data/strategies",
        "--strategy", config["strategy"],
        "--pairs", *config["pairs"],
        "--timeframe", config["timeframe"],
        "--timerange", timerange(fold["train_start"], fold["train_end"]),
        "--fee", str(hyper["fee_rate"]),
        "--spaces", hyper["space"],
        "--epochs", str(hyper["epochs"]),
        "--random-state", str(hyper["random_state"]),
        "--min-trades", str(hyper["min_trades"]),
        "--hyperopt-loss", hyper["loss"],
        "--job-workers", str(hyper["workers"]),
        "--disable-param-export",
        "--no-color",
    ]
    run(command, log_path, command_path)
    result_file = _discover_hyperopt_result_file()

    list_log = fold_dir / "hyperopt_list.jsonl"
    list_command = fold_dir / "hyperopt_list.command.json"
    run([
        "freqtrade", "hyperopt-list",
        "--config", str(runtime_config),
        "--userdir", "freqtrade_data",
        "--hyperopt-filename", result_file.name,
        "--min-trades", str(hyper["min_trades"]),
        "--print-json", "--no-details", "--no-color",
    ], list_log, list_command)
    shortlist = parse_hyperopt_list_output(list_log, int(hyper["shortlist_size"]))

    shortlist_dir = fold_dir / "shortlist"
    shortlist_dir.mkdir()
    candidates: list[dict[str, Any]] = []
    for rank, item in enumerate(shortlist, start=1):
        epoch = int(item["epoch"])
        candidate_id = f"rank_{rank:02d}_epoch_{epoch}"
        show_log = shortlist_dir / f"{candidate_id}.hyperopt_show.json"
        show_command = shortlist_dir / f"{candidate_id}.hyperopt_show.command.json"
        PARAM_PATH.unlink(missing_ok=True)
        run([
            "freqtrade", "hyperopt-show",
            "--config", str(runtime_config),
            "--userdir", "freqtrade_data",
            "--hyperopt-filename", result_file.name,
            "--index", str(epoch),
            "--print-json", "--no-header", "--no-color",
        ], show_log, show_command)
        if not PARAM_PATH.is_file():
            raise SystemExit(f"hyperopt-show epoch {epoch} did not export {PARAM_PATH}")
        validate_parameter_file(PARAM_PATH)
        params_copy = shortlist_dir / f"{candidate_id}.params.json"
        shutil.copy2(PARAM_PATH, params_copy)
        candidates.append({
            "candidate_id": candidate_id,
            "rank": rank,
            "training_epoch": epoch,
            "training_loss": float(item["loss"]),
            "params_path": params_copy,
            "params_sha256": sha256_file(params_copy),
            "show_log_path": str(show_log),
            "show_log_sha256": sha256_file(show_log),
            "show_command_path": str(show_command),
            "show_command_sha256": sha256_file(show_command),
        })

    hyper_copy = fold_dir / "hyperopt_results"
    shutil.copytree(HYPEROPT_RESULTS, hyper_copy)
    official_files = [
        {"path": str(path), "sha256": sha256_file(path)}
        for path in sorted(hyper_copy.rglob("*")) if path.is_file()
    ]
    shortlist_path = fold_dir / "shortlist.json"
    _write_json(shortlist_path, [
        {key: (str(value) if isinstance(value, Path) else value) for key, value in item.items()}
        for item in candidates
    ])
    evidence = {
        "fold_id": fold["id"],
        "hyperopt_log": str(log_path),
        "hyperopt_log_sha256": sha256_file(log_path),
        "hyperopt_command": str(command_path),
        "hyperopt_command_sha256": sha256_file(command_path),
        "hyperopt_list_output": str(list_log),
        "hyperopt_list_output_sha256": sha256_file(list_log),
        "hyperopt_list_command": str(list_command),
        "hyperopt_list_command_sha256": sha256_file(list_command),
        "shortlist": str(shortlist_path),
        "shortlist_sha256": sha256_file(shortlist_path),
        "official_hyperopt_result_files": official_files,
    }
    return candidates, evidence


def run_backtest(
    *, fold_id: str, role: str, start: str, end: str, multiplier: float,
    config: dict[str, Any], runtime_config: Path, fold_dir: Path, candidate: dict[str, Any],
) -> dict[str, Any]:
    params_copy = Path(candidate["params_path"])
    shutil.copy2(params_copy, PARAM_PATH)
    label = str(multiplier).replace(".", "_")
    candidate_slug = _safe_slug(str(candidate["candidate_id"]))
    cell_dir = fold_dir / role / candidate_slug / label
    cell_dir.mkdir(parents=True, exist_ok=False)
    log_path = cell_dir / "backtest.log"
    command_path = cell_dir / "backtest.command.json"
    command = [
        "freqtrade", "backtesting",
        "--config", str(runtime_config),
        "--userdir", "freqtrade_data",
        "--datadir", str(DATA_DIR),
        "--strategy-path", "freqtrade_data/strategies",
        "--strategy", config["strategy"],
        "--pairs", *config["pairs"],
        "--timeframe", config["timeframe"],
        "--timerange", timerange(start, end),
        "--fee", str(config["expected_fee_rate"] * multiplier),
        "--cache", "none",
        "--export", "trades",
        "--backtest-directory", str(cell_dir),
    ]
    run(command, log_path, command_path)
    export = discover_authoritative_export(cell_dir, [config["strategy"]])
    row = summarize_export(
        export_path=export,
        params_path=params_copy,
        fold_id=fold_id,
        role=role,
        cost_multiplier=multiplier,
        expected_pairs=config["pairs"],
        candidate_id=str(candidate["candidate_id"]),
        training_epoch=int(candidate["training_epoch"]),
        training_loss=float(candidate["training_loss"]),
    )
    row["log_path"] = str(log_path)
    row["log_sha256"] = sha256_file(log_path)
    row["command_path"] = str(command_path)
    row["command_sha256"] = sha256_file(command_path)
    return row


def fold_buy_hold(*, start: str, end: str, pairs: list[str], timeframe: str) -> dict[str, Any]:
    candles_by_pair: dict[str, list[dict[str, Any]]] = {}
    start_ts = pd.Timestamp(start, tz="UTC")
    end_ts = pd.Timestamp(end, tz="UTC")
    for pair in pairs:
        path = discover_candle_file(DATA_DIR, pair, timeframe)
        candles = load_candles(path)
        selected = []
        for row in candles:
            when = pd.Timestamp(row["date"])
            when = when.tz_localize("UTC") if when.tzinfo is None else when.tz_convert("UTC")
            if start_ts <= when < end_ts:
                selected.append(row)
        if len(selected) < 2:
            raise SystemExit(f"insufficient buy-and-hold candles for {pair} {start} {end}")
        candles_by_pair[pair] = selected
    return equal_weight_buy_hold(candles_by_pair)


def main() -> int:
    """Never bypass the gated orchestrator when this helper is invoked directly."""
    from atos.c0c_validation_gate import run_gated_development
    import sys
    return run_gated_development(sys.modules[__name__])


if __name__ == "__main__":
    raise SystemExit(main())