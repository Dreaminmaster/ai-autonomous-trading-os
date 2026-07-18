# C3A Execution and Accounting Addendum V1

## 1. Authority

This addendum is normative and forms one preregistered C3A design together with `C3A_RESIDUAL_MEAN_REVERSION_CONTRACT_V1.md`.

- Stage: `C3A`
- Required base SHA: `6546d6ae40c63f38c863dac0f8f1244fde2766bf`
- Parent result: `C2A_REJECTED`
- Contract status: `DESIGN_ONLY`
- C3B: `CLOSED`
- Holdout: `CLOSED`
- Live: `FORBIDDEN`

Where this addendum resolves an indexing, execution, or metric ambiguity, this addendum controls. It does not change any policy parameter, cost, gate, ranking rule, research window, or safety restriction in the main contract.

## 2. Bar and signal indexing

Let retained, aligned four-hour bars be indexed by increasing integer `t`. A row timestamp identifies the opening time of that four-hour candle. The candle is complete only after its close.

At the close of bar `t`:

1. `r_A[t] = log(close_A[t] / close_A[t-1])`.
2. `beta_A[t]` uses exactly the 180 return pairs ending at `t-1`: `r_A[t-180:t]` and `r_BTC[t-180:t]` in half-open Python notation. The current return `r_A[t]` is excluded from beta estimation.
3. Covariance and variance use the same population denominator (`ddof=0`), so the beta ratio is deterministic. A non-finite or zero BTC variance invalidates the signal bar.
4. `e_A[t] = r_A[t] - beta_A[t] * r_BTC[t]`.
5. `E_A[t]` is the inclusive six-residual sum `e_A[t-5] + ... + e_A[t]`.
6. The z-score reference sample contains exactly the 180 cumulative residuals ending at `t-1`: `E_A[t-180:t]`. `E_A[t]` is excluded from its own mean and standard deviation.
7. The z-score standard deviation uses population convention (`ddof=0`). A non-finite or zero value invalidates the signal bar.
8. `SMA300_BTC[t]` is the arithmetic mean of the 300 completed BTC closes from `close_BTC[t-299]` through `close_BTC[t]`, inclusive.
9. `btc_regime_on[t] = close_BTC[t] >= SMA300_BTC[t]`.

A decision generated after the close of bar `t` may execute only at the open of bar `t+1`. No open, high, low, close, volume, or derived value from `t+1` may influence the decision.

## 3. Independent-window state

Each S1/S2/S3 cell resets at the first window open to:

- `1000 USDT` cash;
- zero asset quantity;
- no open trade;
- no cooldown;
- zero trade, turnover, and exposure counters.

Rolling indicators may use any retained completed bar strictly earlier than the current decision bar, including startup history and, for S2/S3, earlier screen-window bars. Positions, cash, cooldown, trades, and PnL never carry between windows.

Only a signal whose decision close lies inside the current economic window and whose execution open is also inside that window may create a new entry. A final-bar entry signal with no in-window next open is ignored. No signal may execute at or after the exclusive `2024-10-01T00:00:00Z` boundary.

## 4. Entry execution and costs

Let:

- `E` be pre-trade equity marked at the entry open;
- `f` be the one-side cost rate;
- `x` be entry asset market value immediately after the fill, before later price movement.

To make the post-cost portfolio exactly 50% asset and 50% cash, use:

`x = 0.5 * E / (1 + 0.5 * f)`

Then:

- entry quantity `q = x / entry_open`;
- entry cost `c = f * x`;
- post-entry cash `E - x - c`;
- post-entry equity `E - c`;
- asset value and cash are each exactly 50% of post-entry equity, within floating-point tolerance.

The engine must reject, rather than repair, any calculation producing negative cash, negative quantity, non-finite values, or an asset share above 50% of post-cost equity beyond numerical tolerance.

## 5. Exit execution and terminal liquidation

For a position with quantity `q` exiting at price `p`:

- gross proceeds are `q * p`;
- exit cost is `f * q * p`;
- net cash proceeds are `q * p * (1 - f)`.

Signal exits execute at the next bar open. Terminal liquidation executes at the final available close inside the independent window and is included in final equity, closed-trade count, PnL, turnover, and concentration calculations.

The price-stop return observed at close `t` is the gross price return `close_A[t] / entry_open - 1`. It excludes the already-paid entry cost and the prospective exit cost. If it is at or below `-6%`, the exit executes at open `t+1` and pays the normal exit cost.

When multiple exit conditions become true on the same decision bar, the economic execution is identical. The retained reason field uses the main-contract order: residual normalization, regime exit, time exit, then price stop.

## 6. Exact holding-period and cooldown rules

