#!/usr/bin/env bash
# ============================================================================
# run_lookahead_analysis.sh — Run Freqtrade lookahead analysis
# ============================================================================
# Detects if strategy uses future data (lookahead bias).
# Critical for validating backtest integrity.
#
# Usage:
#   ./scripts/run_lookahead_analysis.sh
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FREQTRADE_DATA="$PROJECT_DIR/freqtrade_data"
CONFIG="$FREQTRADE_DATA/config.dryrun.json"
RESULTS_DIR="$FREQTRADE_DATA/backtest_results"
ANALYSIS_LOG="$RESULTS_DIR/lookahead_analysis.log"

STRATEGY="${STRATEGY:-AISupervisedStrategy}"
TIMERANGE="${TIMERANGE:-20241201-}"

mkdir -p "$RESULTS_DIR"

echo "=== Lookahead Analysis ==="
echo "Strategy: $STRATEGY"
echo "Log:      $ANALYSIS_LOG"
echo ""

freqtrade lookahead-analysis \
    --config "$CONFIG" \
    --strategy "$STRATEGY" \
    --strategy-path "$FREQTRADE_DATA/strategies" \
    --timerange "$TIMERANGE" \
    2>&1 | tee "$ANALYSIS_LOG"

echo ""
echo "Lookahead analysis complete. Log: $ANALYSIS_LOG"
