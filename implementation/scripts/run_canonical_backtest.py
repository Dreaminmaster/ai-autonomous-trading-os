#!/usr/bin/env python3
"""
Canonical Backtest Runner — single source of truth for all backtest commands.
Usage:
  python3 scripts/run_canonical_backtest.py <variant_name> <output_base> [policy_path]

Outputs:
  freqtrade_data/backtest_results/<output_base>.json
  freqtrade_data/backtest_results/<output_base>.log
  freqtrade_data/backtest_results/<output_base>_summary.json
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

IMPL_DIR = Path(__file__).resolve().parents[1]
os.chdir(IMPL_DIR)

# Ensure output dirs
results_dir = Path("freqtrade_data/backtest_results")
results_dir.mkdir(parents=True, exist_ok=True)
Path("user_data/backtest_results").mkdir(parents=True, exist_ok=True)

variant = sys.argv[1]
output_base = sys.argv[2].replace(".json", "")
policy_path = sys.argv[3] if len(sys.argv) > 3 else "config/policy.validation.json"
timerange = os.environ.get("TIMERANGE", "20250101-20250701")

log_path = Path(f"freqtrade_data/backtest_results/{output_base}.log")
json_path = Path(f"user_data/backtest_results/backtest-result.json")  # Freqtrade writes here
summary_path = Path(f"freqtrade_data/backtest_results/{output_base}_summary.json")
env = os.environ.copy()

# Resolve policy
policy_sha = "none"
policy_abs = Path(policy_path).resolve()
if not policy_abs.exists():
    print(f"FATAL: policy file not found: {policy_abs}", file=sys.stderr)
    sys.exit(1)
env["ATOS_POLICY"] = str(policy_abs)
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
], capture_output=True, text=True, timeout=900, env=env)

elapsed = time.time() - t0
log_path.write_text(result.stdout + "\n" + result.stderr)

if result.returncode != 0:
    print(f"FATAL: Backtest failed (rc={result.returncode}) in {elapsed:.0f}s", file=sys.stderr)
    print(result.stderr[-500:] if result.stderr else result.stdout[-500:], file=sys.stderr)
    sys.exit(result.returncode)

# ── Find Freqtrade output JSON (written to user_data/) ─────────
results_glob = sorted(Path("user_data/backtest_results").glob("backtest-result-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
actual_json_path = None
for rp in results_glob:
    if "meta" not in rp.name:
        actual_json_path = rp
        break

if not actual_json_path:
    print(f"FATAL: No Freqtrade result JSON found in user_data/backtest_results/", file=sys.stderr)
    sys.exit(1)

print(f"  JSON: {actual_json_path.name}")
# Copy to our output dir
import shutil
shutil.copy2(actual_json_path, Path(f"freqtrade_data/backtest_results/{output_base}.json"))

# ── Extract metrics from JSON (fail-fast) ──────────────────────
try:
    data = json.loads(actual_json_path.read_text())
except json.JSONDecodeError as e:
    print(f"FATAL: Cannot parse JSON: {e}", file=sys.stderr)
    sys.exit(1)

strat = data.get("strategy", data.get("strategy_comparison", [{}]))
if isinstance(strat, list):
    strat = strat[0] if strat else {}
if not strat:
    print(f"FATAL: No strategy result in JSON", file=sys.stderr)
    sys.exit(1)

trades = strat.get("total_trades", "?")
profit_pct = strat.get("profit_total_pct", strat.get("profit_total", "?"))
profit_total = strat.get("profit_total", strat.get("profit_total_pct", "?"))
winrate = strat.get("winrate", "?")
max_dd = strat.get("max_drawdown", strat.get("max_drawdown_account", "?"))
pf = strat.get("profit_factor", "?")

print(f"  trades={trades} profit={profit_pct}% winrate={winrate} maxDD={max_dd} pf={pf}")
print(f"  elapsed={elapsed:.0f}s")

summary = {
    "variant": variant,
    "total_trades": trades,
    "profit_total_pct": profit_pct,
    "profit_total": profit_total,
    "winrate": winrate,
    "max_drawdown": max_dd,
    "profit_factor": pf,
    "policy_sha256": policy_sha,
    "elapsed_s": elapsed,
}
summary_path.write_text(json.dumps(summary, indent=2))

# ── Lookahead (optional, only if RUN_LOOKAHEAD=1) ──────────────
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
        print(f"  Lookahead: {la_text[la_text.index('has_bias'):la_text.index('has_bias')+20]}")
    else:
        print(f"  Lookahead: could not parse")
