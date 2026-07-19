# C4A Large-Liquid Cross-Sectional Momentum Contract V1

## 1. Status and authority

- Stage: `C4A`
- Parent result: `C3A_REJECTED`
- Required base SHA: `72f35dd715874dc2e7c355511675dec29642b430`
- Contract status: `DESIGN_ONLY`
- Confirmation stage: `C4B_CLOSED`
- Holdout state: `HOLDOUT_CLOSED`
- Paper trading: not authorized
- Shadow trading: not authorized
- Private OKX APIs: not authorized
- Live trading: `FORBIDDEN`

This document preregisters a structurally new development-screen thesis. It does not authorize implementation results, confirmation data access, paper or shadow execution, private exchange calls, leverage, derivatives, shorts, or live trading.

## 2. Why a new thesis is required

C1A rejected three time-series directional families. C2A rejected slow allocation policies over BTC, ETH, and SOL. C3A rejected sparse ETH/SOL residual mean reversion relative to BTC. All three stages produced profits concentrated in S1 while S2 and S3 were negative.

C4A must not retune C1A, C2A, or C3A. It changes the economic mechanism and the research surface:

- C1A ranked each asset against its own history; C4A ranks assets against one another.
- C2A used only BTC, ETH, and SOL; C4A uses a preregistered large-liquid candidate pool and freezes a top-eight universe using only pre-screen liquidity.
- C3A traded short-lived negative residuals; C4A tests whether large, liquid crypto assets near recent highs continue to outperform cross-sectionally over the next week.
- C4A rebalances only once per week, remains spot long-only, and can remain entirely in cash when breadth is weak.
- C4A adds an explicit multiple-testing correction through a frozen Deflated Sharpe Ratio calculation across exactly three candidate policies.

The falsifiable thesis is:

> Among established, liquid OKX USDT spot assets, recent one-week relative strength and proximity to the recent one-week high may contain cross-sectional continuation information. A weekly, long-only top-two rotation that is formed from a pre-screen liquidity universe, uses a breadth-controlled cash state, and pays realistic turnover costs may produce positive and less window-concentrated development returns.

Research motivation comes from published work reporting short-horizon crypto momentum and a size/liquidity dependence in which large, liquid coins exhibit momentum rather than the reversal found in small, illiquid coins. Those papers motivate the hypothesis only; they do not override this frozen contract or its actual OKX evidence.

## 3. Research boundary

### 3.1 Development screen

Only the following economic windows may be read by the C4A screen:

- S1: `2024-01-01T00:00:00Z` inclusive to `2024-04-01T00:00:00Z` exclusive
- S2: `2024-04-01T00:00:00Z` inclusive to `2024-07-01T00:00:00Z` exclusive
- S3: `2024-07-01T00:00:00Z` inclusive to `2024-10-01T00:00:00Z` exclusive

Each window is an independent experiment and starts with `1000 USDT` cash. Positions, cash, signals, and accounting state do not carry across windows.

### 3.2 Formation-only universe period

The universe-formation period is:

- `2023-09-01T00:00:00Z` inclusive to `2024-01-01T00:00:00Z` exclusive

Formation data may be used only to:

- prove complete candidate-pool coverage;
- compute the frozen liquidity ranking;
- initialize the first weekly signal.

Formation data may not contribute PnL, trade counts, Sharpe, Deflated Sharpe Ratio, ranking, or any economic gate statistic.

### 3.3 Closed confirmation period

C4B remains closed:

- C1: `2024-10-01` to `2025-01-01`
- C2: `2025-01-01` to `2025-04-01`
- C3: `2025-04-01` to `2025-07-01`

No C4A implementation, test, evidence generator, source inventory, or workflow may read those candles for economic, statistical, debugging, or startup decisions.

### 3.4 Closed holdout

The final holdout remains closed:

- `2025-07-01T00:00:00Z` inclusive to `2026-07-01T00:00:00Z` exclusive

The holdout may not be downloaded, inspected, summarized, used for startup, used for debugging, or included in artifacts.

### 3.5 Boundary enforcement

