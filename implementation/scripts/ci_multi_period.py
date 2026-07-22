#!/usr/bin/env python3
"""Run bounded multi-period backtests and generate a diagnostic report."""
from __future__ import annotations

import os
from pathlib import Path

from ci_subprocess_timeout import run_logged

RESULTS = Path("freqtrade_data/backtest_results")
REPORTS = Path("validation_reports")
RESULTS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

PERIODS = ("20250101-20250401", "20250401-20250701", "20250101-20250701")
BACKTEST_TIMEOUT_SECONDS = int(
    os.environ.get("ATOS_CI_BACKTEST_TIMEOUT_SECONDS", "900")
)
REPORT = REPORTS / "multi_period_backtest.md"

REPORT.write_text(
    "# Multi-Period Backtest\n\n"
    "| Period | Trades | Profit % | Max DD % | Status |\n"
    "|--------|--------|----------|----------|--------|\n",
    encoding="utf-8",
)

for index, period in enumerate(PERIODS):
    log = RESULTS / f"mp_{index}.log"
    print(f"=== Multi-period {index}: {period} ===")
    process_status = run_logged(
        [
            "freqtrade",
            "backtesting",
            "--config",
            "freqtrade_data/config.dryrun.json",
            "--strategy",
            "AISupervisedStrategy",
            "--strategy-path",
            "freqtrade_data/strategies",
            "--datadir",
            "freqtrade_data/data/okx",
            "--timerange",
            period,
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
            if (
                "AISupervisedStrategy" in line
                and "│" in line
                and "TOTAL" not in line[:20]
            ):
                parts = [part.strip() for part in line.split("│")]
                if len(parts) >= 7 and parts[2].isdigit():
                    drawdown = parts[8] if len(parts) > 8 else "-"
                    result_row = (
                        f"| {period} | {parts[2]} | {parts[5]} | "
                        f"{drawdown} | REAL_RUN |\n"
                    )
                    break
    if result_row is None:
        result_row = f"| {period} | - | - | - | {process_status} |\n"
    with REPORT.open("a", encoding="utf-8") as handle:
        handle.write(result_row)

print("=== Multi-period done ===")
print(REPORT.read_text(encoding="utf-8"))
