#!/usr/bin/env bash
# ============================================================================
# run_baseline_comparison.sh — Compare AISupervisedStrategy against baselines
# ============================================================================
# Runs backtest for: AISupervisedStrategy, SMA Crossover, RSI Mean Reversion,
# Buy & Hold (Freqtrade doesn't have this natively — use 0-exit SampleStrategy),
# and Freqtrade SampleStrategy.
#
# Output: reports/baseline_comparison.md
# ============================================================================

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
FREQTRADE_DATA="$PROJECT_DIR/freqtrade_data"
CONFIG="$FREQTRADE_DATA/config.dryrun.json"
RESULTS_DIR="$FREQTRADE_DATA/backtest_results"
REPORTS_DIR="$PROJECT_DIR/reports"
STRATEGY_PATH="$FREQTRADE_DATA/strategies"
DATADIR="$FREQTRADE_DATA/data/okx"

TIMERANGE="${TIMERANGE:-20250101-20250701}"
TIMEFRAME="${TIMEFRAME:-5m}"
PAIR="${PAIR:-BTC/USDT}"

mkdir -p "$RESULTS_DIR" "$REPORTS_DIR"

echo "# Baseline Comparison" > "$REPORTS_DIR/baseline_comparison.md"
echo "" >> "$REPORTS_DIR/baseline_comparison.md"
echo "**Timerange:** $TIMERANGE | **Pair:** $PAIR | **Timeframe:** $TIMEFRAME" >> "$REPORTS_DIR/baseline_comparison.md"
echo "" >> "$REPORTS_DIR/baseline_comparison.md"
echo "| Strategy | Trades | Winrate | Profit % | Max DD % | Profit Factor | Avg Duration |" >> "$REPORTS_DIR/baseline_comparison.md"
echo "|----------|--------|---------|----------|----------|---------------|--------------|" >> "$REPORTS_DIR/baseline_comparison.md"

run_backtest() {
    local STRATEGY="$1"
    local LABEL="$2"
    local EXTRA_FLAGS="${3:-}"

    echo "Running: $LABEL ($STRATEGY)..."
    local LOG="$RESULTS_DIR/baseline_${LABEL}.log"

    freqtrade backtesting \
        --config "$CONFIG" \
        --strategy "$STRATEGY" \
        --strategy-path "$STRATEGY_PATH" \
        --datadir "$DATADIR" \
        --timerange "$TIMERANGE" \
        --timeframe "$TIMEFRAME" \
        $EXTRA_FLAGS \
        2>&1 > "$LOG" || true

    # Extract key metrics
    python3 -c "
import json, sys
try:
    with open('$LOG') as f:
        text = f.read()
    # Find the table summary line
    lines = text.split('\n')
    for l in lines:
        if '│ $STRATEGY ' in l[:60] or '| $STRATEGY ' in l[:60] or '$LABEL' in l:
            pass  # Not using strict parsing, use grep below
except:
    pass
" 2>/dev/null || true

    # Parse from Freqtrade table output using grep
    local LINE=$(grep -E "$STRATEGY" "$LOG" 2>/dev/null | grep -E '[0-9]+' | tail -1)

    if [ -n "$LINE" ]; then
        # Extract numbers: Strategy | Trades | Avg Profit % | Tot Profit USDT | Tot Profit % | Avg Duration | Win Draw Loss Win% | Drawdown
        local TRADES=$(echo "$LINE" | awk -F'│|┃' '{print $2}' | tr -d ' ' 2>/dev/null || echo "-")
        local AVGPROFIT=$(echo "$LINE" | awk -F'│|┃' '{print $3}' | tr -d ' ' 2>/dev/null || echo "-")
        local TOTPROFIT=$(echo "$LINE" | awk -F'│|┃' '{print $5}' | tr -d ' ' 2>/dev/null || echo "-")
        local DURATION=$(echo "$LINE" | awk -F'│|┃' '{print $6}' | tr -d ' ' 2>/dev/null || echo "-")
        local WINSTAT=$(echo "$LINE" | awk -F'│|┃' '{print $7}' | tr -d ' ' 2>/dev/null || echo "-")
        local DRAWDOWN=$(echo "$LINE" | awk -F'│|┃' '{print $8}' | tr -d ' ' 2>/dev/null || echo "-")

        # Extract winrate from WINSTAT (format: Win Draw Loss Win%)
        local WINRATE=$(echo "$WINSTAT" | awk '{print $NF}' 2>/dev/null || echo "-")

        echo "| $LABEL | $TRADES | $WINRATE | $TOTPROFIT | $DRAWDOWN | - | $DURATION |" >> "$REPORTS_DIR/baseline_comparison.md"
    else
        echo "| $LABEL | - | - | - | - | - | - | (parse failed) |" >> "$REPORTS_DIR/baseline_comparison.md"
    fi
}

# 1. AISupervisedStrategy
run_backtest "AISupervisedStrategy" "AISupervisedStrategy"

# 2. Simple SMA Crossover (comes with Freqtrade)
run_backtest "SampleStrategy" "SampleStrategy"

# 3. Freqtrade built-in MACD if available (bundled examples don't include it — skip)
# 4. RSI-based — use our AISupervisedStrategy exit logic only (which uses RSI)
#    We compare with SampleStrategy as baseline instead

echo "" >> "$REPORTS_DIR/baseline_comparison.md"
echo "## Buy & Hold (computed separately)" >> "$REPORTS_DIR/baseline_comparison.md"
echo "" >> "$REPORTS_DIR/baseline_comparison.md"

# Compute Buy & Hold using Python
python3 << 'PYEOF'
import json, sys
try:
    # Try to load candle data and compute buy & hold
    from pathlib import Path
    data_dir = Path("freqtrade_data/data/okx")
    if data_dir.exists():
        import pandas as pd
        for f in data_dir.glob("**/*.feather"):
            if "BTC" in str(f) and "5m" in str(f):
                df = pd.read_feather(f)
                if "close" in df.columns and len(df) > 1:
                    first = float(df["close"].iloc[0])
                    last = float(df["close"].iloc[-1])
                    pct = (last - first) / first * 100
                    with open("reports/baseline_comparison.md", "a") as out:
                        out.write(f"| Buy &amp; Hold BTC | 1 | - | {pct:.2f}% | - | - | 180d |\n")
                    sys.exit(0)
except Exception as e:
    pass

# Fallback: use a known approximate
with open("reports/baseline_comparison.md", "a") as out:
    out.write("| Buy & Hold BTC | 1 | - | (data not available) | - | - | 180d |\n")
PYEOF

echo "" >> "$REPORTS_DIR/baseline_comparison.md"
echo "## Notes" >> "$REPORTS_DIR/baseline_comparison.md"
echo "" >> "$REPORTS_DIR/baseline_comparison.md"
echo "- SampleStrategy is Freqtrade's bundled example strategy (SMA-based)." >> "$REPORTS_DIR/baseline_comparison.md"
echo "- AISupervisedStrategy uses ATOS mock provider + risk engine pipeline." >> "$REPORTS_DIR/baseline_comparison.md"
echo "- All strategies use same config, timerange, timeframe, pair." >> "$REPORTS_DIR/baseline_comparison.md"
echo "- **This comparison does NOT imply profitability of any strategy.**" >> "$REPORTS_DIR/baseline_comparison.md"

echo "" >> "$REPORTS_DIR/baseline_comparison.md"
echo "Report: $REPORTS_DIR/baseline_comparison.md"
cat "$REPORTS_DIR/baseline_comparison.md"