- Public data download begins at `2023-09-01T00:00:00Z`.
- The exclusive economic boundary is `2024-10-01T00:00:00Z`.
- Public APIs may return overshoot, but every candle at or after the exclusive boundary must be removed before any research code reads retained data.
- Retained files must have a maximum timestamp strictly earlier than the boundary.
- Missing, duplicate, unordered, or non-four-hour timestamps are evidence failures; forward filling is forbidden.
- Every candidate-pool pair must be inner-aligned on the same completed four-hour timestamps.
- A candidate-pool coverage failure is `EVIDENCE_FAILURE`, not an economic rejection and not permission to substitute another asset.

## 4. Market and execution model

- Exchange data source: public OKX OHLCV only
- Timeframe: `4h`
- Trading mode: spot
- Quote asset: USDT
- Position direction: long only
- Maximum concurrent positions: `2`
- Target invested weight when active: `90%`
- Target cash weight when active: `10%`
- Target weight per selected asset: `45%`
- Borrowing: forbidden
- Margin: forbidden
- Leverage: forbidden
- Shorting: forbidden
- Derivatives: forbidden
- Pyramiding: forbidden
- Partial fills: not modeled
- Order-book data: forbidden
- Funding, open interest, liquidation, sentiment, on-chain, social, market-cap, and private-account data: forbidden

Every signal is calculated after a completed four-hour candle closes. Scheduled rebalances execute at the next completed Monday `00:00 UTC` four-hour open. Window-end liquidation occurs at the last available close of the independent window and pays the applicable one-side cost.

## 5. Frozen candidate pool and liquidity universe

### 5.1 Exact candidate pool

Exactly the following twelve OKX USDT spot pairs are permitted:

1. `BTC/USDT`
2. `ETH/USDT`
3. `SOL/USDT`
4. `XRP/USDT`
5. `DOGE/USDT`
6. `ADA/USDT`
7. `AVAX/USDT`
8. `LINK/USDT`
9. `DOT/USDT`
10. `LTC/USDT`
11. `BCH/USDT`
12. `TRX/USDT`

No asset may be added, removed, renamed, substituted, or mapped to a later token migration inside C4A.

### 5.2 Formation coverage

For every candidate pair, the retained formation period must contain exactly the complete four-hour sequence from `2023-09-01T00:00:00Z` through `2023-12-31T20:00:00Z`.

Every candle must have finite, strictly positive open, high, low, close, and base volume values, with `low <= open/close <= high`.

### 5.3 Liquidity score

For each candidate pair and each completed formation candle:

`quote_volume_proxy[t] = close[t] * base_volume[t]`

The frozen liquidity score is the median of all formation-period `quote_volume_proxy` values.

Rules:

- sort descending by liquidity score;
- resolve exact score ties by lexical pair order;
- select exactly the top `8` pairs;
- freeze that selected universe for all three economic windows and all policies;
- no rolling universe changes are permitted;
- no screen-period return, volatility, or volume may influence universe selection.

The authoritative evidence must retain all twelve scores, exact ranks, selected flags, and the final ordered top-eight universe.

## 6. Frozen weekly signal construction

All calculations use only completed candles and must be shifted so the decision at signal bar `t` cannot read the open, high, low, close, volume, or derived value of bar `t+1` or later.

A scheduled decision is made after the Sunday `20:00 UTC` candle closes when the next candle opens Monday `00:00 UTC`.

For each selected-universe asset `A`:

1. One-week return over exactly `42` four-hour intervals:
   - `weekly_return_A[t] = close_A[t] / close_A[t-42] - 1`
2. One-week high proximity over exactly the most recent `42` completed bars:
   - `weekly_high_A[t] = max(high_A[t-41:t])`
   - `high_proximity_A[t] = close_A[t] / weekly_high_A[t]`
3. Positive-momentum eligibility:
   - `positive_A[t] = weekly_return_A[t] > 0`
4. Market breadth:
   - `breadth[t] = count(positive_A[t]) / 8`
5. Cross-sectional ranking:
   - higher numeric signal ranks first;
   - exact numeric ties use lexical pair order;
   - percentile ranks use deterministic average-free ordinal ranks from `1` through `8`.

A weekly risk-on decision is permitted only when:

- `breadth[t] >= 0.50`; and
- at least two selected-universe assets have strictly positive weekly return.

Otherwise the target is `100%` cash.

No alternative lookback, rebalance day, breadth threshold, universe size, position count, or target weight may be tried inside C4A.

## 7. Frozen candidate policies

Exactly three policies are screened.

