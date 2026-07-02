#!/usr/bin/env python3
"""CI helper: multi-pair backtest + attribution report."""
import subprocess, os

os.makedirs("freqtrade_data/backtest_results", exist_ok=True)
os.makedirs("validation_reports", exist_ok=True)

# Multi-pair
with open("validation_reports/multi_pair_backtest.md", "w") as f:
    f.write("# Multi-Pair Backtest\n\n**Timerange:** 20250101-20250701 5m spot\n\n")
    f.write("| Pair | Download | Trades | Profit % | Max DD % | Data Status |\n")
    f.write("|------|----------|--------|----------|----------|-------------|\n")

for pair in ["ETH/USDT", "SOL/USDT"]:
    safe = pair.replace("/", "_")
    dl_log = f"freqtrade_data/backtest_results/dl_{safe}.log"
    subprocess.run([
        "freqtrade", "download-data",
        "--config", "freqtrade_data/config.dryrun.json",
        "--datadir", "freqtrade_data/data/okx",
        "--exchange", "okx",
        "--pairs", pair,
        "--timeframes", "5m",
        "--timerange", "20250101-20250701",
    ], check=False, stdout=open(dl_log, "w"), stderr=subprocess.STDOUT)

    dl_text = open(dl_log).read()
    if "Downloaded data" in dl_text:
        bt_log = f"freqtrade_data/backtest_results/bt_{safe}.log"
        subprocess.run([
            "freqtrade", "backtesting",
            "--config", "freqtrade_data/config.dryrun.json",
            "--strategy", "AISupervisedStrategy",
            "--strategy-path", "freqtrade_data/strategies",
            "--datadir", "freqtrade_data/data/okx",
            "--timerange", "20250101-20250701",
            "--timeframe", "5m",
            "--pairs", pair,
        ], check=False, stdout=open(bt_log, "w"), stderr=subprocess.STDOUT)
        bt_text = open(bt_log).read()
        found = False
        for line in bt_text.split("\n"):
            if "AISupervisedStrategy" in line and "\u2502" in line:
                parts = [p.strip() for p in line.split("\u2502")]
                if len(parts) >= 7 and parts[2].strip().isdigit():
                    with open("validation_reports/multi_pair_backtest.md", "a") as f:
                        f.write(f"| {pair} | SUCCESS | {parts[2].strip()} | {parts[5].strip()} | {parts[8].strip() if len(parts)>8 else '-'} | REAL_RUN |\n")
                    found = True
                    break
        if not found:
            with open("validation_reports/multi_pair_backtest.md", "a") as f:
                f.write(f"| {pair} | SUCCESS | - | - | - | FAILED (bt parse) |\n")
    else:
        err = dl_text.split("\n")[-2] if "\n" in dl_text else "unknown"
        with open("validation_reports/multi_pair_backtest.md", "a") as f:
            f.write(f"| {pair} | FAILED | - | - | - | FAILED: {err[:60]} |\n")

# Strategy attribution
with open("validation_reports/strategy_attribution.md", "w") as f:
    f.write("# Strategy Attribution\n\n")
    f.write("## Entry Tag Distribution\n\n```\n")
    bt = open("backtest.log").read() if os.path.exists("backtest.log") else ""
    for line in bt.split("\n"):
        if any(tag in line for tag in ["atos_trend", "atos_breakout", "atos_mean"]) and "\u2502" in line:
            if "TOTAL" not in line and "MIXED" not in line:
                f.write(line + "\n")
    f.write("```\n\n## Exit Reason Distribution\n\n```\n")
    for line in bt.split("\n"):
        if any(tag in line for tag in ["take_profit", "max_holding", "stop_loss"]) and "\u2502" in line:
            if "TOTAL" not in line and "MIXED" not in line:
                f.write(line + "\n")
    f.write("```\n\n## ATOS Signal Diagnostics\n\n```\n")
    for line in bt.split("\n"):
        if "ATOS_SIGNAL_DIAGNOSTICS" in line:
            f.write(line + "\n")
    f.write("```\n")
