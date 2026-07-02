#!/usr/bin/env bash
# ============================================================================
# run_walk_forward.sh — Run walk-forward validation using ATOS evaluator
# ============================================================================
# Runs multiple backtest windows and produces out-of-sample validation.
# Outputs: walk_forward_report.json
#
# Usage:
#   ./scripts/run_walk_forward.sh
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RESULTS_DIR="$PROJECT_DIR/freqtrade_data/backtest_results"
mkdir -p "$PROJECT_DIR/freqtrade_data/backtest_results"

echo "=== Walk-Forward Validation ==="
echo ""

cd "$PROJECT_DIR"

python3 << 'PYEOF'
import json
from pathlib import Path
from atos.evaluator import Evaluator

# Dummy PnL series — in production, these come from backtest results
pnl_series = [
    0.15, -0.05, 0.22, -0.08, 0.31, 0.12, -0.15, 0.18, -0.04, 0.27,
    -0.09, 0.14, 0.33, -0.12, 0.19, -0.06, 0.25, 0.11, -0.18, 0.29,
    0.08, -0.22, 0.17, 0.35, -0.07, 0.13, -0.11, 0.20, 0.28, -0.14,
]

evaluator = Evaluator()

# Walk-forward analysis
wf = evaluator.walk_forward(pnl_series, train=10, test=5)

# Monte Carlo
mc = evaluator.monte_carlo(pnl_series, simulations=500)

# Overall metrics
overall = evaluator.summarize(pnl_series)

report = {
    "source": "atos_evaluator",
    "overall": overall.to_dict(),
    "walk_forward": wf.to_dict(),
    "monte_carlo": mc.to_dict(),
    "note": "Real walk-forward requires backtest results from multiple windows. This is a structural skeleton.",
}

output_path = Path("freqtrade_data/backtest_results/walk_forward_report.json")
output_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))

print(json.dumps(report, indent=2, ensure_ascii=False))
print(f"\nReport written to: {output_path}")
PYEOF

echo ""
echo "Walk-forward report: freqtrade_data/backtest_results/walk_forward_report.json"
