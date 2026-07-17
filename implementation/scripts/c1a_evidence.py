#!/usr/bin/env python3
"""Run the preregistered C1A historical family screen. LIVE remains forbidden."""
from __future__ import annotations

import hashlib
import json
import math
import os
import shlex
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from atos.c0b_export import discover_authoritative_export
from atos.c1a_family_screen import evaluate_screen, validate_config
from atos.profitability_diagnostics import (
    ProfitabilityDiagnosticsError,
    buy_and_hold_metrics,
    discover_candle_file,
    extract_trades,
    load_candles,
    load_freqtrade_export,
    select_strategy_payload,
)
from run_c0c_development import validate_recursive_analysis_log


IMPL = Path(__file__).resolve().parents[1]
os.chdir(IMPL)
CONFIG_PATH = Path("config/c1a_strategy_family_screen.json")
STRATEGY_PATH = Path("freqtrade_data/strategies/c1a_common.py")
DATA_DIR = Path("freqtrade_data/data/okx")
RUNTIME = Path("freqtrade_data/c1a_runtime")
RESULTS = Path("freqtrade_data/backtest_results/c1a_family_screen")
BOUNDARY_PATH = RUNTIME / "c1a_data_boundary.json"
COVERAGE_PATH = RUNTIME / "c1a_data_coverage.json"
REPORT_JSON = RESULTS / "c1a_family_screen_report.json"
REPORT_MD = RESULTS / "c1a_family_screen_report.md"
MANIFEST_PATH = RESULTS / "c1a_family_screen_manifest.json"


class C1AEvidenceError(RuntimeError):
    """Raised when C1A execution or retained evidence is incomplete."""


def sha256_file(path: str | Path) -> str:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError as exc:
        raise C1AEvidenceError(f"unreadable file {path}: {exc}") from exc


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise C1AEvidenceError(f"invalid {label}: {exc}") from exc
    if not isinstance(payload, dict):
        raise C1AEvidenceError(f"{label} must contain an object")
    return payload


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise C1AEvidenceError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise C1AEvidenceError(f"{label} must be finite")
    return result


