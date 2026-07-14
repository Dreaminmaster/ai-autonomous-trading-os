#!/usr/bin/env python3
"""Run the frozen C0A canonical reproduction and trade-level diagnostics."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from atos.profitability_diagnostics import (
    analyze_export,
    build_manifest,
    discover_candle_file,
    load_candles,
    write_json_atomic,
)

IMPL_DIR = Path(__file__).resolve().parents[1]
os.chdir(IMPL_DIR)

output_base = "c0a_canonical"
policy_path = Path("config/policy.validation.json")
expected_path = Path("config/c0a_canonical_expected.json")
results_dir = Path("freqtrade_data/backtest_results")
results_dir.mkdir(parents=True, exist_ok=True)

env = os.environ.copy()
env.setdefault("TIMERANGE", "20250101-20250701")
env.pop("RUN_LOOKAHEAD", None)

completed = subprocess.run(
    [
        sys.executable,
        "scripts/run_canonical_backtest.py",
        "c0a_canonical",
        output_base,
        str(policy_path),
    ],
    env=env,
    check=False,
)
if completed.returncode != 0:
    raise SystemExit(completed.returncode)

export_path = results_dir / f"{output_base}.json"
expected = json.loads(expected_path.read_text(encoding="utf-8"))
candle_path = discover_candle_file("freqtrade_data/data/okx", "BTC/USDT", "5m")
candles = load_candles(candle_path)

report = analyze_export(
    export_path=export_path,
    strategy_name="AISupervisedStrategy",
    candles_by_pair={"BTC/USDT": candles},
    expected=expected,
)
manifest = build_manifest(
    run_id=os.environ.get("GITHUB_RUN_ID", "local"),
    head_sha=os.environ.get("GITHUB_SHA", "local"),
    strategy_name="AISupervisedStrategy",
    export_path=export_path,
    config_path="freqtrade_data/config.dryrun.json",
    policy_path=policy_path,
    data_files=[candle_path],
    generated_at=datetime.now(UTC).isoformat(),
)
write_json_atomic(results_dir / "c0a_trade_diagnostics.json", report)
write_json_atomic(results_dir / "c0a_run_manifest.json", manifest)

reproduction = report["canonical_reproduction"]
if reproduction["status"] != "PASS":
    print(json.dumps(reproduction, indent=2), file=sys.stderr)
    raise SystemExit(1)

print(
    "C0A canonical reproduction PASS: "
    f"trades={report['computed_trade_metrics']['total_trades']} "
    f"paths={len(report['trade_paths'])}"
)
