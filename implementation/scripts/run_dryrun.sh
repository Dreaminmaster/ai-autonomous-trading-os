#!/usr/bin/env bash
# ============================================================================
# run_dryrun.sh — Start Freqtrade dry-run with AISupervisedStrategy
# ============================================================================
# Starts Freqtrade in dry-run (paper trading) mode.
# Uses config.dryrun.json which has dry_run=true by default.
# Live trading is NEVER enabled by this script.
#
# Usage:
#   ./scripts/run_dryrun.sh
#
# The bot will:
#   - Fetch live market data from OKX public API
#   - Call the AI supervised strategy on each candle
#   - Simulate trades (no real orders)
#   - Log everything to freqtrade_data/logs/
#   - Serve Freqtrade dashboard on http://127.0.0.1:8080
#
# To stop: Ctrl+C
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FREQTRADE_DATA="$PROJECT_DIR/freqtrade_data"
CONFIG="$FREQTRADE_DATA/config.dryrun.json"
STRATEGY_PATH="$FREQTRADE_DATA/strategies"

STRATEGY="${STRATEGY:-AISupervisedStrategy}"

echo "=== Freqtrade Dry-Run (Paper Trading) ==="
echo "Mode:     DRY-RUN (no real orders)"
echo "Config:   $CONFIG"
echo "Strategy: $STRATEGY"
echo "Path:     $STRATEGY_PATH"
echo ""
echo "Freqtrade Dashboard: http://127.0.0.1:8080"
echo ""
echo "Press Ctrl+C to stop."
echo ""

# Verify dry_run is true
DRY_CHECK=$(python3 -c "
import json
with open('$CONFIG') as f:
    cfg = json.load(f)
if not cfg.get('dry_run', True):
    print('BLOCKED: live trading would be enabled — refusing to run')
    exit(1)
print('CONFIRMED: dry_run=true — safe to start')
" 2>&1)
echo "$DRY_CHECK"
echo ""

# Check strategy file
if [ ! -f "$STRATEGY_PATH/ai_supervised_strategy.py" ]; then
    echo "ERROR: Strategy file not found at $STRATEGY_PATH/ai_supervised_strategy.py"
    exit 1
fi

# Verify strategy can be discovered
echo "Verifying strategy discovery..."
freqtrade list-strategies --strategy-path "$STRATEGY_PATH" 2>&1 | grep -q "$STRATEGY" \
    && echo "  ✓ $STRATEGY found" \
    || echo "  ! $STRATEGY not found in list-strategies output"

# Start Freqtrade trade (dry-run)
freqtrade trade \
    --config "$CONFIG" \
    --strategy "$STRATEGY" \
    --strategy-path "$STRATEGY_PATH" \
    --dry-run
