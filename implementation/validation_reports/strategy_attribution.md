# Strategy Attribution

**Commit:** e9f1ee4 | **Trades:** 244 | **Timerange:** 2025-01-01 → 2025-07-01

## Entry Distribution

| Strategy ID | Trades | Winrate | Profit $ | Pct of Total |
|------------|--------|---------|----------|-------------|
| trend_following_v1 | 230 | 43.5% | -$189.53 | 94% |
| breakout_v1 | 10 | 50.0% | +$1.69 | 4% |
| mean_reversion_v1 | 4 | 100% | +$26.69 | 2% |

## Exit Distribution

| Exit Reason | Trades | Winrate | Profit $ |
|------------|--------|---------|----------|
| max_holding_time (20h) | 174 (71%) | 25.9% | -$524.74 |
| take_profit (2%) | 61 (25%) | 100% | +$403.25 |
| RSI overbought | 7 | 28.6% | -$6.73 |
| stop_loss | 1 | 0% | -$31.06 |

## Root Cause

Entry selection is fine (take-profit trades are 100% profitable).  
**Exit timing is the problem:** 71% of trades expire at max holding time and become losses.  
Take-profit (2%) hits only 25% of the time.

## Recommendations (future, NOT this round)

| Strategy | Recommendation |
|----------|---------------|
| trend_following_v1 | reduce_weight |
| mean_reversion_v1 | needs_more_data |
| breakout_v1 | keep |
| Max holding time (20h) | reduce |
