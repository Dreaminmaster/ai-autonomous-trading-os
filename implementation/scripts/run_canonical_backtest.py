#!/usr/bin/env python3
"""
Canonical Backtest Runner — single source of truth for all backtest commands.
Each run uses an ISOLATED --user-data-dir to prevent cross-run contamination.
Results are provenance-tracked with SHA256.

Usage:
  python3 scripts/run_canonical_backtest.py <variant_name> <output_base> [policy_path]
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

IMPL_DIR = Path(__file__).resolve().parents[1]
os.chdir(IMPL_DIR)

variant = sys.argv[1]
output_base = sys.argv[2].replace(".json", "")
policy_path = sys.argv[3] if len(sys.argv) > 3 else "config/policy.validation.json"
timerange = os.environ.get("TIMERANGE", "20250101-20250701")

# ── Isolated runtime dir per variant ──────────────────────────
run_id = os.environ.get("GITHUB_RUN_ID", f"local_{int(time.time())}")
isolated_dir = Path(f".runtime/backtests/{run_id}/{output_base}")
results_dir = Path("freqtrade_data/backtest_results")
for d in [isolated_dir, results_dir]:
    d.mkdir(parents=True, exist_ok=True)
# Freqtrade needs user_data structure
for sub in ("strategies", "data", "backtest_results"):
    (isolated_dir / sub).mkdir(parents=True, exist_ok=True)

log_path = results_dir / f"{output_base}.log"
summary_path = results_dir / f"{output_base}_summary.json"
env = os.environ.copy()

# ── Resolve policy ────────────────────────────────────────────
policy_abs = Path(policy_path).resolve()
if not policy_abs.exists():
    print(f"FATAL: policy file not found: {policy_abs}", file=sys.stderr)
    sys.exit(1)
env["ATOS_POLICY"] = str(policy_abs)
policy_sha = hashlib.sha256(policy_abs.read_bytes()).hexdigest()[:12]

# Config SHA
config_abs = Path("freqtrade_data/config.dryrun.json").resolve()
config_sha = hashlib.sha256(config_abs.read_bytes()).hexdigest()[:12]

print(f"Policy: {policy_path} sha256={policy_sha}  Config: sha256={config_sha}")
print(f"Isolated: {isolated_dir}")

# ── Run backtest ──────────────────────────────────────────────
run_started_ns = time.time_ns()
print(f"Backtesting {variant}: {output_base} (run_id={run_id})", flush=True)
t0 = time.time()

result = subprocess.run([
    "freqtrade", "backtesting",
    "--config", str(config_abs),
    "--strategy", "AISupervisedStrategy",
    "--strategy-path", "freqtrade_data/strategies",
    "--datadir", "freqtrade_data/data/okx",
    "--user-data-dir", str(isolated_dir.resolve()),
    "--timerange", timerange,
    "--timeframe", "5m",
    "--cache", "none",
    "--export", "trades",
], capture_output=True, text=True, timeout=900, env=env)

elapsed = time.time() - t0
log_path.write_text(result.stdout + "\n" + result.stderr)

if result.returncode != 0:
    print(f"FATAL: Backtest failed (rc={result.returncode}) in {elapsed:.0f}s", file=sys.stderr)
    print(result.stderr[-800:] if result.stderr else result.stdout[-800:], file=sys.stderr)
    sys.exit(result.returncode)

# ── Find the new JSON in isolated dir ─────────────────────────
json_glob = sorted(
    list((isolated_dir / "backtest_results").glob("backtest-result-*.json"))
    + list((isolated_dir / "backtest_results").glob("backtest-result-*.meta.json")),
    key=lambda p: p.stat().st_mtime,
    reverse=True,
)
actual_json_path = None
for rp in json_glob:
    if "meta" not in rp.name and rp.stat().st_mtime_ns >= run_started_ns:
        actual_json_path = rp
        break

if not actual_json_path:
    print(f"FATAL: No fresh Freqtrade result JSON generated in {isolated_dir}/backtest_results/", file=sys.stderr)
    sys.exit(1)

print(f"  JSON: {actual_json_path.name}")
# Copy to shared results dir
copied_json = results_dir / f"{output_base}.json"
shutil.copy2(actual_json_path, copied_json)

# ── Extract metrics ───────────────────────────────────────────
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
    "run_id": run_id,
    "run_started_at_ns": run_started_ns,
    "source_json_path": str(actual_json_path.resolve()),
    "source_json_mtime_ns": actual_json_path.stat().st_mtime_ns,
    "source_json_sha256": hashlib.sha256(actual_json_path.read_bytes()).hexdigest()[:16],
    "total_trades": trades,
    "profit_total_pct": profit_pct,
    "profit_total": profit_total,
    "winrate": winrate,
    "max_drawdown": max_dd,
    "profit_factor": pf,
    "policy_sha256": policy_sha,
    "config_sha256": config_sha,
    "cache_mode": "none",
    "elapsed_s": elapsed,
}
summary_path.write_text(json.dumps(summary, indent=2))

# ── Lookahead (optional) ──────────────────────────────────────
if os.environ.get("RUN_LOOKAHEAD", "") == "1":
    print(f"  Lookahead for {variant}...", flush=True)
    la_log = results_dir / f"{output_base}_lookahead.log"
    la_result = subprocess.run([
        "freqtrade", "lookahead-analysis",
        "--config", str(config_abs),
        "--strategy", "AISupervisedStrategy",
        "--strategy-path", "freqtrade_data/strategies",
        "--timerange", timerange,
        "--user-data-dir", str(isolated_dir.resolve()),
    ], capture_output=True, text=True, timeout=900, env=env)
    la_log.write_text(la_result.stdout + "\n" + la_result.stderr)
    la_text = la_result.stdout
    if "has_bias" in la_text:
        print(f"  Lookahead: {la_text[la_text.index('has_bias'):la_text.index('has_bias')+20]}")
    else:
        print(f"  Lookahead: could not parse")
