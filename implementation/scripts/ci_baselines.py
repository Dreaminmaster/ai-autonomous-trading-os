#!/usr/bin/env python3
"""Run baseline comparison: AISupervised, SMA Crossover, RSI, SampleStrategy."""
import subprocess, os
from pathlib import Path

os.makedirs("freqtrade_data/backtest_results", exist_ok=True)
os.makedirs("validation_reports", exist_ok=True)

STRATS = ["AISupervisedStrategy", "SmaCrossover", "RsiMeanReversion", "SampleStrategy"]

with open("validation_reports/baseline_comparison.md", "w") as f:
    f.write("# Baseline Comparison\n\n**Timerange:** 20250101-20250701 BTC/USDT 5m\n\n")
    f.write("| Strategy | Trades | Profit % | Max DD % | Status |\n")
    f.write("|----------|--------|----------|----------|--------|\n")

for i, strat in enumerate(STRATS):
    log = f"freqtrade_data/backtest_results/bl_{i}.log"
    print(f"=== Baseline: {strat} ===")
    subprocess.run([
        "freqtrade", "backtesting",
        "--config", "freqtrade_data/config.dryrun.json",
        "--strategy", strat,
        "--strategy-path", "freqtrade_data/strategies",
        "--datadir", "freqtrade_data/data/okx",
        "--timerange", "20250101-20250701",
        "--timeframe", "5m",
    ], check=False, stdout=open(log, "w"), stderr=subprocess.STDOUT)

    text = open(log).read()
    found = False
    for line in text.split("\n"):
        if strat in line and "\u2502" in line:
            parts = [p.strip() for p in line.split("\u2502")]
            if len(parts) >= 7 and (parts[2].strip().isdigit() or parts[2].strip() == "0"):
                with open("validation_reports/baseline_comparison.md", "a") as f:
                    f.write(f"| {strat} | {parts[2].strip()} | {parts[5].strip()} | {parts[8].strip() if len(parts)>8 else '-'} | REAL_RUN |\n")
                found = True
                break
    if not found:
        with open("validation_reports/baseline_comparison.md", "a") as f:
            f.write(f"| {strat} | - | - | - | FAILED |\n")

# Buy & Hold
try:
    import pandas as pd
    for fpath in sorted(Path("freqtrade_data/data/okx").rglob("*.feather")):
        if "BTC" in str(fpath) and "5m" in str(fpath):
            df = pd.read_feather(fpath)
            if "close" in df.columns and len(df) > 0:
                first = float(df["close"].iloc[0])
                last = float(df["close"].iloc[-1])
                pct = (last - first) / first * 100
                with open("validation_reports/baseline_comparison.md", "a") as f:
                    f.write(f"| Buy & Hold BTC | 1 | {pct:.2f}% | {abs(pct):.2f}% | REAL_RUN |\n")
                break
except Exception:
    with open("validation_reports/baseline_comparison.md", "a") as f:
        f.write("| Buy & Hold BTC | 1 | - | - | FAILED |\n")

print("=== Baseline done ===")
print(open("validation_reports/baseline_comparison.md").read())
