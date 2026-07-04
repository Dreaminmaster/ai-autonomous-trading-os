#!/usr/bin/env python3
"""Strategy Fix Round 1 — uses canonical runner per variant + best2 lookahead."""
import copy, json, os, subprocess, sys
from pathlib import Path

IMPL_DIR = Path(__file__).resolve().parents[1]
os.chdir(IMPL_DIR)

VALIDATION_POLICY = "config/policy.validation.json"
TIMERANGE = os.environ.get("TIMERANGE", "20250101-20250701")
Timeout = 900  # 15 min per variant

VARIANTS = [
    ("round1_1_baseline_current", None),
    ("round1_2_trend_weight_025_only", {"experiment.strategy_weights.trend_following_v1": 0.25}),
    ("round1_3_trend_disabled_only", {"experiment.disabled_strategies": ["trend_following_v1"]}),
    ("round1_4_max_hold_6h_only", {"experiment.max_holding_minutes": 360}),
    ("round1_5_max_hold_4h_only", {"experiment.max_holding_minutes": 240}),
    ("round1_6_trend_025_hold_6h", {"experiment.strategy_weights.trend_following_v1": 0.25, "experiment.max_holding_minutes": 360}),
    ("round1_7_trend_disabled_hold_6h", {"experiment.disabled_strategies": ["trend_following_v1"], "experiment.max_holding_minutes": 360}),
    ("round1_8_trend_025_early_exit", {"experiment.strategy_weights.trend_following_v1": 0.25, "experiment.early_exit_loss_pct": -0.3, "experiment.early_exit_after_minutes": 120}),
    ("round1_9_trend_disabled_early_exit", {"experiment.disabled_strategies": ["trend_following_v1"], "experiment.early_exit_loss_pct": -0.3, "experiment.early_exit_after_minutes": 120}),
    ("round1_10_trend_025_no_sub", {
        "experiment.strategy_weights.trend_following_v1": 0.25,
        "experiment.no_substitution": True,
    }),
    ("round1_11_trend_disabled_no_sub", {
        "experiment.disabled_strategies": ["trend_following_v1"],
        "experiment.no_substitution": True,
    }),
]

def apply_overrides(base, overrides):
    p = copy.deepcopy(base)
    for k, v in (overrides or {}).items():
        parts = k.split(".")
        target = p
        for part in parts[:-1]:
            if part not in target:
                target[part] = {}
            target = target[part]
        target[parts[-1]] = v
    return p

results = []
base_policy = json.loads(open(VALIDATION_POLICY).read())

for name, overrides in VARIANTS:
    print(f"  [{name}] ...", flush=True)
    if overrides is None:
        policy = base_policy
    else:
        policy = apply_overrides(base_policy, overrides)

    # Write experiment policy
    policy_path = Path(f"freqtrade_data/backtest_results/exp_{name}_policy.json")
    policy_path.write_text(json.dumps(policy, indent=2))

    # Run canonical backtest
    try:
        result = subprocess.run([
            "python3", "scripts/run_canonical_backtest.py",
            name, name, str(policy_path.resolve())
        ], capture_output=True, text=True, timeout=Timeout)
        print(result.stdout[-200:] if result.stdout else "(no stdout)", flush=True)

        summary_path = Path(f"freqtrade_data/backtest_results/{name}_summary.json")
        if not summary_path.exists():
            print(f"    FAILED: no summary generated", file=sys.stderr)
            results.append({"name": name, "status": "FAILED(no summary)", "trades": "?", "profit": "?", "winrate": "?", "dd": "?", "pf": "?", "lookahead": "?"})
            continue

        s = json.loads(summary_path.read_text())
        # P3: wiring telemetry from log
        log_path = Path(f"freqtrade_data/backtest_results/{name}.log")
        telemetry = ""
        if log_path.exists():
            for line in log_path.read_text().split("\n"):
                if "ATOS_SIGNAL_DIAGNOSTICS" in line:
                    telemetry = line.strip()
                    break
            if "disabled_strategies" in telemetry or "strategy_weights" in telemetry:
                pass  # extract later

        results.append({
            "name": name, "status": "OK",
            "trades": s.get("total_trades", "?"),
            "profit": s.get("profit_total_pct", "?"),
            "winrate": s.get("winrate", "?"),
            "dd": s.get("max_drawdown_pct", "?"),
            "pf": s.get("profit_factor", "?"),
            "lookahead": "?",
            "summary": s,
        })
    except subprocess.TimeoutExpired:
        results.append({"name": name, "status": "TIMEOUT", "trades": "?", "profit": "?", "winrate": "?", "dd": "?", "pf": "?", "lookahead": "?"})
    except Exception as e:
        results.append({"name": name, "status": f"CRASH:{e}", "trades": "?", "profit": "?", "winrate": "?", "dd": "?", "pf": "?", "lookahead": "?"})

