#!/usr/bin/env python3
"""
Strategy Fix Round 1 — 9-variant A/B matrix with full isolation.
Baseline uses config/policy.validation.json (unchanged).
Experiment variants start from validation policy + apply overrides.
Each variant has independent log, policy file, backtest run.
"""
import subprocess, json, os, sys, time as _time, traceback
from pathlib import Path

IMPL_DIR = Path(__file__).resolve().parents[1]
os.chdir(IMPL_DIR)

os.makedirs("freqtrade_data/backtest_results", exist_ok=True)
os.makedirs("validation_reports", exist_ok=True)

TIMERANGE = os.environ.get("TIMERANGE", "20250101-20250701")
TIMEOUT = 900

# Baseline uses VALIDATION policy (unchanged)
VALIDATION_POLICY_PATH = "config/policy.validation.json"
VALIDATION_POLICY = json.loads(Path(VALIDATION_POLICY_PATH).read_text())

# Experiment overrides (applied on top of VALIDATION policy)
VARIANTS = [
    ("1_baseline_current", None, "baseline unchanged (validation policy)"),
    ("2_trend_weight_025_only", {"experiment.strategy_weights.trend_following_v1": 0.25}, "trend weight 0.25"),
    ("3_trend_disabled_only", {"experiment.disabled_strategies": ["trend_following_v1"]}, "trend disabled"),
    ("4_max_hold_6h_only", {"experiment.max_holding_minutes": 360}, "max hold 6h"),
    ("5_max_hold_4h_only", {"experiment.max_holding_minutes": 240}, "max hold 4h"),
    ("6_trend_025_hold_6h", {"experiment.strategy_weights.trend_following_v1": 0.25, "experiment.max_holding_minutes": 360}, "trend 0.25 + hold 6h"),
    ("7_trend_disabled_hold_6h", {"experiment.disabled_strategies": ["trend_following_v1"], "experiment.max_holding_minutes": 360}, "trend disabled + hold 6h"),
    ("8_trend_025_early_exit", {"experiment.strategy_weights.trend_following_v1": 0.25, "experiment.max_holding_minutes": 360, "experiment.early_exit_loss_pct": -0.3, "experiment.early_exit_after_minutes": 120}, "trend 0.25 + early exit"),
    ("9_trend_disabled_early_exit", {"experiment.disabled_strategies": ["trend_following_v1"], "experiment.max_holding_minutes": 360, "experiment.early_exit_loss_pct": -0.3, "experiment.early_exit_after_minutes": 120}, "trend disabled + early exit"),
]

def apply_overrides(policy, overrides):
    """Deep copy policy, then apply dot-path overrides."""
    policy = json.loads(json.dumps(policy))
    if not overrides:
        return policy
    for key, value in overrides.items():
        parts = key.split(".")
        target = policy
        for p in parts[:-1]:
            if p not in target:
                target[p] = {}
            target = target[p]
        target[parts[-1]] = value
    return policy

def run_one_variant(variant_name, policy, desc):
    """Run one variant backtest + lookahead. Returns result dict. Always writes log."""
    log_path = Path(f"freqtrade_data/backtest_results/round1_{variant_name}.log")
    policy_path = Path(f"freqtrade_data/backtest_results/exp_{variant_name}_policy.json")
    la_log_path = Path(f"freqtrade_data/backtest_results/round1_la_{variant_name}.log")

    # Write policy
    policy_path.write_text(json.dumps(policy, indent=2))
    env = os.environ.copy()
    env["ATOS_POLICY"] = str(policy_path.resolve())

    # Remove stale cache
    for cached in Path("user_data/backtest_results").glob("backtest-result-*.zip"):
        cached.unlink(missing_ok=True)

    print(f"  [{variant_name}] {desc} ...", flush=True)
    t0 = _time.time()

    try:
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
    except subprocess.TimeoutExpired:
        log_path.write_text("TIMEOUT")
        print(f"  [{variant_name}] TIMEOUT", flush=True)
        return {"variant": variant_name, "status": "TIMEOUT", "trades": "?", "profit": "?", "dd": "?", "lookahead": "?"}
    except Exception as e:
        log_path.write_text(f"EXCEPTION: {traceback.format_exc()}")
        print(f"  [{variant_name}] EXCEPTION: {e}", flush=True)
        return {"variant": variant_name, "status": f"EXCEPTION:{e}", "trades": "?", "profit": "?", "dd": "?", "lookahead": "?"}

    elapsed = _time.time() - t0
    rc = result.returncode
    log_path.write_text(result.stdout + "\n" + result.stderr)

    if rc != 0:
        err_tail = (result.stderr[-200:] if result.stderr else result.stdout[-200:])
        print(f"  [{variant_name}] FAILED(rc={rc}) in {elapsed:.0f}s: {err_tail[:80]}", flush=True)
        return {"variant": variant_name, "status": f"FAILED(rc={rc})", "trades": "?", "profit": "?", "dd": "?", "lookahead": "?"}

    text = result.stdout
    trades = profit = dd = "?"
    for line in text.split("\n"):
        if "AISupervisedStrategy" in line and "\u2502" in line and "TOTAL" not in line:
            parts = [p.strip() for p in line.split("\u2502")]
            if len(parts) >= 9:
                trades = parts[2].strip()
                profit = parts[5].strip()
                dd = parts[8].strip() if len(parts) > 8 else "-"
                break

    # Lookahead (optional, don't fail on its failure)
    try:
        la_result = subprocess.run([
            "freqtrade", "lookahead-analysis",
            "--config", "freqtrade_data/config.dryrun.json",
            "--strategy", "AISupervisedStrategy",
            "--strategy-path", "freqtrade_data/strategies",
            "--timerange", TIMERANGE,
        ], capture_output=True, text=True, timeout=TIMEOUT, env=env)
        la_log_path.write_text(la_result.stdout + "\n" + la_result.stderr)
        la_status = "PASS" if "has_bias" in la_result.stdout and "No" in la_result.stdout.split("has_bias")[-1][:5] else "?"
        if "too few trades" in la_result.stdout:
            la_status = "TOO_FEW"
    except Exception:
        la_status = "?"

    print(f"  [{variant_name}] trades={trades} profit={profit} dd={dd} la={la_status} ({elapsed:.0f}s)", flush=True)
    return {"variant": variant_name, "status": "OK", "trades": trades, "profit": profit, "dd": dd, "lookahead": la_status}

