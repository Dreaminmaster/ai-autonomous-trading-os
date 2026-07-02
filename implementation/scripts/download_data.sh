#!/usr/bin/env bash
# ============================================================================
# download_data.sh — Download OKX historical OHLCV data via Freqtrade
# ============================================================================
# Downloads BTC/USDT and ETH/USDT 1h and 5m candles.
# Data stored in freqtrade_data/data/okx/
#
# Usage:
#   ./scripts/download_data.sh                     # default pairs + timeframes
#   ./scripts/download_data.sh --timerange 20250101-20250701  # custom range
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
USER_DATA="$PROJECT_DIR/freqtrade_data"
CONFIG="$USER_DATA/config.dryrun.json"

# Default time range: last 180 days
TIMERANGE="${TIMERANGE:-20241201-}"
PAIRS=("BTC/USDT" "ETH/USDT")
TIMEFRAMES=("1h" "5m")

echo "=== Downloading OKX Historical Data ==="
echo ""

# Check freqtrade is installed
if ! python -c "import freqtrade" 2>/dev/null; then
    echo "ERROR: Freqtrade not installed. Run ./setup_freqtrade.sh first."
    exit 1
fi

# Check config exists
if [ ! -f "$CONFIG" ]; then
    echo "ERROR: Config not found at $CONFIG. Run ./setup_freqtrade.sh first."
    exit 1
fi

for PAIR in "${PAIRS[@]}"; do
    for TF in "${TIMEFRAMES[@]}"; do
        echo "Downloading $PAIR @ $TF ..."
        freqtrade download-data \
            --config "$CONFIG" \
            --datadir "$USER_DATA/data/okx" \
            --exchange okx \
            --pairs "$PAIR" \
            --timeframes "$TF" \
            --timerange "$TIMERANGE" \
            --erase 2>&1 | tail -3
        echo "  ✓ $PAIR @ $TF downloaded"
        echo ""
    done
done

echo "=== Data download complete ==="
echo ""
echo "Data stored in: $USER_DATA/data/okx/"
ls -la "$USER_DATA/data/okx/" 2>/dev/null || echo "(directory will be populated after first download)"
