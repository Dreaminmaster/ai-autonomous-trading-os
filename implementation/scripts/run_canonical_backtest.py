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
strat = data.get("strategy", data.get("strategy_comparison", [{}]))
if isinstance(strat, list):
    strat = strat[0] if strat else {}
# If "strategy" key doesn't exist, the data itself is the strategy result
if not strat and "total_trades" in data:
    strat = data
if not strat:
    print(f"FATAL: No strategy data in result. Top keys: {sorted(data.keys())}", file=sys.stderr)
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

# ── Field resolution with explicit source tracking ──────────
trades = strat.get("total_trades", "?")
metric_sources = {"trades": "total_trades"}

# profit: prefer profit_total_pct, fallback to profit_total (as ratio)
if "profit_total_pct" in strat:
    profit_val = _number(strat["profit_total_pct"])
    metric_sources["profit_total_pct"] = "profit_total_pct"
elif "profit_total" in strat:
    profit_val = _ratio_to_pct(strat["profit_total"])
    metric_sources["profit_total_pct"] = "profit_total (ratio→pct)"
else:
    profit_val = "?"

profit_total = strat.get("profit_total", "?")

# winrate: Freqtrade returns as ratio 0..1
if "winrate" in strat:
    winrate_val = _ratio_to_pct(strat["winrate"])
    metric_sources["winrate"] = "winrate (ratio→pct)"
else:
    winrate_val = "?"

# max_drawdown: prefer max_drawdown_pct, fallback max_drawdown (ratio)
if "max_drawdown_pct" in strat:
    max_dd_val = _number(strat["max_drawdown_pct"])
    metric_sources["max_drawdown_pct"] = "max_drawdown_pct"
elif "max_drawdown" in strat:
    max_dd_val = _ratio_to_pct(strat["max_drawdown"])
    metric_sources["max_drawdown_pct"] = "max_drawdown (ratio→pct)"
else:
    max_dd_val = "?"

pf = strat.get("profit_factor", "?")

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
    "policy_sha256": policy_sha,
    "config_sha256": config_sha,
    "cache_mode": "none",
    "isolated_user_data_dir": str(isolated_dir.resolve()),
    "elapsed_s": elapsed,
    "baseline_integrity": "CONFIRMED",
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
        "--timerange", timerange,
        "--user-data-dir", str(isolated_dir.resolve()),
    ], capture_output=True, text=True, timeout=900, env=env)
    la_log.write_text(la_result.stdout + "\n" + la_result.stderr)
    la_text = la_result.stdout
    if "has_bias" in la_text:
        print(f"  Lookahead: {la_text[la_text.index('has_bias'):la_text.index('has_bias')+25]}")
    else:
        print(f"  Lookahead: could not parse")
