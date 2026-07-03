#!/usr/bin/env python3
"""
Canonical Backtest Runner — single source of truth for all backtest commands.
Usage:
  python3 scripts/run_canonical_backtest.py <variant_name> <output_json> [--policy PATH]

Outputs:
  freqtrade_data/backtest_results/<output_json>.json
  freqtrade_data/backtest_results/<output_json>.log

All callers (main backtest, Round 1 baseline, Round 1 variants) use this.
"""
import subprocess, json, os, sys, time
from pathlib import Path

IMPL_DIR = Path(__file__).resolve().parents[1]
os.chdir(IMPL_DIR)

variant = sys.argv[1]
output_base = sys.argv[2].replace(".json", "")
policy_path = sys.argv[3] if len(sys.argv) > 3 else "config/policy.validation.json"
timerange = os.environ.get("TIMERANGE", "20250101-20250701")

log_path = Path(f"freqtrade_data/backtest_results/{output_base}.log")
json_path = Path(f"freqtrade_data/backtest_results/{output_base}.json")
env = os.environ.copy()

if policy_path:
    policy_abs = Path(policy_path).resolve()
    env["ATOS_POLICY"] = str(policy_abs)
    if not policy_abs.exists():
        print(f"ERROR: policy not found: {policy_abs}", file=sys.stderr)
        sys.exit(1)
    policy_sha = hashlib.sha256(policy_abs.read_bytes()).hexdigest()[:12]
    print(f"Policy: {policy_path} sha256={policy_sha}")

print(f"Backtesting {variant}: {output_base}.json", flush=True)
t0 = time.time()

result = subprocess.run([
    "freqtrade", "backtesting",
    "--config", "freqtrade_data/config.dryrun.json",
    "--strategy", "AISupervisedStrategy",
    "--strategy-path", "freqtrade_data/strategies",
    "--datadir", "freqtrade_data/data/okx",
    "--timerange", timerange,
    "--timeframe", "5m",
    "--cache", "none",
    "--export", "trades",
    "--export-filename", str(json_path),
], capture_output=True, text=True, timeout=900, env=env)

elapsed = time.time() - t0
log_path.write_text(result.stdout + "\n" + result.stderr)

if result.returncode != 0:
    print(f"Backtest FAILED (rc={result.returncode}) in {elapsed:.0f}s", file=sys.stderr)
    sys.exit(result.returncode)

# Extract key metrics from JSON
try:
    data = json.loads(json_path.read_text())
    strat = data.get("strategy", data.get("strategy_comparison", [{}])[0])
    trades = strat.get("total_trades", "?")
    profit_pct = strat.get("profit_total_pct", strat.get("profit_total", "?"))
    profit_total = strat.get("profit_total", strat.get("profit_total_pct", "?"))
    winrate = strat.get("winrate", "?")
    max_dd = strat.get("max_drawdown", strat.get("max_drawdown_account", "?"))
    pf = strat.get("profit_factor", "?")
    print(f"  trades={trades} profit={profit_pct}% winrate={winrate} maxDD={max_dd} pf={pf}")
    print(f"  elapsed={elapsed:.0f}s")
    # Write summary
    summary = {
        "variant": variant,
        "total_trades": trades,
        "profit_total_pct": profit_pct,
        "profit_total": profit_total,
        "winrate": winrate,
        "max_drawdown": max_dd,
        "profit_factor": pf,
        "policy_sha256": policy_sha,
        "elapsed_s": elapsed
    }
    Path(f"freqtrade_data/backtest_results/{output_base}_summary.json").write_text(json.dumps(summary, indent=2))
except Exception as e:
    print(f"  WARNING: could not parse JSON result: {e}")

# Lookahead (only if requested via env var)
if os.environ.get("RUN_LOOKAHEAD", "") == "1":
    print(f"  Lookahead for {variant}...", flush=True)
    la_log = Path(f"freqtrade_data/backtest_results/{output_base}_lookahead.log")
    la_result = subprocess.run([
        "freqtrade", "lookahead-analysis",
        "--config", "freqtrade_data/config.dryrun.json",
        "--strategy", "AISupervisedStrategy",
        "--strategy-path", "freqtrade_data/strategies",
        "--timerange", timerange,
    ], capture_output=True, text=True, timeout=900, env=env)
    la_log.write_text(la_result.stdout + "\n" + la_result.stderr)
    la_text = la_result.stdout
    if "has_bias" in la_text:
        bias_line = la_text[la_text.index("has_bias"):la_text.index("has_bias")+20]
        print(f"  Lookahead: {bias_line}")
    else:
        print(f"  Lookahead: could not parse")