If entry executes at open of bar `j`, bar `j` is held bar 1. The closes of bars `j` through `j+17` are the 18 completed held bars. The time-exit decision is generated at close `j+17` and executes at open `j+18`, provided that open lies inside the window. Window-end liquidation takes precedence when no such in-window open exists.

If an exit executes at open of bar `k`, bars `k` through `k+5` are the six cooldown bars. Signals at their closes are ignored. The earliest new entry may execute at open `k+6`, from a qualifying signal at close `k+5` after all six cooldown bars have completed.

A terminal liquidation ends the cell; no cooldown or re-entry follows it.

## 7. Equity series and returns

Each cell retains:

- starting equity immediately before the first economic-window open;
- close-marked equity for every completed economic bar after any execution at that bar's open;
- final post-cost terminal-liquidation equity at the last window close.

Four-hour return observations are consecutive percentage changes in this retained equity sequence. No startup return contributes to economic metrics.

Maximum drawdown is computed from the running peak of the retained equity sequence, including starting equity and final post-liquidation equity.

## 8. Sharpe, profit factor, turnover, and exposure

### 8.1 Sharpe

- Risk-free rate: zero.
- Mean: arithmetic mean of retained four-hour equity returns.
- Standard deviation: sample standard deviation (`ddof=1`).
- Annualization factor: `sqrt(365 * 6)`.
- Fewer than two returns, a zero/non-finite standard deviation, or a non-finite result makes the Sharpe gate fail closed.

Aggregate Sharpe uses the concatenated independent-window return streams in S1, S2, S3 order, with no artificial return inserted between windows.

### 8.2 Profit factor

Closed-trade net PnL includes entry and exit costs.

- `gross_profit = sum(max(trade_net_pnl, 0))`.
- `gross_loss = abs(sum(min(trade_net_pnl, 0)))`.
- If `gross_profit == 0`, profit factor is `0`.
- If `gross_profit > 0` and `gross_loss == 0`, profit factor is represented as the string `Infinity` and the `>= 1.15` gate passes.
- Otherwise profit factor is `gross_profit / gross_loss`.

### 8.3 Turnover

For every entry, exit, and terminal liquidation, one-way turnover contribution is:

`traded_notional / pre-trade_equity`

Aggregate annualized one-way turnover is:

`sum(all one-way contributions) * (365 * 6) / total_economic_four_hour_bars`

The denominator is the total number of completed economic bars across S1, S2, and S3. Window turnover uses the same formula with that window's bar count.

### 8.4 Exposure

A bar is exposed when close-marked asset value after any open execution is strictly positive. Aggregate exposure is exposed economic bars divided by total economic bars. The terminal liquidation at the final close does not create an additional bar.

## 9. Trade and concentration metrics

A closed trade includes normal exits and terminal liquidations. Trade net PnL includes both entry and exit costs.

For trade concentration:

- denominator is total positive closed-trade net PnL;
- single-trade share is the largest positive trade PnL divided by that denominator;
- top-three share is the sum of the three largest positive trade PnLs divided by that denominator;
- if the denominator is zero, both shares are conservatively set to `1.0` and their gates fail.

For window concentration:

- compute each window's net PnL as final post-cost equity minus `1000 USDT`;
- denominator is `sum(max(window_net_pnl, 0))`;
- maximum window share is `max(max(window_net_pnl, 0)) / denominator`;
- if the denominator is zero, the share is set to `1.0` and the gate fails.

For `C3AStrongestLaggardResidualReversion` asset contribution:

- ETH and SOL contribution are sums of closed-trade net PnL for trades in that asset;
- the positive-asset denominator is `sum(max(asset_net_pnl, 0))`;
- maximum positive-asset share uses that denominator;
- if the denominator is zero, the share is set to `1.0` and the asset-contribution gates fail.

## 10. Data alignment and failure behavior

The retained BTC/ETH/SOL datasets must each contain the same strictly increasing four-hour timestamp sequence after boundary sanitization. Inner alignment may identify the common sequence but may not silently hide a missing timestamp in any asset. The guard must first prove that every required timestamp exists exactly once in every asset, then construct the aligned frame.

Any of the following is `EVIDENCE_FAILURE`, not an economic result:

- a missing, duplicate, unordered, or misaligned timestamp;
- a retained timestamp at or after the exclusive boundary;
- fewer than 450 completed startup bars before the first S1 decision;
- non-finite prices, returns, equity, quantity, cash, or required metrics;
- a row-count, pointer-count, export-count, source-inventory, hash, or exact-SHA mismatch;
- any read of C3B or holdout candles;
- any private API, account, order, leverage, derivative, short, paper, shadow, or live path.

`C3B_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
