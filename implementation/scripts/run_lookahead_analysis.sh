#!/usr/bin/env bash
# ============================================================================
# run_lookahead_analysis.sh — Run Freqtrade lookahead bias detection
# ============================================================================
# Uses the SAME config/strategy/timerange as the backtest.
# Validates that the strategy does NOT use future data.
#
# Usage:
#   ./scripts/run_lookahead_analysis.sh
#   TIMERANGE=20250101-20250701 ./scripts/run_lookahead_analysis.sh
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FREQTRADE_DATA="$PROJECT_DIR/freqtrade_data"
CONFIG="$FREQTRADE_DATA/config.dryrun.json"
RESULTS_DIR="$FREQTRADE_DATA/backtest_results"
STRATEGY_PATH="$FREQTRADE_DATA/strategies"
DATADIR="$FREQTRADE_DATA/data/okx"

STRATEGY="${STRATEGY:-AISupervisedStrategy}"
TIMERANGE="${TIMERANGE:-20250101-20250701}"
TIMEFRAME="${TIMEFRAME:-5m}"
PAIR="${PAIR:-BTC/USDT}"
MIN_TRADES="${MIN_TRADES:-20}"
TARGETED_TRADES="${TARGETED_TRADES:-100}"
ATOS_POLICY="${ATOS_POLICY:-$PROJECT_DIR/config/policy.validation.json}"

export ATOS_POLICY
export MIN_TRADES
export TARGETED_TRADES

mkdir -p "$RESULTS_DIR"
ANALYSIS_LOG="$RESULTS_DIR/lookahead_analysis.log"

echo "=== Lookahead Bias Analysis ==="
echo "Strategy:   $STRATEGY"
echo "Pair:       $PAIR"
echo "Timeframe:  $TIMEFRAME"
echo "Timerange:  $TIMERANGE"
echo "Config:     $CONFIG"
echo "Datadir:    $DATADIR"
echo "ATOS_POLICY: $ATOS_POLICY"
echo "Min trades: $MIN_TRADES"
echo "Log:        $ANALYSIS_LOG"
echo ""

# Show CLI help first
freqtrade lookahead-analysis --help 2>&1 | head -20 | tee -a "$ANALYSIS_LOG"

echo ""
echo "=== Running lookahead-analysis ==="

START_TS=$(date +%s)

freqtrade lookahead-analysis \
    --config "$CONFIG" \
    --strategy "$STRATEGY" \
    --strategy-path "$STRATEGY_PATH" \
    --datadir "$DATADIR" \
    --timerange "$TIMERANGE" \
    --timeframe "$TIMEFRAME" \
    2>&1 | tee "$ANALYSIS_LOG"

EXIT_CODE=${PIPESTATUS[0]}
DURATION=$(( $(date +%s) - START_TS ))

echo ""
echo "=== Lookahead Diagnostics ==="
echo "LOOKAHEAD_DIAGNOSTICS:"
echo "  strategy=$STRATEGY"
echo "  pair=$PAIR"
echo "  timeframe=$TIMEFRAME"
echo "  timerange=$TIMERANGE"
echo "  config=$CONFIG"
echo "  datadir=$DATADIR"
echo "  ATOS_POLICY=$ATOS_POLICY"
echo "  exit_code=$EXIT_CODE"
echo "  duration_seconds=$DURATION"
echo "  minimum_trade_amount=$MIN_TRADES"
echo "  targeted_trade_amount=$TARGETED_TRADES"

# Parse result
if grep -q "too few trades" "$ANALYSIS_LOG" 2>/dev/null; then
    echo "  result=TOO_FEW_TRADES"
elif grep -q "has_bias.*True" "$ANALYSIS_LOG" 2>/dev/null; then
    echo "  result=BIAS_DETECTED"
elif grep -q "has_bias.*False" "$ANALYSIS_LOG" 2>/dev/null; then
    echo "  result=PASS"
elif [ "$EXIT_CODE" -eq 0 ]; then
    echo "  result=PASS"
else
    echo "  result=FAIL"
fi

echo ""
echo "Lookahead analysis complete. Log: $ANALYSIS_LOG"
