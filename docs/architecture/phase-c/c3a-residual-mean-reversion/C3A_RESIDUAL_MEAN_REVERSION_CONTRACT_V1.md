# C3A Residual Mean-Reversion Contract V1

## 1. Status and authority

- Stage: `C3A`
- Parent result: `C2A_REJECTED`
- Required base SHA: `6546d6ae40c63f38c863dac0f8f1244fde2766bf`
- Contract status: `DESIGN_ONLY`
- Confirmation stage: `C3B_CLOSED`
- Holdout state: `HOLDOUT_CLOSED`
- Paper trading: not authorized
- Shadow trading: not authorized
- Private OKX APIs: not authorized
- Live trading: `FORBIDDEN`

This document preregisters a structurally new development-screen thesis. It does not authorize implementation results, confirmation data access, paper trading, private exchange calls, leverage, derivatives, or live execution.

## 2. Why a new thesis is required

C1A rejected directional breakout, trend-pullback, and dual-momentum families. C2A rejected slow long-only allocation policies because their positive aggregate returns were concentrated in one window while later windows lost money, drawdown exceeded the frozen limit, and turnover exceeded the frozen ceiling.

C3A must not retune C1A or C2A. It changes the economic mechanism:

- C1A and C2A sought persistent directional exposure.
- C3A seeks short-lived rebounds after an altcoin experiences a statistically unusual negative return residual relative to BTC.
- C3A is event-driven and mostly cash.
- C3A uses four-hour completed candles rather than daily allocation decisions.
- C3A never shorts, borrows, uses leverage, or trades derivatives.

The falsifiable thesis is:

> Large negative ETH or SOL return residuals relative to BTC sometimes reflect temporary cross-asset dislocations that mean-revert over the following hours or days. A sparse, long-only spot strategy that buys only the lagging asset after a sufficiently extreme residual, exits after residual normalization or a fixed time limit, and otherwise remains in cash may produce cost-after returns that are less regime-concentrated than the rejected directional policies.

## 3. Research boundary

### 3.1 Development screen

Only the following economic windows may be read by the C3A screen:

- S1: `2024-01-01T00:00:00Z` inclusive to `2024-04-01T00:00:00Z` exclusive
- S2: `2024-04-01T00:00:00Z` inclusive to `2024-07-01T00:00:00Z` exclusive
- S3: `2024-07-01T00:00:00Z` inclusive to `2024-10-01T00:00:00Z` exclusive

Each window is an independent experiment and starts with `1000 USDT` cash.

### 3.2 Startup history

- Startup-data download begins at `2023-09-01T00:00:00Z`.
- Startup history exists only to initialize frozen rolling calculations.
- At least `450` complete four-hour bars must precede the first economic decision in S1 for every required asset.
- Startup bars may not contribute economic PnL, trade counts, ranking, or gate statistics.

### 3.3 Closed confirmation period

C3B remains closed:

- C1: `2024-10-01` to `2025-01-01`
- C2: `2025-01-01` to `2025-04-01`
- C3: `2025-04-01` to `2025-07-01`

No C3A implementation, test, evidence generator, source inventory, or workflow may read those candles for economic or statistical decisions.

### 3.4 Closed holdout

The final holdout remains closed:

- `2025-07-01T00:00:00Z` inclusive to `2026-07-01T00:00:00Z` exclusive

The holdout may not be downloaded, inspected, summarized, used for startup, used for debugging, or included in artifacts.

### 3.5 Boundary enforcement

- The economic boundary is exclusive at `2024-10-01T00:00:00Z`.
- Public APIs may return overshoot, but a guard must remove every candle at or after the exclusive boundary before any research code reads retained data.
- Retained research files must have a maximum timestamp strictly earlier than the boundary.
- Missing or duplicate four-hour timestamps are evidence failures; forward filling is forbidden.
- BTC, ETH, and SOL datasets must be inner-aligned on identical completed four-hour timestamps.

## 4. Market and execution model

- Exchange data source: public OKX OHLCV only
- Pairs:
  - `BTC/USDT`
  - `ETH/USDT`
  - `SOL/USDT`
- Timeframe: `4h`
- Trading mode: spot
- Position direction: long only
- Quote asset: USDT
- Maximum concurrent positions: `1`
- Borrowing: forbidden
- Margin: forbidden
- Leverage: forbidden
- Shorting: forbidden
- Derivatives: forbidden
- Pyramiding: forbidden
- Partial fills: not modeled
- Order-book data: forbidden
- Funding, open interest, liquidation, sentiment, on-chain, social, and private-account data: forbidden

Every signal is calculated after a completed four-hour candle closes. Entry and signal-driven exit occur at the next four-hour candle open. A final open position is liquidated at the last available close of its independent window and pays the applicable one-side cost.

## 5. Frozen signal construction

All calculations use only completed historical bars and must be shifted so the decision at bar `t` cannot read the open, high, low, close, volume, or derived values of bar `t+1` or later.

For alt asset `A` in `{ETH, SOL}`:

1. Compute four-hour log returns:
   - `r_A[t] = log(close_A[t] / close_A[t-1])`
   - `r_BTC[t] = log(close_BTC[t] / close_BTC[t-1])`