### 7.1 `C4AWeeklyReturnTopTwo`

- Rank the eight selected assets by `weekly_return`, descending.
- Only assets with strictly positive weekly return are eligible.
- When risk-on is permitted, hold the top two eligible assets at `45%` target weight each and `10%` cash.

### 7.2 `C4AHighProximityTopTwo`

- Restrict to assets with strictly positive weekly return.
- Rank eligible assets by `high_proximity`, descending.
- When risk-on is permitted, hold the top two eligible assets at `45%` target weight each and `10%` cash.

### 7.3 `C4ACompositeMomentumTopTwo`

For all eight selected assets:

- compute the ordinal rank of weekly return, best rank `8` and worst rank `1`;
- compute the ordinal rank of high proximity, best rank `8` and worst rank `1`;
- `composite_score = (weekly_return_rank + high_proximity_rank) / 2`.

Then:

- restrict to assets with strictly positive weekly return;
- rank by composite score, descending;
- resolve equal composite scores by higher weekly return, then higher high proximity, then lexical pair order;
- when risk-on is permitted, hold the top two eligible assets at `45%` target weight each and `10%` cash.

The three policies are independent preregistered trials. Parameter variants, alternative ranking formulas, and policy mixtures are forbidden.

## 8. Frozen rebalance and accounting semantics

Each policy/window/cost cell is independently simulated from cash.

At a scheduled Monday open:

1. Mark existing positions using that open.
2. Determine the frozen target weights from the prior completed signal bar.
3. Let gross pre-trade equity be cash plus marked position value.
4. Solve post-cost equity `E_after` from:

   `E_after = E_before - fee_rate * sum(abs(target_weight_i * E_after - current_value_i))`

5. Solve the scalar equation deterministically by bisection on `[0, E_before]` until absolute error is at most `1e-12` USDT or `200` iterations are reached.
6. Set each target asset value to `target_weight_i * E_after`.
7. Set post-trade cash to the remaining target cash weight times `E_after`.
8. Reject any non-finite result, negative cash, negative quantity, or accounting residual above `1e-9` USDT.

Additional rules:

- Rebalance trades execute at the same Monday open used for valuation.
- Assets removed from the target are sold; retained assets trade only the required delta.
- No trade occurs between scheduled weekly rebalances.
- No stop loss, profit target, trailing stop, averaging down, or discretionary exit exists.
- A risk-off decision liquidates all positions at the next scheduled Monday open.
- A final open position is liquidated at the final economic candle close of its independent window.
- Entry, rebalance, exit, and terminal liquidation costs apply to absolute traded notional.
- Calculations use full precision; reports may round only for display.

## 9. Costs

One-side all-in cost rates:

- `1.0x`: `0.15%`
- `1.5x`: `0.225%`
- `2.0x`: `0.30%`

Every policy, window, and comparator is run independently at each cost multiplier.

## 10. Required comparators

Exactly four comparators are evaluated for every window and cost multiplier:

1. Cash
2. BTC buy-and-hold
3. Equal-weight buy-and-hold across the frozen top-eight selected universe
4. Equal-weight BTC/ETH/SOL buy-and-hold

Comparator rules:

- Each comparator starts with `1000 USDT` independently in each window.
- Buy-and-hold enters at the first window open and liquidates at the final window close.
- Entry and liquidation pay the same one-side cost as the policy cell.
- Equal-weight comparators use post-cost equal target weights and no intermediate rebalancing.
- Cash has zero trades and zero costs.

The authoritative evidence must retain exactly:

- `27` policy rows: 3 policies × 3 windows × 3 costs
- `36` comparator rows: 4 comparators × 3 windows × 3 costs
- `63` hidden result pointers and `63` matching retained result exports

## 11. Frozen metrics

### 11.1 Standard economic metrics

At expected cost, calculate:

- independent window net returns;
- aggregate compounded net return across S1, S2, and S3;
- aggregate annualized Sharpe from concatenated four-hour marked-to-market return streams;
- maximum drawdown per window;
- total and per-window scheduled active rebalances;
- total closed asset lots;
- annualized one-way turnover;
- invested exposure ratio;
- positive-PnL contribution by window, asset, and non-overlapping week.

Aggregate return is the product of the three independent window equity ratios minus one. No cash or position state carries between windows.

