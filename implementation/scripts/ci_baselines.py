#!/usr/bin/env python3
"""Run bounded strategy baselines and generate a diagnostic report."""
from __future__ import annotations

import os
from pathlib import Path

from ci_subprocess_timeout import run_logged

RESULTS = Path("freqtrade_data/backtest_results")
REPORTS = Path("validation_reports")
RESULTS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

STRATEGIES = (
    "AISupervisedStrategy",
    "SmaCrossover",
    "RsiMeanReversion",
    "SampleStrategy",
)
BACKTEST_TIMEOUT_SECONDS = int(
    os.environ.get("ATOS_CI_BACKTEST_TIMEOUT_SECONDS", "900")
)
REPORT = REPORTS / "baseline_comparison.md"

REPORT.write_text(
    "# Baseline Comparison\n\n"
    "**Timerange:** 20250101-20250701 BTC/USDT 5m\n\n"
    "| Strategy | Trades | Profit % | Max DD % | Status |\n"
    "|----------|--------|----------|----------|--------|\n",
    encoding="utf-8",
)

for index, strategy in enumerate(STRATEGIES):
    log = RESULTS / f"bl_{index}.log"
    print(f"=== Baseline: {strategy} ===")
    process_status = run_logged(
        [
            "freqtrade",
            "backtesting",
            "--config",
            "freqtrade_data/config.dryrun.json",
            "--strategy",
            strategy,
            "--strategy-path",
            "freqtrade_data/strategies",
            "--datadir",
            "freqtrade_data/data/okx",
            "--timerange",
            "20250101-20250701",
            "--timeframe",
            "5m",
        ],
        log_path=log,
        timeout_seconds=BACKTEST_TIMEOUT_SECONDS,
    )

    text = log.read_text(encoding="utf-8", errors="replace")
    result_row: str | None = None
    if process_status == "SUCCESS":
        for line in text.splitlines():
            if strategy in line and "│" in line:
                parts = [part.strip() for part in line.split("│")]
                if len(parts) >= 7 and parts[2].isdigit():
                    drawdown = parts[8] if len(parts) > 8 else "-"
                    result_row = (
                        f"| {strategy} | {parts[2]} | {parts[5]} | "
                        f"{drawdown} | REAL_RUN |\n"
                    )
                    break
    if result_row is None:
        result_row = f"| {strategy} | - | - | - | {process_status} |\n"
    with REPORT.open("a", encoding="utf-8") as handle:
        handle.write(result_row)

try:
    import pandas as pd

    for data_path in sorted(Path("freqtrade_data/data/okx").rglob("*.feather")):
        if "BTC" not in str(data_path) or "5m" not in str(data_path):
            continue
        frame = pd.read_feather(data_path)
        if "close" not in frame.columns or frame.empty:
            continue
        first = float(frame["close"].iloc[0])
        last = float(frame["close"].iloc[-1])
        change = (last - first) / first * 100
        with REPORT.open("a", encoding="utf-8") as handle:
            handle.write(
                f"| Buy & Hold BTC | 1 | {change:.2f}% | "
                f"{abs(change):.2f}% | REAL_RUN |\n"
            )
        break
    else:
        raise RuntimeError("BTC 5m feather data unavailable")
except Exception as exc:  # Diagnostic comparison must not hide the reason.
    with REPORT.open("a", encoding="utf-8") as handle:
        handle.write(f"| Buy & Hold BTC | 1 | - | - | FAILED: {type(exc).__name__} |\n")

print("=== Baseline done ===")
print(REPORT.read_text(encoding="utf-8"))