# ── Best 2 lookahead ─────────────────────────────────────────
ok_results = [r for r in results if r["status"] == "OK" and r["profit"] != "?"]
try:
    ok_results.sort(key=lambda r: float(str(r["profit"]).replace("%","").replace("?","-999")), reverse=True)
except: pass
best_two = ok_results[:2] if len(ok_results) >= 2 else ok_results

for b in best_two:
    name = b["name"]
    print(f"  Lookahead: {name} ...", flush=True)
    try:
        env = os.environ.copy()
        env["RUN_LOOKAHEAD"] = "1"
        policy_p = Path(f"freqtrade_data/backtest_results/exp_{name}_policy.json").resolve()
        env["ATOS_POLICY"] = str(policy_p)
        result = subprocess.run([
            "python3", "scripts/run_canonical_backtest.py",
            f"{name}_la", f"{name}_la", str(policy_p)
        ], capture_output=True, text=True, timeout=Timeout, env=env)
        la_log = Path(f"freqtrade_data/backtest_results/{name}_lookahead.log")
        b["lookahead"] = "PASS" if "has_bias" in result.stdout and "No" in result.stdout.split("has_bias")[-1][:5] else "FAIL"
    except Exception as e:
        b["lookahead"] = f"CRASH:{e}"

# ── Report ────────────────────────────────────────────────────
canonical_summary = Path("freqtrade_data/backtest_results/canonical_baseline_summary.json")
cb_data = {}
if canonical_summary.exists():
    cb_data = json.loads(canonical_summary.read_text())
baseline = results[0]
# P1: Real baseline integrity — compare 4 metrics
def _close(a, b, tol=1e-6):
    try: return abs(float(a)-float(b)) <= tol
    except: return str(a) == str(b)
integrity_keys = ["total_trades", "profit_total_pct", "winrate", "max_drawdown_pct", "profit_factor"]
integrity_checks = {}
for k in integrity_keys:
    cv = cb_data.get(k)
    bv = baseline.get("summary", {}).get(k) if "summary" in baseline else baseline.get(k.replace("total_trades","trades").replace("profit_total_pct","profit").replace("winrate","winrate").replace("max_drawdown_pct","dd"))
    # For baseline, check against canonical
    if isinstance(bv, dict): bv = bv.get(k)
    if bv is None:
        bv = baseline.get(k.replace("_pct","").replace("profit_total","profit"), "?")
    ok = _close(cv, bv) if cv != "?" and bv != "?" else False
    integrity_checks[k] = "PASS" if ok else "FAIL"
integrity = "PASS" if all(v == "PASS" for v in integrity_checks.values()) else "FAIL"
integrity_detail = ", ".join(f"{k}={v}" for k,v in integrity_checks.items())

with open("validation_reports/strategy_fix_round1.md", "w") as f:
    f.write("# Strategy Fix Round 1\n\n")
    f.write(f"**Timerange:** {TIMERANGE} | **Pair:** BTC/USDT 5m\n\n")
    f.write("## Canonical Baseline\n\n")
    f.write(f"- Canonical fresh: {cb_data.get('total_trades','?')} trades, {cb_data.get('profit_total_pct','?')}%, WR {cb_data.get('winrate','?')}, DD {cb_data.get('max_drawdown_pct','?')}\n")
    f.write(f"- Round1 baseline: {baseline.get('trades','?')} trades / {baseline.get('profit','?')}%\n")
    f.write(f"- Baseline integrity: {integrity} ({integrity_detail})\n\n")
    f.write("## Variant Matrix\n\n")
    f.write("| # | Variant | Status | Trades | Profit % | Winrate | Max DD | Profit Factor | Lookahead |\n")
    f.write("|---|---------|--------|--------|----------|---------|--------|---------------|-----------|\n")
    for i, r in enumerate(results):
        f.write(f"| {i+1} | {r['name']} | {r['status']} | {r.get('trades','?')} | {r.get('profit','?')} | {r.get('winrate','?')} | {r.get('dd','?')} | {r.get('pf','?')} | {r.get('lookahead','?')} |\n")
    f.write(f"\n## Best 2\n\n")
    for b in best_two:
        f.write(f"- **{b['name']}**: {b.get('trades','?')} trades, {b.get('profit','?')}%, WR {b.get('winrate','?')}, LA {b.get('lookahead','?')}\n")
    f.write("\n## Conclusion\n\n- Live trading: FORBIDDEN\n")

print(Path("validation_reports/strategy_fix_round1.md").read_text())