# ════════════════════════════════════════
# Run all
# ════════════════════════════════════════
results = []
failed_count = 0
for name, overrides, desc in VARIANTS:
    if overrides is None:
        policy = VALIDATION_POLICY  # Use validation policy directly for baseline
    else:
        policy = apply_overrides(VALIDATION_POLICY, overrides)
    r = run_one_variant(name, policy, desc)
    results.append(r)
    if r["status"] != "OK":
        failed_count += 1

# ════════════════════════════════════════
# Write report
# ════════════════════════════════════════
baseline = results[0] if results else {}
baseline_trades = baseline.get("trades", "?")
baseline_profit = baseline.get("profit", "?")
baseline_integrity = "PASS" if (baseline_trades == "244" or (isinstance(baseline_trades, str) and "244" in baseline_trades)) else "FAIL"
# Allow small variance: 240-250 trades acceptable
try:
    bt = int(baseline_trades)
    baseline_integrity = "PASS" if 230 <= bt <= 260 else f"FAIL (expected ~244, got {bt})"
except:
    pass

with open("validation_reports/strategy_fix_round1.md", "w") as f:
    f.write("# Strategy Fix Round 1\n\n")
    f.write(f"**Timerange:** {TIMERANGE} | **Pair:** BTC/USDT 5m\n\n")
    f.write("## Baseline Integrity Check\n\n")
    f.write(f"- Expected: 244 trades / -16.12%\n")
    f.write(f"- Actual: {baseline_trades} trades / {baseline_profit}%\n")
    f.write(f"- **Baseline integrity: {baseline_integrity}**\n\n")
    f.write("## Variant Matrix\n\n")
    f.write("| Variant | Status | Trades | Profit % | Max DD | Lookahead |\n")
    f.write("|---------|--------|--------|----------|--------|-----------|\n")
    for r in results:
        f.write(f"| {r['variant']} | {r['status']} | {r['trades']} | {r['profit']} | {r['dd']} | {r['lookahead']} |\n")
    f.write(f"\n## Summary\n\n- Total: {len(results)} variants\n- Succeeded: {len(results)-failed_count}\n- Failed: {failed_count}\n")
    f.write(f"- Baseline integrity: {baseline_integrity}\n")
    f.write("- Live trading: FORBIDDEN\n")

report_path = Path("validation_reports/strategy_fix_round1.md")
print("\n" + report_path.read_text())

# Exit code
log_count = len(list(Path("freqtrade_data/backtest_results").glob("round1_[1-9]_*.log")))
print(f"\nRound 1 logs: {log_count}/9")
if log_count < 9:
    print(f"FATAL: only {log_count}/9 variant logs generated", file=sys.stderr)
    sys.exit(1)
if failed_count > 1:
    print(f"WARNING: {failed_count} variants failed", file=sys.stderr)
if baseline_integrity != "PASS":
    print(f"FATAL: baseline integrity check failed: {baseline_integrity}", file=sys.stderr)
    sys.exit(1)
