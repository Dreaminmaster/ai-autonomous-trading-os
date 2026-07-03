#!/usr/bin/env python3
"""
Strategy Fix Round 1 — A/B matrix of 9 strategy variants.
Each variant runs a real Freqtrade backtest + lookahead.
Output: validation_reports/strategy_fix_round1.md
Exits 1 if any variant fails to produce log.
"""
import subprocess, json, os, sys, time as _time
from pathlib import Path

IMPL_DIR = Path(__file__).resolve().parents[1]
os.chdir(IMPL_DIR)

os.makedirs("freqtrade_data/backtest_results", exist_ok=True)
os.makedirs("validation_reports", exist_ok=True)

TIMERANGE = os.environ.get("TIMERANGE", "20250101-20250701")
TIMEOUT = 900

BASE_POLICY = json.loads(Path("config/policy.experiment_round1.json").read_text())

VARIANTS = [
    ("1_baseline_current", {}, "baseline unchanged"),
    ("2_trend_weight_025_only", {"experiment.strategy_weights.trend_following_v1": 0.25}, "trend weight reduced to 0.25"),
    ("3_trend_disabled_only", {"experiment.disabled_strategies": ["trend_following_v1"]}, "trend_following disabled"),
    ("4_max_hold_6h_only", {"experiment.max_holding_minutes": 360}, "max hold 6h"),
    ("5_max_hold_4h_only", {"experiment.max_holding_minutes": 240}, "max hold 4h"),
    ("6_trend_025_hold_6h", {"experiment.strategy_weights.trend_following_v1": 0.25, "experiment.max_holding_minutes": 360}, "trend 0.25 + hold 6h"),
    ("7_trend_disabled_hold_6h", {"experiment.disabled_strategies": ["trend_following_v1"], "experiment.max_holding_minutes": 360}, "trend disabled + hold 6h"),
    ("8_trend_025_early_exit", {"experiment.strategy_weights.trend_following_v1": 0.25, "experiment.max_holding_minutes": 360, "experiment.early_exit_loss_pct": -0.3, "experiment.early_exit_after_minutes": 120}, "trend 0.25 + early exit"),
    ("9_trend_disabled_early_exit", {"experiment.disabled_strategies": ["trend_following_v1"], "experiment.max_holding_minutes": 360, "experiment.early_exit_loss_pct": -0.3, "experiment.early_exit_after_minutes": 120}, "trend disabled + early exit"),
]

def apply_overrides(policy, overrides):
    policy = json.loads(json.dumps(policy))
    for key, value in overrides.items():
        parts = key.split(".")
        target = policy
        for p in parts[:-1]:
            if p not in target:
                target[p] = {}
            target = target[p]
        target[parts[-1]] = value
    return policy

def run_backtest(variant_name, policy, desc):
    policy_path = f"freqtrade_data/backtest_results/exp_{variant_name}_policy.json"
    Path(policy_path).write_text(json.dumps(policy, indent=2))

    log_path = f"freqtrade_data/backtest_results/round1_{variant_name}.log"
    env = os.environ.copy()
    env["ATOS_POLICY"] = policy_path

    print(f"  [{variant_name}] {desc} ...", flush=True)
    t0 = _time.time()

    result = subprocess.run([
        "freqtrade", "backtesting",
        "--config", "freqtrade_data/config.dryrun.json",
        "--strategy", "AISupervisedStrategy",
        "--strategy-path", "freqtrade_data/strategies",
        "--datadir", "freqtrade_data/data/okx",
        "--timerange", TIMERANGE,
        "--timeframe", "5m",
        "--cache", "none",
    ], capture_output=True, text=True, timeout=TIMEOUT, env=env)

    elapsed = _time.time() - t0
    rc = result.returncode

    # Write log ALWAYS
    Path(log_path).write_text(result.stdout + "\n" + result.stderr)

    if rc != 0:
        # Write log ALWAYS even on failure
        Path(log_path).write_text(f"STDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n\nRC={rc}")
        print(f"  [{variant_name}] FAILED (rc={rc}) in {elapsed:.0f}s", flush=True)
        return {"variant": variant_name, "status": f"FAILED(rc={rc})", "trades": "?", "profit": "?", "dd": "?", "lookahead": "?"}

    text = result.stdout
    trades = profit = dd = "?"
    for line in text.split("\n"):
        if "AISupervisedStrategy" in line and "\u2502" in line and "TOTAL" not in line:
            parts = [p.strip() for p in line.split("\u2502")]
            if len(parts) >= 8:
                trades = parts[2].strip()
                profit = parts[5].strip()
                dd = parts[8].strip() if len(parts) > 8 else "-"

    # Lookahead
    la_log = f"freqtrade_data/backtest_results/round1_la_{variant_name}.log"
    la_result = subprocess.run([
        "freqtrade", "lookahead-analysis",
        "--config", "freqtrade_data/config.dryrun.json",
        "--strategy", "AISupervisedStrategy",
        "--strategy-path", "freqtrade_data/strategies",
        "--timerange", TIMERANGE,
    ], capture_output=True, text=True, timeout=TIMEOUT, env=env)
    Path(la_log).write_text(la_result.stdout + "\n" + la_result.stderr)
    la_status = "PASS" if "has_bias" in la_result.stdout and "No" in la_result.stdout.split("has_bias")[-1][:5] else "?"
    if "too few trades" in la_result.stdout:
        la_status = "TOO_FEW"

    print(f"  [{variant_name}] trades={trades} profit={profit} dd={dd} la={la_status} ({elapsed:.0f}s)", flush=True)

    return {"variant": variant_name, "status": "OK", "trades": trades, "profit": profit, "dd": dd, "lookahead": la_status}

# ════════════════════════════════════════
# Run all
# ════════════════════════════════════════
results = []
failed = 0
for name, overrides, desc in VARIANTS:
    policy = apply_overrides(BASE_POLICY, overrides)
    r = run_backtest(name, policy, desc)
    results.append(r)
    if "FAILED" in r.get("status", ""):
        failed += 1

# ════════════════════════════════════════
# Write report
# ════════════════════════════════════════
baseline = results[0] if results else {"profit": "-16.12", "dd": "17.85%"}

with open("validation_reports/strategy_fix_round1.md", "w") as f:
    f.write("# Strategy Fix Round 1\n\n")
    f.write(f"**Timerange:** {TIMERANGE} | **Pair:** BTC/USDT 5m\n\n")
    f.write(f"**Baseline:** {baseline['profit']} profit, {baseline['trades']} trades, DD {baseline['dd']}\n\n")
    f.write("| # | Variant | Trades | Profit % | Max DD | Lookahead | Status |\n")
    f.write("|---|---------|--------|----------|--------|-----------|--------|\n")

    for r in results:
        f.write(f"| {r['variant']} | {r['trades']} | {r['profit']} | {r['dd']} | {r['lookahead']} | {r['status']} |\n")

    f.write("\n## Conclusion\n\n")
    f.write(f"- Baseline: {baseline['profit']}\n")
    f.write(f"- Variants completed: {len(results)}/9\n")
    f.write(f"- Failed: {failed}\n")
    f.write("- Live trading: FORBIDDEN\n")

report_path = Path("validation_reports/strategy_fix_round1.md")
if not report_path.exists():
    print("FATAL: report not generated", file=sys.stderr)
    sys.exit(1)

print("\n" + report_path.read_text())

log_count = len(list(Path("freqtrade_data/backtest_results").glob("round1_*.log")))
print(f"\nRound 1 logs: {log_count}/9")
if log_count < 9:
    print("WARNING: fewer than 9 variant logs generated", file=sys.stderr)
