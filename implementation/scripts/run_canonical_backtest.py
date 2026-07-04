#!/usr/bin/env python3
"""
Canonical Backtest Runner — isolated per-variant, zip archive result parsing.

Freqtrade 2026.6 writes results as:
  backtest-result-<ts>.meta.json   (metadata only — NOT full result)
  backtest-result-<ts>.zip         (archive containing actual JSON)

This runner extracts the archive JSON for structured metrics.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

IMPL_DIR = Path(__file__).resolve().parents[1]
os.chdir(IMPL_DIR)

variant = sys.argv[1]
output_base = sys.argv[2].replace(".json", "")
policy_path = sys.argv[3] if len(sys.argv) > 3 else "config/policy.validation.json"
timerange = os.environ.get("TIMERANGE", "20250101-20250701")

run_id = os.environ.get("GITHUB_RUN_ID", f"local_{int(time.time())}")
isolated_dir = Path(f".runtime/backtests/{run_id}/{output_base}")
results_dir = Path("freqtrade_data/backtest_results")
for d in [isolated_dir, results_dir]:
    d.mkdir(parents=True, exist_ok=True)
for sub in ("strategies", "data", "backtest_results"):
    (isolated_dir / sub).mkdir(parents=True, exist_ok=True)

log_path = results_dir / f"{output_base}.log"
summary_path = results_dir / f"{output_base}_summary.json"
env = os.environ.copy()

policy_abs = Path(policy_path).resolve()
if not policy_abs.exists():
    print(f"FATAL: policy file not found: {policy_abs}", file=sys.stderr)
    sys.exit(1)
env["ATOS_POLICY"] = str(policy_abs)
env["ATOS_TELEMETRY_PATH"] = str(results_dir / f"{output_base}_telemetry.json")
try:
    policy_sha = hashlib.sha256(policy_abs.read_bytes()).hexdigest()[:12]
except Exception:
    policy_sha = "none"

config_abs = Path("freqtrade_data/config.dryrun.json").resolve()
config_sha = "none"
if config_abs.exists():
    config_sha = hashlib.sha256(config_abs.read_bytes()).hexdigest()[:12]

print(f"Policy: {policy_path} sha256={policy_sha}  Config: sha256={config_sha}")
print(f"Isolated: {isolated_dir}")

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
    "--pairs", "BTC/USDT",
], capture_output=True, text=True, timeout=900, env=env)

elapsed = time.time() - t0
log_path.write_text(result.stdout + "\n" + result.stderr)

if result.returncode != 0:
    print(f"FATAL: Backtest failed (rc={result.returncode}) in {elapsed:.0f}s", file=sys.stderr)
    print(result.stderr[-800:] if result.stderr else result.stdout[-800:], file=sys.stderr)
    sys.exit(result.returncode)

# ── Recursively list isolated results dir for diagnosis ────────
results_subdir = isolated_dir / "backtest_results"
all_files = sorted(results_subdir.rglob("*"), key=lambda p: (p.is_file(), p.stat().st_mtime))
print(f"  Isolated results ({len(all_files)} entries):")
for f in all_files:
    if f.is_file():
        print(f"    {f.relative_to(isolated_dir)} size={f.stat().st_size} mtime_ns={f.stat().st_mtime_ns}")

# ── Find the result: check .zip archives first, then .json ─────
zip_files = sorted(results_subdir.glob("backtest-result-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
actual_json_path = None
source_type = "?"

# Strategy 1: zip archives
for zf in zip_files:
    if zf.stat().st_mtime_ns >= run_started_ns:
        try:
            with zipfile.ZipFile(zf) as zz:
                names = zz.namelist()
                for name in names:
                    if name.endswith(".json") and "meta" not in name.lower():
                        jtext = zz.read(name).decode("utf-8")
                        data = json.loads(jtext)
                        actual_json_path = zf
                        source_type = "zip"
                        break
            if actual_json_path:
                break
        except Exception as e:
            print(f"  zip parse failed for {zf.name}: {e}")

# Strategy 2: plain .json (not .meta.json)
if not actual_json_path:
    json_files = sorted(results_subdir.glob("backtest-result-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for jf in json_files:
        if "meta" not in jf.name.lower() and jf.stat().st_mtime_ns >= run_started_ns:
            try:
                data = json.loads(jf.read_text())
                actual_json_path = jf
                source_type = "json"
                break
            except json.JSONDecodeError:
                pass

if not actual_json_path:
    print(f"FATAL: No fresh Freqtrade result (zip or json) found in {results_subdir}", file=sys.stderr)
    print(f"  zip files: {[z.name for z in zip_files]}", file=sys.stderr)
    sys.exit(1)

print(f"  Result: {actual_json_path.name} type={source_type}")

# Copy to shared results dir
copied_json = results_dir / f"{output_base}.json"
shutil.copy2(actual_json_path, copied_json)

# ── Extract metrics ────────────────────────────────────────────
# P0: Freqtrade 2026.6 nests under strategy/{StrategyName}/ or strategy_comparison/[]
strategy_container = data.get("strategy", data.get("strategy_comparison", None))

if isinstance(strategy_container, dict):
    if "AISupervisedStrategy" in strategy_container:
        strat = strategy_container["AISupervisedStrategy"]
    elif len(strategy_container) == 1:
        strat = next(iter(strategy_container.values()))
    elif "total_trades" in strategy_container:
        strat = strategy_container
    elif not strategy_container:
        strat = data if "total_trades" in data else {}
    else:
        strat = {}
elif isinstance(strategy_container, list) and len(strategy_container) > 0:
    strat = strategy_container[0]
else:
    strat = data if "total_trades" in data else {}

if not strat or "total_trades" not in strat:
    print(f"FATAL: Cannot find strategy data with total_trades. Top keys: {sorted(data.keys())}", file=sys.stderr)
    sys.exit(1)

# Debug: print available keys
print(f"  Strategy keys: {sorted(strat.keys()) if isinstance(strat, dict) else 'not dict'}")

def _number(val):
    """'17.85%' → 17.85, '17.85' → 17.85, 17.85 → 17.85"""
    if isinstance(val, str):
        val = val.replace("%", "").strip()
    try:
        return float(val)
    except (ValueError, TypeError):
        return val

def _ratio_to_pct(val):
    """0.447 → 44.7, -0.1612 → -16.12"""
    v = _number(val)
    return round(v * 100, 2) if isinstance(v, (int, float)) and abs(v) <= 1 else v

# ── P1: Field resolution with real Freqtrade JSON keys ───────
trades = strat.get("total_trades", "?")
metric_sources = {"trades": "total_trades"}

profit_val = "?"
if "profit_total_pct" in strat:
    profit_val = _number(strat["profit_total_pct"])
    metric_sources["profit_total_pct"] = "profit_total_pct"
elif "profit_total" in strat:
    profit_val = _ratio_to_pct(strat["profit_total"])
    metric_sources["profit_total_pct"] = "profit_total (ratio→pct)"

profit_total = strat.get("profit_total", "?")

winrate_val = "?"
if "winrate" in strat:
    winrate_val = _ratio_to_pct(strat["winrate"])
    metric_sources["winrate"] = "winrate (ratio→pct)"

max_dd_val = "?"
if "max_drawdown_pct" in strat:
    max_dd_val = _number(strat["max_drawdown_pct"])
    metric_sources["max_drawdown_pct"] = "max_drawdown_pct"
elif "max_drawdown_account" in strat:
    max_dd_val = _ratio_to_pct(strat["max_drawdown_account"])
    metric_sources["max_drawdown_pct"] = "max_drawdown_account (ratio→pct)"
elif "max_drawdown" in strat:
    max_dd_val = _ratio_to_pct(strat["max_drawdown"])
    metric_sources["max_drawdown_pct"] = "max_drawdown (ratio→pct)"

pf = strat.get("profit_factor", "?")

# P3: Baseline integrity — must have real values
has_missing = any(v == "?" or v is None for v in [trades, profit_val, winrate_val, max_dd_val])
baseline_integrity = "CONFIRMED" if not has_missing else "FAIL:missing_metrics"

# P4: Pair universe
pairs_requested = ["BTC/USDT"]
actual_pairs = []

# 1) Try trades inside strategy
trades_data = strat.get("trades")
if not isinstance(trades_data, list) or not trades_data:
    trades_data = data.get("trades")
if isinstance(trades_data, list) and trades_data:
    actual_pairs = sorted({t.get("pair") for t in trades_data if isinstance(t, dict) and t.get("pair")})

# 2) Try pairlist in strategy
if not actual_pairs:
    pl = strat.get("pairlist")
    if isinstance(pl, list):
        actual_pairs = sorted(set(pl))

# 3) Try top-level pairs
if not actual_pairs:
    p2 = data.get("pairs")
    if isinstance(p2, list):
        actual_pairs = sorted(set(p2))

if not actual_pairs:
    pairs_tested = []
    pair_universe_integrity = "FAIL:no_actual_pairs_evidence"
else:
    pairs_tested = actual_pairs
    pair_universe_integrity = "PASS" if pairs_requested == actual_pairs else "FAIL"

print(f"  trades={trades} profit_val={profit_val} winrate_val={winrate_val} maxDD_val={max_dd_val} pf={pf}")
print(f"  metric_sources: {metric_sources}")

summary = {
    "variant": variant,
    "run_id": run_id,
    "run_started_at_ns": run_started_ns,
    "source_result_path": str(actual_json_path.resolve()),
    "source_result_sha256": hashlib.sha256(actual_json_path.read_bytes()).hexdigest()[:16],
    "source_result_type": source_type,
    "total_trades": trades,
    "profit_total_pct": profit_val,
    "profit_total": profit_total,
    "winrate": winrate_val,
    "max_drawdown_pct": max_dd_val,
    "profit_factor": pf,
    "metric_sources": metric_sources,
    "pairs_requested": pairs_requested,
    "pairs_tested": pairs_tested,
    "policy_sha256": policy_sha,
    "config_sha256": config_sha,
    "cache_mode": "none",
    "isolated_user_data_dir": str(isolated_dir.resolve()),
    "elapsed_s": elapsed,
    "baseline_integrity": baseline_integrity,
    "pair_universe_integrity": pair_universe_integrity,
}
summary_path.write_text(json.dumps(summary, indent=2))
print(f"  elapsed={elapsed:.0f}s  summary={summary_path}")

# ── Lookahead (optional) ────────────────────────────────────────
if os.environ.get("RUN_LOOKAHEAD", "") == "1":
    print(f"  Lookahead for {variant}...", flush=True)
    la_log = results_dir / f"{output_base}_lookahead.log"
    la_result = subprocess.run([
        "freqtrade", "lookahead-analysis",
        "--config", str(config_abs),
        "--strategy", "AISupervisedStrategy",
        "--strategy-path", "freqtrade_data/strategies",
        "--datadir", str(Path("freqtrade_data/data/okx").resolve()),
        "--timerange", timerange,
        "--pairs", "BTC/USDT",
    ], capture_output=True, text=True, timeout=900, env=env)
    la_log.write_text(la_result.stdout + "\n" + la_result.stderr)

    # P0: fail-fast on any lookahead error
    if la_result.returncode != 0:
        print(f"FATAL: Lookahead failed rc={la_result.returncode}", file=sys.stderr)
        sys.exit(la_result.returncode)
    la_text = la_result.stdout
    if "has_bias" in la_text:
        idx = la_text.index("has_bias")
        snippet = la_text[idx:idx+40]
        print(f"  Lookahead: {snippet}")
        if "Yes" in snippet:
            print(f"FATAL: Lookahead BIAS DETECTED", file=sys.stderr)
            sys.exit(1)
    elif "No data found" in la_text or "Terminating" in la_text:
        print(f"FATAL: Lookahead found no data", file=sys.stderr)
        sys.exit(1)
    else:
        print(f"FATAL: Lookahead could not parse result", file=sys.stderr)
        sys.exit(1)
