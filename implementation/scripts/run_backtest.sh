#!/usr/bin/env bash
# ============================================================================
# run_backtest.sh — Run Freqtrade backtest with AISupervisedStrategy
# ============================================================================
# Backtests the AI Supervised Strategy on downloaded historical data.
# Produces results in freqtrade_data/backtest_results/
#
# Usage:
#   ./scripts/run_backtest.sh                                           # default
#   ./scripts/run_backtest.sh --timerange 20250101-20250601             # custom range
#   STRATEGY=SampleStrategy ./scripts/run_backtest.sh                   # other strategy
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FREQTRADE_DATA="$PROJECT_DIR/freqtrade_data"
CONFIG="$FREQTRADE_DATA/config.dryrun.json"
RESULTS_DIR="$FREQTRADE_DATA/backtest_results"
STRATEGY_PATH="$FREQTRADE_DATA/strategies"

STRATEGY="${STRATEGY:-AISupervisedStrategy}"
TIMERANGE="${TIMERANGE:-20241201-}"
TIMEFRAMES="${TIMEFRAMES:-5m}"

echo "=== Freqtrade Backtest ==="
echo "Strategy:  $STRATEGY"
echo "Path:      $STRATEGY_PATH"
echo "Timerange: $TIMERANGE"
echo "Timeframe: $TIMEFRAMES"
echo ""

# Check strategy file exists
if [ ! -f "$STRATEGY_PATH/ai_supervised_strategy.py" ]; then
    echo "WARNING: Strategy file not found at $STRATEGY_PATH/ai_supervised_strategy.py"
    echo "  Falling back to Freqtrade SampleStrategy."
    STRATEGY="SampleStrategy"
    STRATEGY_PATH=""
fi

mkdir -p "$RESULTS_DIR"

# Build command
CMD="freqtrade backtesting"
CMD="$CMD --config '$CONFIG'"
CMD="$CMD --datadir '$FREQTRADE_DATA/data/okx'"
CMD="$CMD --strategy '$STRATEGY'"
[ -n "$STRATEGY_PATH" ] && CMD="$CMD --strategy-path '$STRATEGY_PATH'"
CMD="$CMD --timerange '$TIMERANGE'"
CMD="$CMD --timeframe '$TIMEFRAMES'"
CMD="$CMD --export trades"
CMD="$CMD --export-filename '$RESULTS_DIR/backtest_result.json'"

echo "Running: $CMD"
echo ""
eval "$CMD" 2>&1 | tail -30

echo ""
echo "Backtest complete. Results in: $RESULTS_DIR/"

# If JSON results exist, print summary
if [ -f "$RESULTS_DIR/backtest_result.json" ]; then
    echo ""
    echo "=== Summary ==="
    python3 -c "
import json
with open('$RESULTS_DIR/backtest_result.json') as f:
    data = json.load(f)
strat = data.get('strategy', data.get('strategy_comparison', [{}])[0])
print(f\"  Pairs: {strat.get('pairlist', [])}\")
print(f\"  Total trades: {strat.get('total_trades', 'N/A')}\")
print(f\"  Win rate: {strat.get('winrate', 'N/A')}\")
print(f\"  Profit total: {strat.get('profit_total_pct', strat.get('profit_total', 'N/A'))}\")
print(f\"  Max drawdown: {strat.get('max_drawdown', strat.get('max_drawdown_account', 'N/A'))}\")
    " 2>/dev/null || echo "  (summary parse skipped — see JSON file directly)"
fi
