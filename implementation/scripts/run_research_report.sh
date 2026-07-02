#!/usr/bin/env bash
# ============================================================================
# run_research_report.sh — Generate a combined research report
# ============================================================================
# Aggregates backtest results, walk-forward, and Monte Carlo into one report.
# Outputs: research_report.json
#
# Usage:
#   ./scripts/run_research_report.sh
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$PROJECT_DIR/freqtrade_data/backtest_results"

mkdir -p "$RESULTS_DIR"

echo "=== Research Report ==="

cd "$PROJECT_DIR"

python3 << 'PYEOF'
import json
import os
from datetime import datetime
from pathlib import Path

results = {
    "generated_at": datetime.now().isoformat(),
    "commit": None,
    "pytest": {"passed": 0, "total": 0},
    "backtest": None,
    "walk_forward": None,
    "monte_carlo": None,
    "lookahead": None,
    "secret_scan": None,
}

# Try to get git hash
try:
    import subprocess
    commit = subprocess.check_output(
        ["git", "-C", "/root/ai-autonomous-trading-os", "rev-parse", "HEAD"], text=True
    ).strip()
    results["commit"] = commit
except Exception:
    pass

# Try to load backtest results
bt_file = Path("freqtrade_data/backtest_results/backtest_result.json")
if bt_file.exists():
    try:
        bt = json.loads(bt_file.read_text())
        strat = bt.get("strategy", bt.get("strategy_comparison", [{}])[0])
        results["backtest"] = {
            "pairs": strat.get("pairlist", []),
            "total_trades": strat.get("total_trades", 0),
            "winrate": strat.get("winrate", 0),
            "profit_total_pct": strat.get("profit_total_pct", strat.get("profit_total", 0)),
            "max_drawdown": strat.get("max_drawdown", strat.get("max_drawdown_account", 0)),
        }
    except Exception as e:
        results["backtest"] = {"error": str(e), "file": str(bt_file)}

# Try to load walk-forward report
wf_file = Path("freqtrade_data/backtest_results/walk_forward_report.json")
if wf_file.exists():
    try:
        wf = json.loads(wf_file.read_text())
        results["walk_forward"] = wf.get("walk_forward", {})
        results["monte_carlo"] = wf.get("monte_carlo", {})
    except Exception as e:
        results["walk_forward"] = {"error": str(e)}

# Try to load lookahead log
la_file = Path("freqtrade_data/backtest_results/lookahead_analysis.log")
if la_file.exists():
    try:
        results["lookahead"] = {"file": str(la_file), "size": la_file.stat().st_size}
    except Exception:
        pass

# Write combined report
report_path = Path("freqtrade_data/backtest_results/research_report.json")
report_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
print(f"Report written to: {report_path}")
print(json.dumps(results, indent=2, ensure_ascii=False))
PYEOF

echo ""
echo "Research report: freqtrade_data/backtest_results/research_report.json"