2. Estimate trailing BTC beta over the previous `180` completed four-hour returns:
   - `beta_A[t] = cov(r_A, r_BTC) / var(r_BTC)`
   - beta is clipped to `[0.25, 2.50]`
   - a zero or non-finite BTC variance invalidates that signal bar
3. Compute residual return:
   - `e_A[t] = r_A[t] - beta_A[t] * r_BTC[t]`
4. Compute the six-bar cumulative residual:
   - `E_A[t] = sum(e_A[t-5:t])`
5. Standardize `E_A[t]` against the previous `180` completed values of `E_A`:
   - `z_A[t] = (E_A[t] - mean_180[t]) / std_180[t]`
   - non-finite or zero standard deviation invalidates that signal bar
6. Compute the BTC regime filter from the previous `300` completed four-hour closes:
   - `btc_regime_on[t] = close_BTC[t] >= SMA300_BTC[t]`

No alternative lookback, beta estimator, clipping range, residual horizon, z-score threshold, or BTC regime filter may be tried inside C3A.

## 6. Frozen candidate policies

Exactly three policies are screened.

### 6.1 `C3AEthResidualReversion`

- Eligible asset: ETH only
- Entry condition: `z_ETH <= -2.00` and `btc_regime_on = true`
- Entry target: `50%` of current equity in ETH, remainder in cash

### 6.2 `C3ASolResidualReversion`

- Eligible asset: SOL only
- Entry condition: `z_SOL <= -2.00` and `btc_regime_on = true`
- Entry target: `50%` of current equity in SOL, remainder in cash

### 6.3 `C3AStrongestLaggardResidualReversion`

- Eligible assets: ETH and SOL
- Entry condition for each asset: its z-score is `<= -2.00` and `btc_regime_on = true`
- When both assets qualify on the same bar, select the more negative z-score
- Exact z-score ties are resolved by lexical asset order: ETH before SOL
- Entry target: `50%` of current equity in the selected asset, remainder in cash

The three policies differ only by eligible universe. Parameter variants are forbidden.

## 7. Frozen position lifecycle

An open position exits at the next four-hour open after the first completed signal bar satisfying any of:

1. Residual normalization: held asset z-score is `>= -0.25`
2. Regime exit: `btc_regime_on = false`
3. Time exit: position has been held for `18` completed four-hour bars
4. Price stop: position return before exit cost is `<= -6.0%`

Additional rules:

- A new entry cannot occur while a position is open.
- After any exit, a six-bar cooldown must complete before another entry.
- A signal during cooldown is ignored, not queued.
- There is no profit target.
- There is no trailing stop.
- There is no averaging down.
- There is no intrabar stop execution; all signal exits use the next bar open.
- Window-end liquidation is mandatory and independent from the cooldown rule.

## 8. Costs and accounting

Each policy/window/cost cell is independently simulated from cash.

One-side all-in cost rates:

- `1.0x`: `0.15%`
- `1.5x`: `0.225%`
- `2.0x`: `0.30%`

Costs apply to every entry, exit, and terminal liquidation on traded notional.

Accounting requirements:

- Mark equity at every completed four-hour close.
- Preserve cash separately from asset market value.
- Never permit negative cash or asset quantity.
- Round only for displayed reports; calculations use full precision.
- Aggregate return is the product of the three independent window equity ratios minus one.
- Aggregate equity and Sharpe are computed by concatenating the three independent window return streams in S1, S2, S3 order, without carrying positions or cash between windows.
- Profit factor uses closed-trade net PnL after costs.
- Turnover is total one-way traded notional divided by contemporaneous equity, annualized from the exact economic duration.
- Exposure is the fraction of completed economic bars with nonzero asset value.

## 9. Required comparators

Exactly four comparators are evaluated for every window and cost multiplier:

1. Cash
2. BTC buy-and-hold
3. ETH buy-and-hold
4. SOL buy-and-hold

Comparator rules:

- Each comparator starts with `1000 USDT` independently in each window.
- Buy-and-hold enters at the first window open and liquidates at the last window close.
- Entry and liquidation pay the same one-side cost as the policy cell.
- Cash has zero trades and zero costs.

The authoritative evidence must therefore retain exactly:

- `27` policy rows: 3 policies × 3 windows × 3 costs
- `36` comparator rows: 4 comparators × 3 windows × 3 costs
- `63` hidden result pointers and `63` matching retained result exports

## 10. Frozen eligibility gates

A policy is eligible only if all conditions pass at expected cost unless explicitly stated otherwise.

### 10.1 Return and stability

- Positive windows: at least `2 of 3`
- Median window net return: strictly positive
- Aggregate expected-cost net return: strictly positive
- Aggregate `1.5x`-cost net return: nonnegative
- Aggregate expected-cost Sharpe: at least `0.75`
- Aggregate expected-cost profit factor: at least `1.15`
- Maximum expected-cost window drawdown: at most `12%`

### 10.2 Activity and sparsity

- Closed trades: at least `18` aggregate
- Closed trades per window: at least `4`
- Expected-cost exposure: at most `45%`
- Annualized one-way turnover: at most `36x`

