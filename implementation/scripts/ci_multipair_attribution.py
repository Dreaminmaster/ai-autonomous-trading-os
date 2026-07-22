#!/usr/bin/env python3
"""Run bounded multi-pair validation and generate attribution reports."""
from __future__ import annotations

import os
from pathlib import Path

from ci_subprocess_timeout import run_logged

RESULTS = Path("freqtrade_data/backtest_results")
REPORTS = Path("validation_reports")
RESULTS.mkdir(parents=True, exist_ok=True)
REPORTS.mkdir(parents=True, exist_ok=True)

DOWNLOAD_TIMEOUT_SECONDS = int(
    os.environ.get("ATOS_CI_DOWNLOAD_TIMEOUT_SECONDS", "600")
)
BACKTEST_TIMEOUT_SECONDS = int(
    os.environ.get("ATOS_CI_BACKTEST_TIMEOUT_SECONDS", "900")
)
MULTIPAIR_REPORT = REPORTS / "multi_pair_backtest.md"

MULTIPAIR_REPORT.write_text(
    "# Multi-Pair Backtest\n\n"
    "**Timerange:** 20250101-20250701 5m spot\n\n"
    "| Pair | Download | Trades | Profit % | Max DD % | Data Status |\n"
    "|------|----------|--------|----------|----------|-------------|\n",
    encoding="utf-8",
)

for pair in ("ETH/USDT", "SOL/USDT"):
    safe_name = pair.replace("/", "_")
    download_log = RESULTS / f"dl_{safe_name}.log"
    download_status = run_logged(
        [
            "freqtrade",
            "download-data",
            "--config",
            "freqtrade_data/config.dryrun.json",
            "--datadir",
            "freqtrade_data/data/okx",
            "--exchange",
            "okx",
            "--pairs",
            pair,
            "--timeframes",
            "5m",
            "--timerange",
            "20250101-20250701",
        ],
        log_path=download_log,
        timeout_seconds=DOWNLOAD_TIMEOUT_SECONDS,
    )

    download_text = download_log.read_text(encoding="utf-8", errors="replace")
    downloaded = download_status == "SUCCESS" and "Downloaded data" in download_text
    result_row: str | None = None
    if downloaded:
        backtest_log = RESULTS / f"bt_{safe_name}.log"
        backtest_status = run_logged(
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
                "20250101-20250701",
                "--timeframe",
                "5m",
                "--pairs",
                pair,
            ],
            log_path=backtest_log,
            timeout_seconds=BACKTEST_TIMEOUT_SECONDS,
        )
        backtest_text = backtest_log.read_text(encoding="utf-8", errors="replace")
        if backtest_status == "SUCCESS":
            for line in backtest_text.splitlines():
                if "AISupervisedStrategy" in line and "│" in line:
                    parts = [part.strip() for part in line.split("│")]
                    if len(parts) >= 7 and parts[2].isdigit():
                        drawdown = parts[8] if len(parts) > 8 else "-"
                        result_row = (
                            f"| {pair} | SUCCESS | {parts[2]} | {parts[5]} | "
                            f"{drawdown} | REAL_RUN |\n"
                        )
                        break
        if result_row is None:
            result_row = (
                f"| {pair} | SUCCESS | - | - | - | {backtest_status} |\n"
            )
    else:
        last_line = next(
            (line for line in reversed(download_text.splitlines()) if line.strip()),
            download_status,
        )
        result_row = (
            f"| {pair} | {download_status} | - | - | - | "
            f"FAILED: {last_line[:60]} |\n"
        )
    with MULTIPAIR_REPORT.open("a", encoding="utf-8") as handle:
        handle.write(result_row)

attribution_report = REPORTS / "strategy_attribution.md"
backtest_text = (
    Path("backtest.log").read_text(encoding="utf-8", errors="replace")
    if Path("backtest.log").is_file()
    else ""
)
with attribution_report.open("w", encoding="utf-8") as handle:
    handle.write("# Strategy Attribution\n\n## Entry Tag Distribution\n\n```\n")
    for line in backtest_text.splitlines():
        if (
            any(tag in line for tag in ("atos_trend", "atos_breakout", "atos_mean"))
            and "│" in line
            and "TOTAL" not in line
            and "MIXED" not in line
        ):
            handle.write(line + "\n")
    handle.write("```\n\n## Exit Reason Distribution\n\n```\n")
    for line in backtest_text.splitlines():
        if (
            any(tag in line for tag in ("take_profit", "max_holding", "stop_loss"))
            and "│" in line
            and "TOTAL" not in line
            and "MIXED" not in line
        ):
            handle.write(line + "\n")
    handle.write("```\n\n## ATOS Signal Diagnostics\n\n```\n")
    for line in backtest_text.splitlines():
        if "ATOS_SIGNAL_DIAGNOSTICS" in line:
            handle.write(line + "\n")
    handle.write("```\n")
