# C4A Accounting and Contribution Clarification V1

## 1. Status and precedence

- Stage: `C4A`
- Parent contract: `C4A_LARGE_LIQUID_CROSS_SECTIONAL_MOMENTUM_CONTRACT_V1.md`
- Universe and multiple-testing addendum: `C4A_UNIVERSE_AND_MULTIPLE_TESTING_ADDENDUM_V1.md`
- Weekly boundary clarification: `C4A_WEEKLY_BOUNDARY_CLARIFICATION_V1.md`
- DSR and universe-scope clarification: `C4A_DSR_AND_UNIVERSE_SCOPE_CLARIFICATION_V1.md`
- Required base SHA: `72f35dd715874dc2e7c355511675dec29642b430`
- Clarification status: `DESIGN_ONLY`
- C4B: `CLOSED`
- Holdout: `HOLDOUT_CLOSED`
- Live: `FORBIDDEN`

This clarification is normative. It freezes lot counting, equity marks, return streams, turnover, exposure, drawdown, and additive PnL-contribution semantics used by C4A gates and ranking.

## 2. Economic equity timeline

Every policy/window/cost cell begins immediately before its first scheduled window-open rebalance with:

- cash: `1000 USDT`;
- all asset quantities: zero;
- initial equity mark: `1000 USDT`.

For every four-hour candle inside the independent window:

1. At the candle open, mark any quantity carried from the previous candle close to the current open.
2. If this is a scheduled rebalance open, solve and apply the frozen post-cost target transaction.
3. Hold the resulting quantities through the candle.
4. Mark equity at the candle close.

No intermediate intrabar mark is used for Sharpe or drawdown. Rebalance-open ledger values are retained separately for accounting evidence.

For the final economic candle:

- mark carried positions to its close;
- execute mandatory terminal liquidation at that same close unless the portfolio is already cash;
- deduct liquidation fees;
- record the post-liquidation close as the final equity mark.

The close-equity sequence must include exactly one mark for every economic four-hour candle plus the initial `1000 USDT` mark.

## 3. Four-hour return stream

For a window with close-equity marks `E_0 = 1000, E_1, ..., E_n`:

`r_t = E_t / E_(t-1) - 1`, for `t = 1..n`.

Rules:

- the first return includes the first scheduled rebalance fee and the first candle's open-to-close movement;
- a scheduled rebalance inside the window is reflected in the single return ending at that candle close;
- the final return includes terminal liquidation fees when liquidation occurs at the final close;
- no return is formed between independent windows;
- aggregate four-hour Sharpe concatenates the three within-window arrays in S1, S2, S3 order.

Every return must be finite. A non-positive prior equity or non-finite ratio is `EVIDENCE_FAILURE`.

## 4. Drawdown

Window drawdown is calculated from the initial equity mark and every post-cost close-equity mark:

- running peak starts at `1000`;
- drawdown at a mark is `equity / running_peak - 1`;
- maximum drawdown is the absolute magnitude of the most negative drawdown;
- the final post-liquidation close mark is included.

No intrabar high/low drawdown and no cross-window drawdown are used.

## 5. Invested exposure

At each economic four-hour close after all open-time transactions:

`invested = total_asset_market_value > 0`

Window exposure is invested close marks divided by the exact economic close-mark count. Aggregate exposure is the count-weighted fraction across S1, S2, and S3.

Rules:

- the initial pre-trade `1000` mark is excluded from the exposure denominator;
- a close after an open-time liquidation is cash and counts as uninvested;
- the S3 terminal stub close marks count in ordinary exposure metrics;
- no quantity or value tolerance may silently convert a positive position to zero; the accounting engine must produce exact zero targets when liquidated.

## 6. Scheduled decisions and active rebalances

Each of the forty audit-calendar decisions produces one retained target record.

Definitions:

- `scheduled_decision_count`: every scheduled decision, including cash targets and unchanged targets;
- `scheduled_active_rebalance_count`: a decision whose final frozen target contains at least one asset with positive target weight;
- `traded_rebalance_count`: a decision where the sum of absolute asset trade notionals is strictly positive;
- `risk_off_liquidation_count`: a scheduled decision with a cash target that trades positive notional to liquidate an existing position.

The activity eligibility gates use `scheduled_active_rebalance_count` exactly as stated in the weekly-boundary clarification.

## 7. Closed asset lots

An asset lot is one contiguous holding spell for one pair inside one independent window.

A lot:

- opens when that asset's quantity changes from exactly zero to strictly positive;
- remains the same lot across scheduled rebalances while its post-trade quantity remains strictly positive;
- is not closed by a partial reduction or increased by a partial purchase;
- closes when its quantity changes from strictly positive to exactly zero at a scheduled rebalance or mandatory terminal liquidation;
- cannot cross an independent window boundary.

`closed_asset_lot_count` is the number of such completed spells across all assets and all three independent windows at expected cost.

Every closed-lot ledger must retain:

- pair;
- window;
- opening timestamp and quantity;
- every intervening quantity adjustment;
- closing timestamp and quantity;
- gross price PnL;
- allocated transaction fees;
- net PnL.

All lots are forcibly closed by the final window liquidation, so open-lot count must be zero after each cell.

## 8. Turnover

At each transaction event `j`:

`normalized_traded_notional_j = sum_i(abs(delta_value_i_j)) / E_before_j`

where `E_before_j` is finite, strictly positive gross equity immediately before transaction fees at that event.