### 10.3 Concentration

- Maximum positive-PnL share from one window: at most `70%`
- Maximum positive-PnL share from one closed trade: at most `25%`
- Maximum positive-PnL share from the top three closed trades: at most `55%`

For `C3AStrongestLaggardResidualReversion` only:

- ETH net contribution must be strictly positive
- SOL net contribution must be strictly positive
- Maximum positive-PnL share from one asset: at most `75%`

Single-asset policies are not failed merely for being single-asset; they remain subject to all window and trade concentration gates.

### 10.4 Comparator context

Comparator returns do not override eligibility gates. A policy that beats buy-and-hold but fails stability, drawdown, cost, activity, or concentration remains ineligible.

## 11. Frozen ranking

Eligible policies are ranked lexicographically by:

1. Minimum window net return, descending
2. Median window net return, descending
3. Aggregate `1.5x`-cost net return, descending
4. Maximum window drawdown, ascending
5. Annualized one-way turnover, ascending
6. Policy ID, ascending

If no policy passes every gate:

- `economic_result = REJECTED`
- `selected_policy = null`
- C3B remains closed
- no gate may be weakened
- no parameter may be retuned in place

If one policy is selected, C3B still does not open automatically. A separate design-only confirmation contract and explicit independent review are required first.

## 12. Implementation scope

A later implementation PR may add only the minimum surfaces required for:

- static C3A configuration
- public-data boundary guard
- deterministic residual and policy engine
- evidence generation
- independent evidence finalizer
- source inventory and retained snapshots
- focused unit and integration tests
- one temporary final authoritative workflow when the implementation candidate is frozen

Normal iteration and visibility must use the existing repository `CI` and `Freqtrade Validation` workflows.

A dedicated C3A workflow is permitted only for the final authoritative screen and evidence capture. It must:

- trigger only once from a deliberate Ready transition
- bind exact source SHA and merge-ref SHA
- use public data only
- retain hidden evidence files
- upload the final artifact even on failure
- be removed from `.github/workflows` after the result is frozen
- be retained only as non-executable architecture evidence if needed for provenance

## 13. Required tests

At minimum, implementation must prove:

- all rolling values use past completed bars only
- perturbing future candles cannot change earlier signals, trades, or equity
- beta clipping and zero-variance handling are deterministic
- six-bar residual construction is exact
- entry executes at the next bar open
- every exit rule executes at the next bar open
- time exit occurs after exactly 18 completed held bars
- six-bar cooldown is enforced
- simultaneous ETH/SOL signals use the frozen tie-break rule
- position target never exceeds 50% of equity
- cash and asset quantity never become negative
- no overlapping positions or pyramiding occur
- window cells are independent
- terminal liquidation charges cost
- expected, 1.5x, and 2x costs produce monotonic non-increasing equity for identical trades
- row counts are exactly 27 policy and 36 comparator rows
- hidden pointers and retained exports are exactly 63 and match
- retained data ends before `2024-10-01T00:00:00Z`
- startup coverage is at least 450 completed four-hour bars
- missing, duplicate, or misaligned candles fail closed
- confirmation and holdout timestamps are absent from executable research inputs
- private API credentials and order endpoints are absent
- `LIVE=FORBIDDEN` remains invariant

## 14. Evidence and decision integrity

The finalizer must independently recompute from retained primitive data:

- signals
- trades
- costs
- equity curves
- window metrics
- aggregate metrics
- concentration metrics
- comparator rows
- gate decisions
- ranking and selected policy

The final artifact must include:

- exact source SHA
- exact merge-ref SHA
- configuration snapshot and hash
- effective-source inventory and hashes
- retained source snapshots
- boundary and coverage reports
- 27 policy rows
- 36 comparator rows
- 63 hidden pointers and 63 exports
- trade ledgers
- equity series
- final decision
- complete manifest
- `errors=[]` only when every required check passes

A queued, running, skipped, partially uploaded, SHA-mismatched, boundary-failed, or finalizer-failed run is never an economic PASS or REJECTED result. It is an evidence failure.

## 15. Explicit exclusions

C3A may not include:

- Hyperopt or parameter sweeps
- machine learning or LLM signals
- sentiment or news signals
- on-chain data
- order-book or trade-tape data
- funding, open interest, or liquidation data
- private OKX API calls
- account balances or positions
- derivatives, leverage, borrowing, or shorts
- C1A or C2A parameter changes
- C3B or holdout access
- paper, shadow, or live execution
- threshold changes after seeing C3A results

## 16. Failure handling

- Data download or schema failure: `EVIDENCE_FAILURE`
- Boundary, alignment, startup, or duplicate failure: `EVIDENCE_FAILURE`
- Source or merge-ref mismatch: `EVIDENCE_FAILURE`
- Test, finalizer, inventory, manifest, or artifact failure: `EVIDENCE_FAILURE`
- Complete valid evidence with no eligible policy: `REJECTED`
- Complete valid evidence with exactly one top-ranked eligible policy: `SELECTED`

Economic rejection is a valid result. It must be frozen without retuning, and the next research direction must again be structurally distinct.

`C3B_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