### 11.2 Weekly returns for multiple-testing correction

For every policy at expected cost:

- build non-overlapping weekly net return observations aligned to the frozen Monday rebalance schedule;
- include cash weeks as zero returns;
- concatenate S1, S2, and S3 weekly observations in order;
- do not join returns across independent window boundaries.

### 11.3 Frozen Deflated Sharpe Ratio

The implementation must calculate a Deflated Sharpe probability for each policy using the Bailey and López de Prado method.

Frozen inputs and conventions:

- number of trials `N = 3`;
- trial set is exactly the three C4A policies;
- each trial Sharpe is annualized from the same non-overlapping weekly return convention;
- `sigma_SR` is the sample standard deviation of the three observed weekly Sharpe estimates;
- if `sigma_SR == 0`, the expected maximum Sharpe threshold is `0`;
- otherwise the expected maximum Sharpe threshold is:

  `SR_star = sigma_SR * ((1 - gamma) * Phi^-1(1 - 1/N) + gamma * Phi^-1(1 - 1/(N * e)))`

  where `gamma` is the Euler-Mascheroni constant, `e` is Euler's number, and `Phi^-1` is the standard-normal inverse CDF.

For a policy with observed weekly Sharpe `SR`, sample count `T`, sample skewness `skew`, and ordinary sample kurtosis `kurtosis`:

`DSR = Phi((SR - SR_star) * sqrt(T - 1) / sqrt(1 - skew * SR + ((kurtosis - 1) / 4) * SR^2))`

Rules:

- `T` must be at least `24`;
- non-finite inputs or a non-positive denominator are evidence failures;
- no autocorrelation adjustment, alternative trial count, or alternative Sharpe convention may be substituted inside C4A;
- the production calculation must be reproduced by a separate reference implementation.

## 12. Frozen eligibility gates

A policy is eligible only if every condition passes at expected cost unless explicitly stated otherwise.

### 12.1 Return and stability

- Positive windows: at least `2 of 3`
- Median window net return: strictly positive
- Aggregate expected-cost net return: strictly positive
- Aggregate `1.5x`-cost net return: nonnegative
- Aggregate expected-cost four-hour Sharpe: at least `0.75`
- Deflated Sharpe probability: at least `0.90`
- Maximum expected-cost window drawdown: at most `15%`

### 12.2 Activity and cost

- Scheduled active rebalances: at least `12` aggregate
- Scheduled active rebalances per window: at least `3`
- Closed asset lots: at least `18` aggregate
- Annualized one-way turnover: at most `18x`
- Invested exposure: at most `90%`

### 12.3 Breadth and concentration

- At least `4` distinct selected-universe assets must have strictly positive aggregate net contribution
- Maximum positive-PnL share from one window: at most `70%`
- Maximum positive-PnL share from one asset: at most `45%`
- Maximum positive-PnL share from one non-overlapping week: at most `25%`
- Maximum positive-PnL share from the top three non-overlapping weeks: at most `55%`

Comparator returns provide context only. Beating a comparator does not override any gate.

## 13. Frozen ranking

Eligible policies are ranked lexicographically by:

1. Minimum window net return, descending
2. Deflated Sharpe probability, descending
3. Median window net return, descending
4. Aggregate `1.5x`-cost net return, descending
5. Maximum window drawdown, ascending
6. Annualized one-way turnover, ascending
7. Policy ID, ascending

If no policy passes every gate:

- `economic_result = REJECTED`
- `selected_policy = null`
- C4B remains closed
- no gate may be weakened
- no candidate pool, universe rule, signal, or parameter may be retuned in place

If one policy is selected, C4B still does not open automatically. A separate design-only confirmation contract and explicit independent review are required first.

## 14. Evidence requirements

A later authoritative run must retain and verify:

- exact source SHA, workflow head SHA, base SHA, and PR merge-ref SHA;
- exact twelve-pair formation data and full retained data boundaries;
- candidate coverage, liquidity score, rank, selected flag, and frozen top-eight universe;
- exact weekly schedule and every signal snapshot;
- every rebalance target, pre-trade value, solved post-cost equity, traded delta, fee, quantity, cash, and accounting residual;
- 27 policy rows, 36 comparator rows, 63 hidden pointers, and 63 exports;
- all weekly return observations used for Deflated Sharpe calculations;
- the three trial Sharpes, `sigma_SR`, `SR_star`, skewness, kurtosis, denominator, and DSR value for each policy;
- independent recomputation of universe selection, signals, accounting, metrics, DSR, gates, ranking, and decision;
- effective source inventory, exact source snapshots, complete manifest, and SHA-256 hashes;
- `confirmation_opened=false`, `HOLDOUT_CLOSED`, and `LIVE_FORBIDDEN`.