def _timestamp(value: Any, label: str) -> datetime:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value) / (1000 if float(value) > 10_000_000_000 else 1)
        return datetime.fromtimestamp(seconds, tz=UTC)
    if not isinstance(value, str) or not value.strip():
        raise C1AEvidenceError(f"{label} must be a timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise C1AEvidenceError(f"{label} invalid timestamp") from exc
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _timerange(start: str, end: str) -> str:
    return start.replace("-", "") + "-" + end.replace("-", "")


def _slug(value: str) -> str:
    result = "".join(char if char.isalnum() or char in "_.-" else "_" for char in value)
    result = result.strip("_")
    if not result:
        raise C1AEvidenceError("empty path slug")
    return result


def _log_tail(path: Path, lines: int = 120) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError as exc:
        return f"unable to read {path}: {exc}"


def run(command: list[str], log_path: Path, command_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "argv": command,
        "shell_escaped": shlex.join(command),
        "cwd": str(Path.cwd()),
        "started_at": datetime.now(UTC).isoformat(),
        "returncode": None,
    }
    _write_json(command_path, record)
    with log_path.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            command,
            stdout=handle,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
    record["completed_at"] = datetime.now(UTC).isoformat()
    record["returncode"] = result.returncode
    _write_json(command_path, record)
    if result.returncode:
        print(_log_tail(log_path))
        raise C1AEvidenceError(
            f"command failed with exit code {result.returncode}: {shlex.join(command)}"
        )


def prepare_runtime_config(config: Mapping[str, Any]) -> Path:
    payload = _read_json(Path("freqtrade_data/config.dryrun.json"), "Freqtrade dry-run config")
    if payload.get("dry_run") is not True or payload.get("trading_mode") != "spot":
        raise C1AEvidenceError("C1A requires spot dry-run configuration")
    for key in (
        "stoploss",
        "minimal_roi",
        "trailing_stop",
        "trailing_stop_positive",
        "trailing_stop_positive_offset",
        "trailing_only_offset_is_reached",
        "use_exit_signal",
        "exit_profit_only",
        "ignore_roi_if_entry_signal",
    ):
        payload.pop(key, None)
    payload["exchange"]["pair_whitelist"] = list(config["pairs"])
    payload["max_open_trades"] = int(config["max_open_trades"])
    payload["stake_currency"] = config["stake_currency"]
    payload["stake_amount"] = float(config["stake_amount"])
    payload["dry_run_wallet"] = float(config["starting_balance"])
    payload["tradable_balance_ratio"] = 1.0
    payload["api_server"]["enabled"] = False
    payload["force_entry_enable"] = False
    payload["initial_state"] = "stopped"
    RUNTIME.mkdir(parents=True, exist_ok=True)
    destination = RUNTIME / "config.c1a.json"
    _write_json(destination, payload)
    return destination


def validate_data_evidence(source_sha: str) -> dict[str, Any]:
    boundary = _read_json(BOUNDARY_PATH, "C1A boundary report")
    coverage = _read_json(COVERAGE_PATH, "C1A coverage report")
    for label, payload in (("boundary", boundary), ("coverage", coverage)):
        if payload.get("status") != "PASS":
            raise C1AEvidenceError(f"{label} report did not pass")
        if payload.get("source_head_sha") != source_sha:
            raise C1AEvidenceError(f"{label} source SHA mismatch")
        if payload.get("economic_boundary_exclusive") != "2024-10-01T00:00:00+00:00":
            raise C1AEvidenceError(f"{label} boundary drift")
        if payload.get("holdout_state") != "HOLDOUT_CLOSED" or payload.get("live") != "FORBIDDEN":
            raise C1AEvidenceError(f"{label} safety state drift")
        cells = payload.get("cells")
        if not isinstance(cells, list) or len(cells) != 6:
            raise C1AEvidenceError(f"{label} must contain six cells")
    if coverage.get("boundary_sha256") != sha256_file(BOUNDARY_PATH):
        raise C1AEvidenceError("coverage report is not bound to boundary report")
    return {
        "boundary_path": str(BOUNDARY_PATH),
        "boundary_sha256": sha256_file(BOUNDARY_PATH),
        "coverage_path": str(COVERAGE_PATH),
        "coverage_sha256": sha256_file(COVERAGE_PATH),
    }


def capture_versions() -> dict[str, Any]:
    version_log = RESULTS / "freqtrade_version.txt"
    version_command = RESULTS / "freqtrade_version.command.json"
    run(["freqtrade", "--version"], version_log, version_command)
    dependency_log = RESULTS / "research_versions.txt"
    dependency_command = RESULTS / "research_versions.command.json"
    run(
        [
            sys.executable,
            "-c",
            (
                "import sys, freqtrade, ccxt, pandas; "
                "print('python', sys.version.replace('\\n', ' ')); "
                "print('freqtrade', freqtrade.__version__); "
                "print('ccxt', ccxt.__version__); "
                "print('pandas', pandas.__version__)"
            ),
        ],
        dependency_log,
        dependency_command,
    )
    value = version_log.read_text(encoding="utf-8", errors="replace").strip()
    if "freqtrade" not in value.lower():
        raise C1AEvidenceError("unable to prove Freqtrade version")
    return {
        "freqtrade_version_path": str(version_log),
        "freqtrade_version_sha256": sha256_file(version_log),
        "freqtrade_version_command_path": str(version_command),
        "freqtrade_version_command_sha256": sha256_file(version_command),
        "research_versions_path": str(dependency_log),
        "research_versions_sha256": sha256_file(dependency_log),
        "research_versions_command_path": str(dependency_command),
        "research_versions_command_sha256": sha256_file(dependency_command),
    }


def run_recursive_analysis(config: Mapping[str, Any], runtime_config: Path) -> dict[str, Any]:
    startup = config["startup_analysis"]
    cells: list[dict[str, Any]] = []
    for strategy in config["strategies"]:
        required = startup["required_indicators"][strategy]
        for pair in config["pairs"]:
            cell = RESULTS / "recursive" / _slug(strategy) / _slug(pair)
            log_path = cell / "recursive_analysis.log"
            command_path = cell / "recursive_analysis.command.json"
            command = [
                "freqtrade",
                "recursive-analysis",
                "--config",
                str(runtime_config),
                "--userdir",
                "freqtrade_data",
                "--datadir",
                str(DATA_DIR),
                "--strategy-path",
                "freqtrade_data/strategies",
                "--strategy",
                strategy,
                "--pairs",
                pair,
                "--timeframe",
                config["timeframe"],
                "--timerange",
                startup["timerange"],
                "--startup-candle",
                *[str(value) for value in startup["startup_candidates"]],
                "--no-color",
            ]
            run(command, log_path, command_path)
            parsed = validate_recursive_analysis_log(
                log_path,
                startup_count=int(startup["selected_startup_candles"]),
                required_indicators=required,
                max_variance_pct=float(startup["max_variance_pct"]),
            )
            cells.append(
                {
                    "strategy": strategy,
                    "pair": pair,
                    "log_path": str(log_path),
                    "log_sha256": sha256_file(log_path),
                    "command_path": str(command_path),
                    "command_sha256": sha256_file(command_path),
                    "result": parsed,
                }
            )
    if len(cells) != 9 or any(cell["result"].get("status") != "PASS" for cell in cells):
        raise C1AEvidenceError("recursive/no-lookahead evidence incomplete")
    report = {
        "schema_version": 1,
        "status": "PASS",
        "startup_candle_count": startup["selected_startup_candles"],
        "cells": cells,
    }
    path = RESULTS / "c1a_recursive_analysis_report.json"
    _write_json(path, report)
    return {"path": str(path), "sha256": sha256_file(path)}


def _profit_sums(trades: Sequence[Mapping[str, Any]]) -> tuple[float, float, list[float]]:
    gains = 0.0
    losses = 0.0
    positives: list[float] = []
    for index, trade in enumerate(trades):
        profit = _number(trade.get("profit_abs"), f"trade[{index}].profit_abs")
        if profit > 0:
            gains += profit
            positives.append(profit)
        elif profit < 0:
            losses += profit
    return gains, losses, sorted(positives, reverse=True)


def _verify_fee_binding(trades: Sequence[Mapping[str, Any]], expected_rate: float) -> dict[str, Any]:
    observed: set[float] = set()
    for index, trade in enumerate(trades):
        for field in ("fee_open", "fee_close"):
            if field not in trade:
                raise C1AEvidenceError(f"trade[{index}] missing {field}")
            value = _number(trade[field], f"trade[{index}].{field}")
            if abs(value - expected_rate) > 1e-12:
                raise C1AEvidenceError(
                    f"trade[{index}].{field} {value} does not equal expected {expected_rate}"
                )
            observed.add(value)
    return {
        "verified": True,
        "expected_fee_rate": expected_rate,
        "observed_fee_rates": sorted(observed),
        "basis": "per_trade_export" if trades else "no_trades_command_bound",
    }


def _trade_notional(trade: Mapping[str, Any], index: int) -> float:
    entry = 0.0
    exit_ = 0.0
    orders = trade.get("orders", [])
    if not isinstance(orders, list):
        raise C1AEvidenceError(f"trade[{index}].orders must be a list")
    for order_index, order in enumerate(orders):
        if not isinstance(order, Mapping):
            raise C1AEvidenceError(f"trade[{index}].orders[{order_index}] must be an object")
        cost = _number(order.get("cost", 0.0), f"trade[{index}].orders[{order_index}].cost")
        if bool(order.get("ft_is_entry", False)):
            entry += abs(cost)
        else:
            exit_ += abs(cost)
    if entry <= 0:
        entry = _number(trade.get("stake_amount"), f"trade[{index}].stake_amount")
    if exit_ <= 0:
        amount = _number(trade.get("amount"), f"trade[{index}].amount")
        close_rate = _number(trade.get("close_rate"), f"trade[{index}].close_rate")
        exit_ = abs(amount * close_rate)
    if entry <= 0 or exit_ <= 0:
        raise C1AEvidenceError(f"trade[{index}] has invalid notional")
    return entry + exit_


def _exit_summary(trades: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for index, trade in enumerate(trades):
        reason = trade.get("exit_reason")
        if not isinstance(reason, str) or not reason.strip():
            raise C1AEvidenceError(f"trade[{index}] missing exit_reason")
        item = grouped.setdefault(
            reason, {"exit_reason": reason, "trades": 0, "net_profit_abs": 0.0}
        )
        item["trades"] += 1
        item["net_profit_abs"] += _number(
            trade.get("profit_abs"), f"trade[{index}].profit_abs"
        )
    return sorted(grouped.values(), key=lambda item: item["exit_reason"])


def summarize_export(
    *,
    export_path: Path,
    strategy: str,
    window: Mapping[str, Any],
    multiplier: float,
    expected_pairs: Sequence[str],
    command_path: Path,
    log_path: Path,
) -> dict[str, Any]:
    try:
        export = load_freqtrade_export(export_path)
        _, payload = select_strategy_payload(export, strategy)
        trades = extract_trades(payload)
    except ProfitabilityDiagnosticsError as exc:
        raise C1AEvidenceError(str(exc)) from exc
    if int(payload.get("total_trades", len(trades))) != len(trades):
        raise C1AEvidenceError("summary/trade count mismatch")
    if payload.get("timeframe") != "1h":
        raise C1AEvidenceError("export timeframe drift")
    start = _timestamp(window["start"], "window.start")
    end = _timestamp(window["end"], "window.end")
    for index, trade in enumerate(trades):
        if trade.get("pair") not in expected_pairs:
            raise C1AEvidenceError(f"trade[{index}] pair outside universe")
        if bool(trade.get("is_short", False)):
            raise C1AEvidenceError(f"trade[{index}] is short")
        opened = _timestamp(trade.get("open_date"), f"trade[{index}].open_date")
        closed = _timestamp(trade.get("close_date"), f"trade[{index}].close_date")
        if opened < start or opened >= end or closed > end:
            raise C1AEvidenceError(f"trade[{index}] outside screen window")
    expected_fee = 0.0015 * multiplier
    fee_binding = _verify_fee_binding(trades, expected_fee)
    raw_pairs = payload.get("results_per_pair")
    if not isinstance(raw_pairs, list):
        raise C1AEvidenceError("results_per_pair missing")
    pairs: list[dict[str, Any]] = []
    for item in raw_pairs:
        if not isinstance(item, Mapping) or item.get("key") == "TOTAL":
            continue
        pairs.append(
            {
                "pair": str(item.get("key")),
                "trades": int(item.get("trades", 0)),
                "net_profit_abs": _number(item.get("profit_total_abs", 0.0), "pair profit"),
            }
        )
    if {item["pair"] for item in pairs} != set(expected_pairs):
        raise C1AEvidenceError("pair coverage mismatch")
    starting = _number(payload.get("starting_balance"), "starting_balance")
    gains, losses, positives = _profit_sums(trades)
    net_profit = _number(payload.get("profit_total_abs"), "profit_total_abs")
    if abs(gains + losses - net_profit) > 1e-7:
        raise C1AEvidenceError("trade profits do not reconcile to summary")
    net_return = _number(payload.get("profit_total"), "profit_total")
    if abs(net_profit / starting - net_return) > 1e-7:
        raise C1AEvidenceError("net return does not reconcile")
    profit_factor = gains / abs(losses) if losses < 0 else (0.0 if gains == 0 else 1e12)
    turnover = sum(_trade_notional(trade, index) for index, trade in enumerate(trades))
    return {
        "family_id": strategy,
        "window_id": window["id"],
        "cost_multiplier": multiplier,
        "fee_rate": expected_fee,
        "fee_binding": fee_binding,
        "starting_balance": starting,
        "trades": len(trades),
        "net_profit_abs": net_profit,
        "net_return_ratio": net_return,
        "max_drawdown_ratio": _number(
            payload.get("max_drawdown_account", 0.0), "max_drawdown"
        ),
        "profit_factor": profit_factor,
        "positive_profit_abs": gains,
        "negative_profit_abs": losses,
        "positive_trade_profits_abs": positives,
        "pairs": sorted(pairs, key=lambda item: item["pair"]),
        "turnover_notional_abs": turnover,
        "turnover_ratio": turnover / starting,
        "exit_reason_summary": _exit_summary(trades),
        "market_change": _number(payload.get("market_change", 0.0), "market_change"),
        "export_path": str(export_path),
        "export_sha256": sha256_file(export_path),
        "command_path": str(command_path),
        "command_sha256": sha256_file(command_path),
        "log_path": str(log_path),
        "log_sha256": sha256_file(log_path),
    }


def run_backtest_cell(
    config: Mapping[str, Any],
    runtime_config: Path,
    strategy: str,
    window: Mapping[str, Any],
    multiplier: float,
) -> dict[str, Any]:
    cell = (
        RESULTS
        / "cells"
        / _slug(strategy)
        / window["id"]
        / str(multiplier).replace(".", "_")
    )
    if cell.exists():
        shutil.rmtree(cell)
    cell.mkdir(parents=True)
    log_path = cell / "backtest.log"
    command_path = cell / "backtest.command.json"
    command = [
        "freqtrade",
        "backtesting",
        "--config",
        str(runtime_config),
        "--userdir",
        "freqtrade_data",
        "--datadir",
        str(DATA_DIR),
        "--strategy-path",
        "freqtrade_data/strategies",
        "--strategy",
        strategy,
        "--pairs",
        *config["pairs"],
        "--timeframe",
        config["timeframe"],
        "--timerange",
        _timerange(window["start"], window["end"]),
        "--fee",
        str(float(config["expected_fee_rate"]) * multiplier),
        "--cache",
        "none",
        "--export",
        "trades",
        "--backtest-directory",
        str(cell),
    ]
    run(command, log_path, command_path)
    export = discover_authoritative_export(cell, [strategy])
    return summarize_export(
        export_path=export,
        strategy=strategy,
        window=window,
        multiplier=multiplier,
        expected_pairs=config["pairs"],
        command_path=command_path,
        log_path=log_path,
    )


def buy_hold_comparators(config: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "hold_cash": {"net_return_ratio": 0.0, "selectable": False},
        "windows": [],
    }
    for window in config["screen_windows"]:
        start = pd.Timestamp(window["start"], tz="UTC")
        end = pd.Timestamp(window["end"], tz="UTC")
        pair_rows = []
        for pair in config["pairs"]:
            path = discover_candle_file(DATA_DIR, pair, config["timeframe"])
            selected = []
            for row in load_candles(path):
                when = pd.Timestamp(row["date"])
                when = when.tz_localize("UTC") if when.tzinfo is None else when.tz_convert("UTC")
                if start <= when < end:
                    selected.append(row)
            if len(selected) < 2:
                raise C1AEvidenceError(
                    f"insufficient buy-and-hold candles for {pair} {window['id']}"
                )
            pair_rows.append({"pair": pair, **buy_and_hold_metrics(selected)})
        result["windows"].append(
            {"window_id": window["id"], "selectable": False, "pairs": pair_rows}
        )
    return result


def _markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# C1A Strategy Family Screen Report",
        "",
        f"- Status: `{report['status']}`",
        f"- Selected family: `{report['selected_family']}`",
        "- Confirmation opened: `false`",
        "- Holdout: `HOLDOUT_CLOSED`",
        "- Live: `FORBIDDEN`",
        "",
        "## Family decisions",
        "",
        "| Family | Eligible | Expected return | 1.5x return | PF | Max DD | Trades |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["family_decisions"]:
        lines.append(
            "| {family_id} | {eligible} | {aggregate_expected_net_return_ratio:.4%} | "
            "{aggregate_1_5x_net_return_ratio:.4%} | {aggregate_expected_profit_factor:.4f} | "
            "{maximum_window_drawdown_ratio:.4%} | {total_trades} |".format(**item)
        )
    lines.extend(
        [
            "",
            "Screen-only result; no confirmation, holdout, paper, shadow, or live authorization.",
            "",
            "`HOLDOUT_CLOSED` / `LIVE FORBIDDEN`",
        ]
    )
    return "\n".join(lines) + "\n"


def build_manifest(
    *,
    source_sha: str,
    workflow_sha: str,
    run_id: str,
    config: Mapping[str, Any],
    data_evidence: Mapping[str, Any],
    versions: Mapping[str, Any],
    recursive: Mapping[str, Any],
    report: Mapping[str, Any],
) -> dict[str, Any]:
    source_paths = [
        CONFIG_PATH,
        STRATEGY_PATH,
        Path("scripts/c1a_data_guard.py"),
        Path("scripts/c1a_evidence.py"),
        Path("src/atos/c1a_family_screen.py"),
        Path("tests/test_c1a_strategy_contract.py"),
        Path("tests/test_c1a_family_screen.py"),
    ]
    files = [
        {"path": str(path), "sha256": sha256_file(path)}
        for path in sorted(RESULTS.rglob("*"))
        if path.is_file() and path != MANIFEST_PATH
    ]
    return {
        "schema_version": 1,
        "stage": "C1A",
        "status": report["status"],
        "source_head_sha": source_sha,
        "workflow_sha": workflow_sha,
        "github_run_id": run_id,
        "required_base_sha": config["required_base_sha"],
        "report_path": str(REPORT_JSON),
        "report_sha256": sha256_file(REPORT_JSON),
        "report_markdown_path": str(REPORT_MD),
        "report_markdown_sha256": sha256_file(REPORT_MD),
        "source_files": [
            {"path": str(path), "sha256": sha256_file(path)} for path in source_paths
        ],
        "data_evidence": dict(data_evidence),
        "versions": dict(versions),
        "recursive_analysis": dict(recursive),
        "retained_result_files": files,
        "selected_family": report["selected_family"],
        "confirmation_opened": False,
        "holdout_state": "HOLDOUT_CLOSED",
        "live": "FORBIDDEN",
    }


def main() -> int:
    source_sha = os.environ.get("C1A_SOURCE_SHA", "")
    workflow_sha = os.environ.get("GITHUB_SHA", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "local")
    if len(source_sha) != 40:
        raise C1AEvidenceError("C1A_SOURCE_SHA must be an exact 40-character commit SHA")
    if workflow_sha and len(workflow_sha) != 40:
        raise C1AEvidenceError("GITHUB_SHA must be a 40-character SHA when present")
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    RESULTS.mkdir(parents=True)
    try:
        config = _read_json(CONFIG_PATH, "C1A config")
        validate_config(config)
        data_evidence = validate_data_evidence(source_sha)
        runtime_config = prepare_runtime_config(config)
        versions = capture_versions()
        recursive = run_recursive_analysis(config, runtime_config)
        rows = [
            run_backtest_cell(config, runtime_config, strategy, window, multiplier)
            for strategy in config["strategies"]
            for window in config["screen_windows"]
            for multiplier in config["fee_multipliers"]
        ]
        if len(rows) != 27:
            raise C1AEvidenceError("C1A requires exactly 27 retained backtest cells")
        report = evaluate_screen(rows, config)
        report["source_head_sha"] = source_sha
        report["workflow_sha"] = workflow_sha
        report["github_run_id"] = run_id
        report["rows"] = rows
        report["comparators"] = buy_hold_comparators(config)
        _write_json(REPORT_JSON, report)
        REPORT_MD.write_text(_markdown(report), encoding="utf-8")
        _write_json(
            MANIFEST_PATH,
            build_manifest(
                source_sha=source_sha,
                workflow_sha=workflow_sha,
                run_id=run_id,
                config=config,
                data_evidence=data_evidence,
                versions=versions,
                recursive=recursive,
                report=report,
            ),
        )
    except Exception as exc:
        failure = {
            "schema_version": 1,
            "stage": "C1A",
            "status": "EVIDENCE_FAILURE",
            "source_head_sha": source_sha,
            "workflow_sha": workflow_sha,
            "github_run_id": run_id,
            "error_type": type(exc).__name__,
            "error": str(exc),
            "confirmation_opened": False,
            "holdout_state": "HOLDOUT_CLOSED",
            "live": "FORBIDDEN",
        }
        _write_json(REPORT_JSON, failure)
        REPORT_MD.write_text(
            "# C1A Strategy Family Screen\n\n"
            f"Evidence failure: `{type(exc).__name__}: {exc}`\n\n"
            "No economic classification. `HOLDOUT_CLOSED` / `LIVE FORBIDDEN`\n",
            encoding="utf-8",
        )
        print(f"C1A EVIDENCE FAILURE: {type(exc).__name__}: {exc}")
        raise
    print(
        f"C1A {report['status']}: selected_family={report['selected_family']}, "
        "confirmation_opened=false, HOLDOUT_CLOSED / LIVE FORBIDDEN"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
