#!/usr/bin/env python3
"""
Strategy Fix Round 1 — 9 variants via canonical backtest runner.
Baseline uses VALIDATION policy. Others apply overrides on top.
Each variant: independent --export JSON + log + policy.
Only best 2 run lookahead. Report: validation_reports/strategy_fix_round1.md
"""
import subprocess, json, os, sys, traceback
from pathlib import Path

os.chdir(Path(__file__).resolve().parents[1])
os.makedirs("freqtrade_data/backtest_results", exist_ok=True)
os.makedirs("validation_reports", exist_ok=True)

TIMEOUT = 900
VALIDATION_POLICY = "config/policy.validation.json"
# Validate baseline = fresh run from validation policy
BASELINE_OUT = "round1_1_baseline_current"

VARIANTS = [
    (BASELINE_OUT, None),
    ("round1_2_trend_weight_025_only", {"experiment.strategy_weights.trend_following_v1": 0.25}),
    ("round1_3_trend_disabled_only", {"experiment.disabled_strategies": ["trend_following_v1"]}),
    ("round1_4_max_hold_6h_only", {"experiment.max_holding_minutes": 360}),
    ("round1_5_max_hold_4h_only", {"experiment.max_holding_minutes": 240}),
    ("round1_6_trend_025_hold_6h", {"experiment.strategy_weights.trend_following_v1": 0.25, "experiment.max_holding_minutes": 360}),
    ("round1_7_trend_disabled_hold_6h", {"experiment.disabled_strategies": ["trend_following_v1"], "experiment.max_holding_minutes": 360}),
    ("round1_8_trend_025_early_exit", {"experiment.strategy_weights.trend_following_v1": 0.25, "experiment.max_holding_minutes": 360, "experiment.early_exit_loss_pct": -0.3, "experiment.early_exit_after_minutes": 120}),
    ("round1_9_trend_disabled_early_exit", {"experiment.disabled_strategies": ["trend_following_v1"], "experiment.max_holding_minutes": 360, "experiment.early_exit_loss_pct": -0.3, "experiment.early_exit_after_minutes": 120}),
]

def apply_overrides(policy, overrides):
    p = json.loads(json.dumps(policy))
    if not overrides: return p
    for k, v in overrides.items():
        target = p
        for part in k.split(".")[:-1]:
            if part not in target: target[part] = {}
            target = target[part]
        target[k.split(".")[-1]] = v
    return p

def write_policy_and_run(name, policy, env):
    """Write policy file, run canonical backtest, return summary path."""
    policy_path = Path(f"freqtrade_data/backtest_results/exp_{name}_policy.json")
    policy_path.write_text(json.dumps(policy, indent=2))
    env = env.copy()
    env["ATOS_POLICY"] = str(policy_path.resolve())

    print(f"  [{name}] running...", flush=True)
    try:
        result = subprocess.run([
            "freqtrade", "backtesting",
            "--config", "freqtrade_data/config.dryrun.json",
            "--strategy", "AISupervisedStrategy",
            "--strategy-path", "freqtrade_data/strategies",
            "--datadir", "freqtrade_data/data/okx",
            "--timerange", os.environ.get("TIMERANGE", "20250101-20250701"),
            "--timeframe", "5m",
            "--cache", "none",
            "--export", "trades",
            "--export-filename", f"freqtrade_data/backtest_results/{name}.json",
        ], capture_output=True, text=True, timeout=TIMEOUT, env=env)
        log_path = Path(f"freqtrade_data/backtest_results/{name}.log")
        log_path.write_text(result.stdout + "\n" + result.stderr)
        if result.returncode != 0:
            return {"name": name, "status": f"FAILED(rc={result.returncode})", "trades": "?", "profit": "?", "dd": "?"}
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "TIMEOUT", "trades": "?", "profit": "?", "dd": "?"}
    except Exception as e:
        return {"name": name, "status": f"CRASH:{e}", "trades": "?", "profit": "?", "dd": "?"}

    # Parse JSON result
    json_path = Path(f"freqtrade_data/backtest_results/{name}.json")
    try:
        data = json.loads(json_path.read_text())
        s = data.get("strategy", data.get("strategy_comparison", [{}])[0])
        return {"name": name, "status": "OK",
                "trades": s.get("total_trades", "?"),
                "profit": s.get("profit_total_pct", s.get("profit_total", "?")),
                "dd": s.get("max_drawdown", s.get("max_drawdown_account", "?")),
                "winrate": s.get("winrate", "?"),
                "profit_factor": s.get("profit_factor", "?"),
                "summary_path": f"freqtrade_data/backtest_results/{name}_summary.json"}
    except Exception as e:
        return {"name": name, "status": f"PARSE_ERROR:{e}", "trades": "?", "profit": "?", "dd": "?"}