Any missing evidence, count mismatch, hash mismatch, data gap, timing ambiguity, or reference mismatch is `EVIDENCE_FAILURE`, not an economic result.

## 15. Implementation scope

A later implementation PR may add only the minimum surfaces required for:

- static C4A configuration;
- twelve-pair public-data and boundary guard;
- deterministic formation-liquidity selector;
- deterministic weekly cross-sectional signal and policy engine;
- post-cost rebalance accounting;
- Deflated Sharpe calculation;
- evidence generation;
- separate reference recomputation and finalizer;
- source inventory and retained snapshots;
- focused unit, no-lookahead, accounting, universe, DSR, and evidence-contract tests;
- one temporary final authoritative workflow only after the implementation candidate is frozen.

Normal iteration and visibility must use the existing repository `CI` and `Freqtrade Validation` workflows.

A dedicated C4A workflow is permitted only for the final authoritative screen and evidence capture. It must be Ready-only, exact-SHA-bound, public-data-only, fail closed, always upload evidence, and be removed after the result is frozen.

## 16. Required tests

At minimum, implementation tests must prove:

- exact formation and economic timestamp sequences for all twelve pairs;
- overshoot removal before research reads;
- missing, duplicate, unordered, or invalid candles fail closed;
- liquidity scores use only formation data;
- top-eight selection is deterministic and tie-broken lexically;
- screen-period mutations cannot alter the selected universe;
- weekly decisions use only the prior completed Sunday `20:00 UTC` bar;
- next-open Monday execution and terminal liquidation are exact;
- each policy rank and tie-break rule is exact;
- breadth below `0.50` produces cash;
- fewer than two positive assets produces cash;
- the bisection rebalance solver reaches tolerance and never creates negative cash or quantity;
- all fees, turnover, exposure, contribution, and drawdown calculations are exact;
- DSR matches a separate reference implementation on deterministic fixtures;
- all 27 policy rows, 36 comparator rows, 63 pointers, and 63 exports are retained;
- source snapshots and manifest hashes are complete;
- no active authoritative workflow remains after closeout;
- C4B, holdout, private execution, and live remain closed/forbidden.

## 17. Explicit prohibitions

C4A forbids:

- Hyperopt, grid search, Bayesian optimization, or manual parameter variants;
- a candidate pool other than the exact twelve pairs;
- a selected universe size other than eight;
- rolling or screen-period universe changes;
- daily or intraday rebalance variants;
- alternative lookbacks, thresholds, weights, position counts, or ranking formulas;
- market-cap, order-book, funding, open-interest, liquidation, sentiment, on-chain, social, or private-account data;
- ML, deep learning, LLM-generated signals, or adaptive parameter updates;
- shorting, leverage, borrowing, derivatives, or margin;
- C4B, holdout, paper, shadow, private OKX APIs, or live execution;
- weakening gates after observing results.

## 18. Research references

Motivation and statistical controls were informed by:

- Milan Fičura and Gonul Colak, “Impact of Size and Volume on Cryptocurrency Momentum and Reversal,” SSRN 4378429, revised 2024.
- Victoria Dobrynskaya, “Cryptocurrency Momentum and Reversal,” Journal of Alternative Investments 26(1), 2023, DOI `10.3905/jai.2023.1.189`.
- David H. Bailey and Marcos López de Prado, “The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality,” Journal of Portfolio Management 40(5), 2014, DOI `10.2139/ssrn.2460551`.
- David H. Bailey, Jonathan Borwein, Marcos López de Prado, and Qiji Jim Zhu, “The Probability of Backtest Overfitting,” Journal of Computational Finance, 2015, DOI `10.2139/ssrn.2326253`.

These references motivate the preregistered mechanism and statistical safeguards. They are not evidence that C4A works on the frozen OKX development screen.

`C4A_DESIGN_ONLY` / `C4B_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
