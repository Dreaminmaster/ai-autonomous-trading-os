# C4A Exposure Erratum V1

## 1. Status and precedence

- Stage: `C4A`
- Required base SHA: `ec872bba9701f005f59d3238538918d93a5537da`
- Parent accounting clarification: `C4A_ACCOUNTING_AND_CONTRIBUTION_CLARIFICATION_V1.md`
- Erratum status: `DESIGN_ONLY`
- C4B: `CLOSED`
- Holdout: `HOLDOUT_CLOSED`
- Live: `FORBIDDEN`

This erratum is normative and controls the invested-exposure definition where the parent accounting clarification could be read ambiguously at a close-time terminal liquidation.

## 2. Frozen bar-held exposure definition

Exposure measures whether capital was exposed to an asset during the economic candle after all transactions at that candle's open.

For every economic four-hour candle:

`bar_exposed = total_asset_quantity_immediately_after_open_time_transactions > 0`

Rules:

- quantities are evaluated immediately after any scheduled entry, rebalance, or risk-off liquidation at the candle open;
- if no transaction occurs at the open, carried quantities determine the flag;
- a position held from the candle open through its close counts as exposed even when mandatory terminal liquidation occurs at that same close;
- therefore the final S1 or S2 candle counts as exposed when a position is held during that candle and liquidated at its close;
- the S3 candle beginning `2024-09-30T00:00:00Z` is unexposed because the boundary rule forces cash at its open;
- a close-time terminal liquidation changes the final post-liquidation equity and quantity state but does not retroactively change the bar-held exposure flag;
- the initial pre-window `1000 USDT` mark is not an economic candle and is excluded from the exposure denominator.

Window exposure is:

`sum(bar_exposed) / economic_four_hour_candle_count`

Aggregate exposure is the count-weighted fraction across all economic candles in S1, S2, and S3.

No notional threshold, rounding threshold, or tolerance may silently change a positive post-open quantity to unexposed.

## 3. Evidence and tests

Every retained close-mark row must include both:

- `bar_exposed`, determined from post-open quantities;
- `post_close_quantity`, which is zero after a close-time terminal liquidation.

Implementation tests must prove:

- an entry at a candle open makes that candle exposed;
- a risk-off liquidation at a candle open makes that candle unexposed;
- a position terminally liquidated at the candle close still makes that candle exposed;
- the final post-liquidation quantity is zero while the same row's `bar_exposed` may be true;
- S3's forced-cash terminal stub is unexposed;
- production and independent reference exposure counts match exactly.

## 4. Safety state

This erratum changes no signal, universe, cost, return, DSR, gate threshold, data boundary, or execution authorization.

`C4A_DESIGN_ONLY` / `C4B_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
