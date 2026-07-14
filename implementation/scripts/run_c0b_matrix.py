#!/usr/bin/env python3
"""Run the prospective C0B deterministic baseline matrix."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from atos.c0b_export import (
    C0BExportDiscoveryError,
    discover_authoritative_export,
)
from atos.c0b_matrix import build_matrix_report, sha256_file, write_report_files
from atos.profitability_diagnostics import write_json_atomic


IMPL_DIR = Path(__file__).resolve().parents[1]
os.chdir(IMPL_DIR)


def _log_tail(path: Path, line_count: int = 80) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"unable to read {path}: {exc}"
    return "\n".join(lines[-line_count:])


config_path = Path("config/c0b_matrix.json")
config = json.loads(config_path.read_text(encoding="utf-8"))
if config.get("live") != "FORBIDDEN":
    raise SystemExit("C0B config must keep LIVE FORBIDDEN")

pairs = config["pairs"]
timeframes = config["timeframes"]
strategies = config["strategies"]
multipliers = config["fee_multipliers"]
expected_fee = float(config["expected_fee_rate"])
timerange = str(config["timerange"])

base_config_path = Path("freqtrade_data/config.dryrun.json")
base_config = json.loads(base_config_path.read_text(encoding="utf-8"))
if base_config.get("dry_run") is not True:
    raise SystemExit("C0B requires dry_run=true")

# Config values override strategy attributes in Freqtrade. Remove strategy-level
# controls from the shared dry-run config so each baseline is evaluated using
# its own frozen stoploss/ROI/exit semantics.
strategy_override_keys = [
    "stoploss",
    "minimal_roi",
    "trailing_stop",
    "trailing_stop_positive",
    "trailing_stop_positive_offset",
    "trailing_only_offset_is_reached",
    "use_exit_signal",
    "exit_profit_only",
    "ignore_roi_if_entry_signal",
]
removed_overrides = {
    key: base_config.pop(key)
    for key in strategy_override_keys
    if key in base_config
}

base_config["exchange"]["pair_whitelist"] = pairs
base_config["max_open_trades"] = len(pairs)
base_config["api_server"]["enabled"] = False

runtime_dir = Path("freqtrade_data/c0b_runtime")
runtime_dir.mkdir(parents=True, exist_ok=True)
matrix_config_path = runtime_dir / "config.c0b.json"
matrix_config_path.write_text(json.dumps(base_config, indent=2), encoding="utf-8")

results_dir = Path("freqtrade_data/backtest_results/c0b")
if results_dir.exists():
    shutil.rmtree(results_dir)
results_dir.mkdir(parents=True, exist_ok=True)
run_specs: list[dict[str, object]] = []

for timeframe in timeframes:
    for raw_multiplier in multipliers:
        multiplier = float(raw_multiplier)
        label = str(multiplier).replace(".", "_")
        cell_id = f"{timeframe}_{label}"
        cell_dir = results_dir / f"cell_{cell_id}"
        cell_dir.mkdir(parents=True, exist_ok=False)
        log_path = results_dir / f"c0b_{cell_id}.log"

        command = [
            "freqtrade",
            "backtesting",
            "--config",
            str(matrix_config_path),
            "--datadir",
            "freqtrade_data/data/okx",
            "--strategy-path",
            "freqtrade_data/strategies",
            "--strategy-list",
            *strategies,
            "--pairs",
            *pairs,
            "--timeframe",
            timeframe,
            "--timerange",
            timerange,
            "--fee",
            str(expected_fee * multiplier),
            "--cache",
            "none",
            "--export",
            "trades",
            "--backtest-directory",
            str(cell_dir),
        ]
        print(
            f"C0B run timeframe={timeframe} fee_multiplier={multiplier} "
            f"strategies={','.join(strategies)}"
        )
        with log_path.open("w", encoding="utf-8") as log_handle:
            completed = subprocess.run(
                command,
                check=False,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
            )
        if completed.returncode != 0:
            print(_log_tail(log_path))
            raise SystemExit(completed.returncode)

        try:
            export_path = discover_authoritative_export(cell_dir, strategies)
        except C0BExportDiscoveryError as exc:
            print(_log_tail(log_path))
            raise SystemExit(str(exc)) from exc

        run_specs.append(
            {
                "timeframe": timeframe,
                "fee_multiplier": multiplier,
                "export_path": str(export_path),
                "log_path": str(log_path),
            }
        )

report = build_matrix_report(run_specs=run_specs, config=config)
report_path = results_dir / "c0b_matrix_report.json"
markdown_path = results_dir / "c0b_matrix_report.md"
write_report_files(report, json_path=report_path, markdown_path=markdown_path)

data_files = sorted(
    path
    for path in Path("freqtrade_data/data/okx").glob("*")
    if path.is_file()
    and any(
        timeframe in path.name
        for timeframe in [*timeframes, *config["informative_timeframes"]]
    )
)
manifest = {
    "schema_version": 3,
    "run_id": os.environ.get("GITHUB_RUN_ID", "local"),
    "head_sha": os.environ.get("GITHUB_SHA", "local"),
    "generated_at": datetime.now(UTC).isoformat(),
    "live": "FORBIDDEN",
    "config": {"path": str(config_path), "sha256": sha256_file(config_path)},
    "runtime_config": {
        "path": str(matrix_config_path),
        "sha256": sha256_file(matrix_config_path),
        "removed_strategy_overrides": removed_overrides,
    },
    "strategy_file": {
        "path": "freqtrade_data/strategies/c0b_baselines.py",
        "sha256": sha256_file("freqtrade_data/strategies/c0b_baselines.py"),
    },
    "data_files": [
        {"path": str(path), "sha256": sha256_file(path)} for path in data_files
    ],
    "exports": [
        {
            "timeframe": spec["timeframe"],
            "fee_multiplier": spec["fee_multiplier"],
            "path": spec["export_path"],
            "sha256": sha256_file(str(spec["export_path"])),
            "log_path": spec["log_path"],
            "log_sha256": sha256_file(str(spec["log_path"])),
        }
        for spec in run_specs
    ],
    "report": {"path": str(report_path), "sha256": sha256_file(report_path)},
}
write_json_atomic(results_dir / "c0b_run_manifest.json", manifest)

print(
    "C0B matrix complete: "
    + ", ".join(
        f"{item['candidate_id']}={item['status']}"
        for item in report["candidate_screening"]
    )
)
