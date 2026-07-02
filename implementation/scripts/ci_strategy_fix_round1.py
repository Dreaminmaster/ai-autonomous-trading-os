#!/usr/bin/env python3
"""Strategy Fix Round 1 — A/B matrix testing of 9 strategy variants.

Each variant is one backtest run. Reports go to validation_reports/strategy_fix_round1.md.
Configuration via policy.experiment_round1.json + overrides per variant.
"""
import subprocess, json, os, sys, time as _time
from pathlib import Path

os.makedirs("freqtrade_data/backtest_results", exist_ok=True)
os.makedirs("validation_reports", exist_ok=True)

TIMERANGE = os.environ.get("TIMERANGE", "20250101-20250701")
PAIR = os.environ.get("PAIR", "BTC/USDT")

BASE_POLICY = json.loads(Path("config/policy.experiment_round1.json").read_text())

# ── Variant definitions ───────────────────────────────────────
VARIANTS = [
    ("1_baseline_current", {}),
    ("2_trend_weight_025", {
        "experiment.strategy_weights.trend_following_v1": 0.25,
    }),
    ("3_trend_disabled", {
        "experiment.disabled_strategies": ["trend_following_v1"],
    }),
    ("4_max_hold_6h", {
        "experiment.max_holding_minutes": 360,
    }),
    ("5_max_hold_4h", {
        "experiment.max_holding_minutes": 240,
    }),
    ("6_trend_025_hold_6h", {
        "experiment.strategy_weights.trend_following_v1": 0.25,
        "experiment.max_holding_minutes": 360,
    }),
    ("7_trend_disabled_hold_6h", {
        "experiment.disabled_strategies": ["trend_following_v1"],
        "experiment.max_holding_minutes": 360,
    }),
    ("8_trend_025_early_exit", {
        "experiment.strategy_weights.trend_following_v1": 0.25,
        "experiment.max_holding_minutes": 360,
        "experiment.early_exit_loss_pct": -0.3,
        "experiment.early_exit_after_minutes": 120,
    }),
    ("9_trend_disabled_early_exit", {
        "experiment.disabled_strategies": ["trend_following_v1"],
        "experiment.max_holding_minutes": 360,
        "experiment.early_exit_loss_pct": -0.3,
        "experiment.early_exit_after_minutes": 120,
    }),
]


def apply_overrides(policy, overrides):
    """Apply dot-path overrides to policy dict."""
    policy = json.loads(json.dumps(policy))  # deep copy
    for key, value in overrides.items():
        parts = key.split(".")
        target = policy
        for p in parts[:-1]:
            if p not in target:
                target[p] = {}
            target = target[p]
        target[parts[-1]] = value
    return policy


def run_backtest(variant_name, policy, pair):
    """Run one freqtrade backtest, return extracted metrics."""
    policy_path = f"freqtrade_data/backtest_results/exp_{variant_name}_policy.json"
    Path(policy_path).write_text(json.dumps(policy))

    log = f"freqtrade_data/backtest_results/exp_{variant_name}.log"
    env = os.environ.copy()
    env["ATOS_POLICY"] = policy_path

    print(f"  Running {variant_name} on {pair} ...", flush=True)
    t0 = _time.time()
    subprocess.run([
        "freqtrade", "backtesting",
        "--config", "freqtrade_data/config.dryrun.json",
        "--strategy", "AISupervisedStrategy",
        "--strategy-path", "freqtrade_data/strategies",
        "--datadir", "freqtrade_data/data/okx",
        "--timerange", TIMERANGE,
        "--timeframe", "5m",
        "--pairs", pair,
    ], check=False, stdout=open(log, "w"), stderr=subprocess.STDOUT, env=env)
    elapsed = _time.time() - t0
    print(f"  Done in {elapsed:.0f}s", flush=True)

    text = open(log).read()

    # Extract STRATEGY SUMMARY line
    trades = winrate = profit = dd = "?"
    for line in text.split("\n"):
        if "AISupervisedStrategy" in line and "\u2502" in line and "TOTAL" not in line:
            parts = [p.strip() for p in line.split("\u2502")]
            if len(parts) >= 8:
                trades = parts[2].strip()
                profit = parts[5].strip()
                dd = parts[8].strip() if len(parts) > 8 else "-"
                winstat = parts[7].strip()
    # winrate is last token in winstat
    if trades == "0":
        profit = "0.0"
        dd = "0 USDT  0.00%"

    # Lookahead check
    la_log = f"freqtrade_data/backtest_results/exp_la_{variant_name}.log"
    subprocess.run([
        "freqtrade", "lookahead-analysis",
        "--config", "freqtrade_data/config.dryrun.json",
        "--strategy", "AISupervisedStrategy",
        "--strategy-path", "freqtrade_data/strategies",
        "--timerange", TIMERANGE,
    ], check=False, stdout=open(la_log, "w"), stderr=subprocess.STDOUT, env=env)
    la_text = open(la_log).read()
    la_status = "PASS" if "has_bias" in la_text and "No" in la_text.split("has_bias")[-1][:5] else "CHECK"
    if "too few trades" in la_text:
        la_status = "TOO_FEW"

    return {
        "variant": variant_name,
        "trades": trades,
        "profit": profit,
        "dd": dd,
        "lookahead": la_status,
    }


# ═══════════════════════════════════════════════════════════
# Run all variants
# ═══════════════════════════════════════════════════════════
results = []

for variant_name, overrides in VARIANTS:
    policy = apply_overrides(BASE_POLICY, overrides)
    result = run_backtest(variant_name, policy, PAIR)
    results.append(result)

# ═══════════════════════════════════════════════════════════
# Write report
# ═══════════════════════════════════════════════════════════
with open("validation_reports/strategy_fix_round1.md", "w") as f:
    f.write("# Strategy Fix Round 1\n\n")
    f.write(f"**Timerange:** {TIMERANGE} | **Pair:** {PAIR} 5m\n\n")
    f.write("| # | Variant | Trades | Profit % | Max DD % | Lookahead | vs Baseline |\n")
    f.write("|---|---------|--------|----------|----------|-----------|-------------|\n")

    baseline_profit_str = results[0]["profit"] if results else "-16.12"
    try:
        baseline_profit = float(baseline_profit_str.replace("%", "")) if results else -16.12
    except:
        baseline_profit = -16.12

    best = None

    for r in results:
        profit_str = r["profit"]
        dd_str = r["dd"]
        try:
            profit_val = float(profit_str.replace("%", ""))
        except:
            profit_val = -99.0
        delta = profit_val - baseline_profit
        vs = f"{delta:+.2f}%" if isinstance(delta, (int, float)) else "?"

        f.write(f"| {r['variant']} | {r['trades']} | {profit_str} | {dd_str} | {r['lookahead']} | {vs} |\n")

        if best is None or profit_val > best[1]:
            best = (r, profit_val)

f.write("\n## Best Variant\n\n")
if best:
    f.write(f"**{best[0]['variant']}: {best[0]['profit']} profit, {best[0]['trades']} trades, DD {best[0]['dd']}**\n\n")

f.write("## Conclusion\n\n")
f.write(f"- Baseline: {baseline_profit_str}\n")
f.write(f"- All variants must have lookahead PASS\n")
f.write(f"- Live trading: FORBIDDEN\n")

print("\n═══════════════════════════════")
print("Round 1 Results")
print("═══════════════════════════════")
print(open("validation_reports/strategy_fix_round1.md").read())
