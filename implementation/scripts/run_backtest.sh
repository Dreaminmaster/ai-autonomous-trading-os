#!/usr/bin/env bash
# ============================================================================
# run_backtest.sh — Run Freqtrade backtest with AI Supervised Strategy
# ============================================================================
# Backtests the ai_supervised_strategy on downloaded historical data.
# Produces results in freqtrade_data/backtest_results/
#
# Usage:
#   ./scripts/run_backtest.sh                                           # default
#   ./scripts/run_backtest.sh --timerange 20250101-20250601             # custom range
#   ./scripts/run_backtest.sh --strategy SampleStrategy                 # other strategy
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
USER_DATA="$PROJECT_DIR/freqtrade_data"
CONFIG="$USER_DATA/config.dryrun.json"
RESULTS_DIR="$USER_DATA/backtest_results"

STRATEGY="${STRATEGY:-ai_supervised_strategy}"
TIMERANGE="${TIMERANGE:-20241201-}"
TIMEFRAMES="${TIMEFRAMES:-5m}"

echo "=== Freqtrade Backtest ==="
echo "Strategy:  $STRATEGY"
echo "Timerange: $TIMERANGE"
echo "Timeframe: $TIMEFRAMES"
echo ""

# Check strategy file exists
STRATEGY_FILE="$USER_DATA/strategies/${STRATEGY}.py"
if [ ! -f "$STRATEGY_FILE" ]; then
    echo "WARNING: Strategy file not found at $STRATEGY_FILE"
    echo "  The AI supervised strategy will be used once created."
    echo "  For now, running backtest on Freqtrade's SampleStrategy as a smoke test."
    STRATEGY="SampleStrategy"
fi

mkdir -p "$RESULTS_DIR"

echo "Running backtest..."
freqtrade backtesting \
    --config "$CONFIG" \
    --datadir "$USER_DATA/data/okx" \
    --strategy "$STRATEGY" \
    --timerange "$TIMERANGE" \
    --timeframe "$TIMEFRAMES" \
    --export trades \
    --export-filename "$RESULTS_DIR/backtest_result.json" \
    2>&1 | tail -30

echo ""
echo "Backtest complete. Results in: $RESULTS_DIR/"

# If JSON results exist, print summary
if [ -f "$RESULTS_DIR/backtest_result.json" ]; then
    echo ""
    echo "=== Summary ==="
    python -c "
import json
with open('$RESULTS_DIR/backtest_result.json') as f:
    data = json.load(f)
strategy = data.get('strategy', data.get('strategy_comparison', [{}])[0])
print(f\"  Pairs: {strategy.get('pairlist', [])}\")
print(f\"  Total trades: {strategy.get('total_trades', 'N/A')}\")
print(f\"  Win rate: {strategy.get('winrate', 'N/A')}\")
print(f\"  Profit total: {strategy.get('profit_total_pct', strategy.get('profit_total', 'N/A'))}\")
print(f\"  Max drawdown: {strategy.get('max_drawdown', strategy.get('max_drawdown_account', 'N/A'))}\")
    " 2>/dev/null || echo "  (summary parse skipped — see JSON file directly)"
fi