Aggregate normalized traded notional is the sum across all scheduled and terminal transactions in S1, S2, and S3.

Aggregate economic duration is the sum of the three exact independent window durations in years using `365 * 24 * 60 * 60` seconds per year.

`annualized_one_way_turnover = aggregate_normalized_traded_notional / aggregate_duration_years`

Despite the historical label “one-way turnover,” no `0.5` factor is applied. Buys and sells each contribute their absolute traded notional, consistent with the frozen cost equation and prior Phase C accounting.

Cash decisions with zero traded notional contribute zero. Terminal liquidation contributes its absolute sold notional.

## 9. Additive asset PnL contribution

Asset-level contribution is calculated from quantities held over each price segment plus transaction fees allocated to that asset.

For a non-rebalance candle after the first mark:

`asset_price_pnl_i = quantity_i * (close_i_current - close_i_previous)`

For a scheduled rebalance candle:

1. carried-position gap PnL before the trade:
   - `quantity_i_before * (open_i - previous_close_i)`;
2. allocate that asset's transaction fee:
   - `-fee_rate * abs(delta_value_i)`;
3. post-trade intrabar PnL:
   - `quantity_i_after * (close_i - open_i)`.

For the first window candle:

- there is no carried gap segment;
- the entry fee and post-trade open-to-close PnL are included.

For final-close liquidation:

- price PnL to the final close is included first;
- liquidation fee is then allocated negatively to the liquidated asset.

For each window and across all windows:

`sum(asset_net_contribution_i) = final_equity - starting_equity`

within absolute tolerance `1e-9 USDT`.

Cash has zero price contribution. No residual “portfolio” bucket is permitted. Any unreconciled residual above tolerance is `EVIDENCE_FAILURE`.

## 10. Window contribution

For each independent window:

`window_net_pnl = final_post_liquidation_equity - 1000`

Positive-window-PnL concentration uses only windows with strictly positive `window_net_pnl`:

`window_positive_share = positive_window_net_pnl / sum(all positive window net pnl)`

If total positive window net PnL is zero, any gate requiring positive-window breadth or concentration fails; shares are retained as `null`, not coerced to zero.

## 11. Non-overlapping full-week contribution

A full-week contribution bucket begins immediately before its scheduled Monday rebalance and ends after the Sunday `20:00 UTC` close mark, including any terminal liquidation at that close.

`full_week_net_pnl = ending_equity - starting_gross_equity_before_monday_rebalance`

Thus each bucket includes:

- the Monday rebalance fee;
- all price PnL through the Sunday close;
- terminal liquidation fee when the window ends at that Sunday close.

The 39 full-week buckets align exactly with the 39 DSR observations, although DSR uses returns and concentration uses absolute USDT PnL.

The S3 one-day terminal stub is retained as `terminal_stub_net_pnl` for reconciliation but is excluded from the full-week positive-PnL concentration gates because it is not a full week and is forced cash. Its liquidation fee remains included in asset, window, aggregate-return, turnover, drawdown, and exposure accounting.

Positive-week concentration uses only full-week buckets with strictly positive net PnL:

- maximum one-week positive-PnL share;
- sum of the three largest positive-week PnL values divided by total positive full-week PnL.

If total positive full-week PnL is zero, the relevant concentration gates fail and shares are retained as `null`.

## 12. Asset positive-PnL concentration and breadth

For each pair, aggregate net contribution is the sum of its additive asset contribution across all three windows at expected cost.

- positive contributing assets have contribution strictly greater than zero;
- distinct positive-asset count uses pair identity, not lot count;
- maximum asset positive-PnL share is the largest positive asset contribution divided by total positive asset contribution;
- if total positive asset contribution is zero, the breadth and concentration gates fail and the share is retained as `null`.

The frozen gate requires at least four distinct positive contributing assets and maximum asset positive-PnL share at most `45%`.

## 13. Comparator accounting

Comparator cells use the same:

- initial and close-equity timeline;
- post-cost root solver;
- transaction-fee treatment;
- terminal liquidation;
- four-hour return construction;
- drawdown convention;
- turnover normalization;
- manifest and evidence requirements.

Equal-weight comparator targets are:

- frozen top-eight comparator: exactly `1/8` per selected asset, zero cash before costs except the solver-consistent post-cost residual;
- BTC/ETH/SOL comparator: exactly `1/3` per asset, zero cash before costs except the solver-consistent post-cost residual.

Comparators enter only once at the first window open and liquidate only at the final window close. They are not weekly rebalanced.

## 14. Required tests

Implementation tests must prove:

- exact initial, close, and final post-liquidation equity marks;
- no cross-window return;
- rebalance fees enter the correct four-hour and full-week return;
- terminal fees enter the correct final mark;
- partial resizing does not close a lot;
- zero-to-positive and positive-to-zero transitions open and close exactly one lot;
- turnover uses absolute notionals with no hidden `0.5` factor;
- exposure uses economic close marks only;
- asset contributions reconcile to final minus initial equity within `1e-9 USDT`;
- window, asset, full-week, and terminal-stub contributions reconcile without a residual bucket;
- zero-positive-PnL cases retain `null` concentration shares and fail the associated gates;
- comparator accounting uses the same root solver and terminal semantics;
- production and independent reference implementations match every metric and ledger field within frozen tolerances.

## 15. Safety state

This clarification opens no reserved data and authorizes no execution mode.

`C4A_DESIGN_ONLY` / `C4B_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
