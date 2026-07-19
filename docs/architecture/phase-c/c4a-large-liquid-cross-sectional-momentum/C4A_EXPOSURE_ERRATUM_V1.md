# C4A Exposure and Weekly-Reconciliation Erratum V1

## 1. Status and precedence

- Stage: `C4A`
- Required base SHA: `ec872bba9701f005f59d3238538918d93a5537da`
- Parent weekly clarification: `C4A_WEEKLY_BOUNDARY_CLARIFICATION_V1.md`
- Parent accounting clarification: `C4A_ACCOUNTING_AND_CONTRIBUTION_CLARIFICATION_V1.md`
- Erratum status: `DESIGN_ONLY`
- C4B: `CLOSED`
- Holdout: `HOLDOUT_CLOSED`
- Live: `FORBIDDEN`

This erratum is normative. It controls the invested-exposure definition at a close-time terminal liquidation and assigns any Sunday-close-to-Monday-open marking difference to the new economic week so weekly returns and PnL buckets reconcile exactly.

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

## 3. Weekly start reference and boundary-gap assignment

A crypto candle timestamp identifies its open. The Sunday `20:00 UTC` candle close and the following Monday `00:00 UTC` candle open represent the same weekly boundary, but the two reported prices are not assumed numerically identical.

To prevent an unreconciled marking residual, each full week uses a start-reference equity before the Monday open is applied:

- for the first full week of each independent window, `weekly_start_reference_equity = 1000 USDT`;
- for every later full week inside that window, `weekly_start_reference_equity` is the prior Sunday `20:00 UTC` post-close equity mark, before the new Monday open mark or transaction;
- carried-position PnL from the prior Sunday close to the Monday open belongs to the new week;
- the Monday rebalance fee belongs to the new week;
- price PnL from the Monday open through the ending Sunday close belongs to the same week;
- any terminal liquidation at the ending Sunday close and its fee belong to that week.

The controlling full-week equation is:

`weekly_net_return = ending_sunday_post_close_equity / weekly_start_reference_equity - 1`

This equation supersedes wording that used gross equity already marked at the Monday open as the weekly denominator.

For the S3 terminal stub:

- `terminal_stub_start_equity` is the post-close equity from Sunday `2024-09-29T20:00:00Z`;
- the Monday-open marking difference, forced-cash liquidation fee, and subsequent cash-only marks are included in `terminal_stub_net_pnl`;
- the stub remains excluded from the 39-value DSR arrays but is included in ordinary economic and reconciliation metrics.

Consequences:

- every marking difference, fee, and price change belongs to exactly one full-week or terminal-stub bucket;
- the sum of the 39 full-week PnL buckets plus the S3 terminal-stub PnL equals the sum of the three independent-window net PnL values within `1e-9 USDT`;
- no next-window open is read by S1 or S2;
- no C4B or holdout timestamp is used.

## 4. Evidence and tests

Every retained close-mark row must include both:

- `bar_exposed`, determined from post-open quantities;
- `post_close_quantity`, which is zero after a close-time terminal liquidation.

Every full-week evidence row must include:

- start-reference timestamp and equity;
- Monday execution timestamp;
- pre-trade open equity;
- boundary-gap PnL;
- rebalance fee;
- ending Sunday timestamp and post-close equity;
- terminal fee when applicable;
- full-week net PnL and net return.

Implementation tests must prove:

- an entry at a candle open makes that candle exposed;
- a risk-off liquidation at a candle open makes that candle unexposed;
- a position terminally liquidated at the candle close still makes that candle exposed;
- the final post-liquidation quantity is zero while the same row's `bar_exposed` may be true;
- S3's forced-cash terminal stub is unexposed;
- a nonzero Sunday-close-to-Monday-open price difference is assigned to the new week;
- Monday transaction cost is included in the new week's return;
- full-week and terminal-stub buckets reconcile to window PnL without a residual;
- production and independent reference exposure and weekly-reconciliation results match exactly.

## 5. Safety state

This erratum changes no signal, universe, policy, cost rate, gate threshold, research boundary, or execution authorization. It resolves only exposure and cost/PnL attribution before implementation or economic observation.

`C4A_DESIGN_ONLY` / `C4B_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
