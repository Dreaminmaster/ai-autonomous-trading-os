#!/usr/bin/env python3
"""CI helper: run baseline strategy backtest and generate report."""
import subprocess, os

STRAT = os.environ.get("BASELINE_STRATEGY", "AISupervisedStrategy")
LOG = os.environ.get("BASELINE_LOG", "freqtrade_data/backtest_results/bl_unknown.log")
REPORT = "validation_reports/baseline_comparison.md"

os.makedirs("freqtrade_data/backtest_results", exist_ok=True)
os.makedirs("validation_reports", exist_ok=True)

subprocess.run([
    "freqtrade", "backtesting",
    "--config", "freqtrade_data/config.dryrun.json",
    "--strategy", STRAT,
    "--strategy-path", "freqtrade_data/strategies",
    "--datadir", "freqtrade_data/data/okx",
    "--timerange", "20250101-20250701",
    "--timeframe", "5m",
], check=False, stdout=open(LOG, "w"), stderr=subprocess.STDOUT)

text = open(LOG).read()
found = False
for line in text.split("\n"):
    if STRAT in line and "\u2502" in line:
        parts = [p.strip() for p in line.split("\u2502")]
        if len(parts) >= 7 and (parts[2].strip().isdigit() or parts[2].strip() == "0"):
            trades = parts[2].strip()
            tot = parts[5].strip()
            dd = parts[8].strip() if len(parts) > 8 else "-"
            with open(REPORT, "a") as f:
                f.write(f"| {STRAT} | {trades} | - | {tot} | {dd} | REAL_RUN |\n")
            found = True
            break
if not found:
    with open(REPORT, "a") as f:
        f.write(f"| {STRAT} | - | - | - | - | FAILED (no parse) |\n")