# ════════════════════════════════════════
# Run all 9
# ════════════════════════════════════════
base_env = os.environ.copy()
base_policy = json.loads(open(VALIDATION_POLICY).read())
results = []
for name, overrides in VARIANTS:
    if overrides is None:
        policy = base_policy  # untouched validation policy
    else:
        policy = apply_overrides(base_policy, overrides)
    r = write_policy_and_run(name, policy, base_env)
    results.append(r)

# ════════════════════════════════════════
# Best 2 lookahead
# ════════════════════════════════════════
ok_results = [r for r in results if r["status"] == "OK"]
ok_results.sort(key=lambda r: float(str(r["profit"]).replace("%","").replace("?","-999")))
best_two = ok_results[-2:] if len(ok_results) >= 2 else ok_results

for b in best_two:
    name = b["name"]
    print(f"  Lookahead: {name} ...", flush=True)
    try:
        result = subprocess.run([
            "freqtrade", "lookahead-analysis",
            "--config", "freqtrade_data/config.dryrun.json",
            "--strategy", "AISupervisedStrategy",
            "--strategy-path", "freqtrade_data/strategies",
            "--timerange", os.environ.get("TIMERANGE", "20250101-20250701"),
        ], capture_output=True, text=True, timeout=TIMEOUT, env={"ATOS_POLICY": str(Path(f"freqtrade_data/backtest_results/exp_{name}_policy.json").resolve())})
        Path(f"freqtrade_data/backtest_results/{name}_lookahead.log").write_text(result.stdout + "\n" + result.stderr)
        b["lookahead"] = "PASS" if "has_bias" in result.stdout and "No" in result.stdout.split("has_bias")[-1][:5] else "?"
    except Exception:
        b["lookahead"] = "?"

# ════════════════════════════════════════
# Report
# ════════════════════════════════════════
baseline = results[0]
canonical_json = "freqtrade_data/backtest_results/canonical_baseline.json"
cb_trades = "?"
if Path(canonical_json).exists():
    try:
        cb = json.loads(Path(canonical_json).read_text())
        s = cb.get("strategy", cb.get("strategy_comparison", [{}])[0])
        cb_trades = s.get("total_trades", "?")
    except: pass

with open("validation_reports/strategy_fix_round1.md", "w") as f:
    f.write("# Strategy Fix Round 1\n\n")
    f.write(f"**Timerange:** {os.environ.get('TIMERANGE','20250101-20250701')} | **Pair:** BTC/USDT 5m\n\n")
    f.write("## Canonical Baseline\n\n")
    f.write(f"- Canonical fresh: {cb_trades} trades\n")
    f.write(f"- Round1 baseline: {baseline.get('trades','?')} trades / {baseline.get('profit','?')}%\n")
    match = (str(cb_trades) == str(baseline.get("trades",""))) and "OK" in baseline.get("status","")
    f.write(f"- Baseline integrity: {'PASS' if match else 'FAIL (canonical ≠ round1 baseline)'}\n\n")
    f.write("## Variant Matrix\n\n")
    f.write("| # | Variant | Status | Trades | Profit % | Winrate | Max DD | Profit Factor | Lookahead |\n")
    f.write("|---|---------|--------|--------|----------|---------|--------|---------------|-----------|\n")
    for i, r in enumerate(results):
        f.write(f"| {i+1} | {r['name']} | {r['status']} | {r.get('trades','?')} | {r.get('profit','?')} | {r.get('winrate','?')} | {r.get('dd','?')} | {r.get('profit_factor','?')} | {r.get('lookahead','?')} |\n")
    f.write(f"\n## Best 2\n\n")
    for b in best_two:
        f.write(f"- **{b['name']}**: {b.get('trades','?')} trades, {b.get('profit','?')}%, WR {b.get('winrate','?')}, LA {b.get('lookahead','?')}\n")
    f.write("\n## Conclusion\n\n- Live trading: FORBIDDEN\n")

print(Path("validation_reports/strategy_fix_round1.md").read_text())
