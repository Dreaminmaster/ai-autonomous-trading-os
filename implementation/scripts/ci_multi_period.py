#!/usr/bin/env python3
"""Run multi-period backtests and generate report."""
import subprocess, os

os.makedirs("freqtrade_data/backtest_results", exist_ok=True)
os.makedirs("validation_reports", exist_ok=True)

PERIODS = ["20250101-20250401", "20250401-20250701", "20250101-20250701"]

with open("validation_reports/multi_period_backtest.md", "w") as f:
    f.write("# Multi-Period Backtest\n\n")
    f.write("| Period | Trades | Profit % | Max DD % | Status |\n")
    f.write("|--------|--------|----------|----------|--------|\n")

for i, period in enumerate(PERIODS):
    log = f"freqtrade_data/backtest_results/mp_{i}.log"
    print(f"=== Multi-period {i}: {period} ===")
    subprocess.run([
        "freqtrade", "backtesting",
        "--config", "freqtrade_data/config.dryrun.json",
        "--strategy", "AISupervisedStrategy",
        "--strategy-path", "freqtrade_data/strategies",
        "--datadir", "freqtrade_data/data/okx",
        "--timerange", period,
        "--timeframe", "5m",
    ], check=False, stdout=open(log, "w"), stderr=subprocess.STDOUT)

    text = open(log).read()
    found = False
    for line in text.split("\n"):
        if "AISupervisedStrategy" in line and "\u2502" in line and "TOTAL" not in line[:20]:
            parts = [p.strip() for p in line.split("\u2502")]
            if len(parts) >= 7 and parts[2].strip().isdigit():
                with open("validation_reports/multi_period_backtest.md", "a") as f:
                    f.write(f"| {period} | {parts[2].strip()} | {parts[5].strip()} | {parts[8].strip() if len(parts)>8 else '-'} | REAL_RUN |\n")
                found = True
                break
    if not found:
        with open("validation_reports/multi_period_backtest.md", "a") as f:
            f.write(f"| {period} | - | - | - | FAILED |\n")

print("=== Multi-period done ===")
print(open("validation_reports/multi_period_backtest.md").read())
