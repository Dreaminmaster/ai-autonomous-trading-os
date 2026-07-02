#!/usr/bin/env bash
# ============================================================================
# run_dryrun.sh — Start Freqtrade dry-run with AI Supervised Strategy
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
#   - Serve dashboard on http://127.0.0.1:8080
#
# To stop: Ctrl+C
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
USER_DATA="$PROJECT_DIR/freqtrade_data"
CONFIG="$USER_DATA/config.dryrun.json"

STRATEGY="${STRATEGY:-ai_supervised_strategy}"

echo "=== Freqtrade Dry-Run (Paper Trading) ==="
echo "Mode:    DRY-RUN (no real orders)"
echo "Config:  $CONFIG"
echo "Strategy: $STRATEGY"
echo ""
echo "Dashboard: http://127.0.0.1:8080"
echo "API:       http://127.0.0.1:8080/api/v1/"
echo ""
echo "Press Ctrl+C to stop."
echo ""

# Verify dry_run is true
DRY_CHECK=$(python -c "
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
STRATEGY_FILE="$USER_DATA/strategies/${STRATEGY}.py"
if [ ! -f "$STRATEGY_FILE" ]; then
    echo "WARNING: AI strategy file not found at $STRATEGY_FILE"
    echo "  Using Freqtrade SampleStrategy instead for smoke test."
    STRATEGY="SampleStrategy"
fi

# Start Freqtrade trade (dry-run)
freqtrade trade \
    --config "$CONFIG" \
    --strategy "$STRATEGY" \
    --dry-run
