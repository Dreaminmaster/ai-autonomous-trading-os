# C2A Low-Turnover Allocation Screen Contract V1

## 1. Status and authority

- Stage: `C2A`
- Contract state: `PREREGISTERED_NOT_EXECUTED`
- Parent main SHA: `c57a0b1ca2df1600b71e32e92d5b061ee1a76db0`
- Parent economic result: `C1A_REJECTED`
- C2B confirmation: `CLOSED`
- Holdout: `CLOSED`
- Live: `FORBIDDEN`

This document defines a new strategy thesis. It does not retune C0C or C1A, reinterpret their negative results, or authorize confirmation, paper trading, shadow trading, private OKX APIs, derivatives, leverage, or live execution.

## 2. Why this stage exists

C0 and C1 established three facts:

1. intraday directional activity can show gross edge while expected fees reverse the result;
2. the C1A breakout and dual-momentum families produced positive aggregate returns but failed stability, breadth, trade-count, and concentration gates;
3. more frequent trade-level logic is therefore not the next justified experiment.

C2A tests a structurally different hypothesis: a slow portfolio-allocation policy with explicit cash, turnover controls, and next-bar execution may retain part of the market's positive drift while reducing fee drag and concentration.

External research is rationale only, not project evidence. Recent studies emphasize realistic transaction costs, turnover penalties, non-Gaussian crypto returns, and state-dependent momentum. C2A adopts only the general design lesson that portfolio construction and turnover must be tested directly; it does not import any reported performance claim.

## 3. Research question

Can one fixed, low-turnover, long-only spot allocation policy across `BTC/USDT`, `ETH/USDT`, `SOL/USDT`, and cash satisfy all preregistered net-of-cost stability, drawdown, breadth, and turnover gates on the already opened C1A screen period?

A valid answer may be `REJECTED`.

## 4. Data boundary

### 4.1 Permitted data

- Exchange: OKX public spot OHLCV only.
- Assets: `BTC/USDT`, `ETH/USDT`, `SOL/USDT`.
- Signal timeframe: `1d`.
- Startup download may begin at `2023-05-01` solely to calculate fixed trailing indicators.
- Economic screen begins at `2024-01-01`.
- Exclusive C2A boundary: `2024-10-01T00:00:00Z`.
- Before the first S1 decision, each asset must retain at least `220` consecutive completed daily candles; this is startup coverage only and is excluded from economic metrics.

### 4.2 Screen windows

- S1: `2024-01-01` to `2024-04-01`.
- S2: `2024-04-01` to `2024-07-01`.
- S3: `2024-07-01` to `2024-10-01`.

### 4.3 Closed data

- C2B-C1: `2024-10-01` to `2025-01-01`.
- C2B-C2: `2025-01-01` to `2025-04-01`.
- C2B-C3: `2025-04-01` to `2025-07-01`.
- Holdout: `2025-07-01` to `2026-07-01`.

No C2A code, test, workflow, log, artifact, or diagnostic may read candles at or beyond the exclusive C2A boundary. Overshoot must be sanitized before any strategy module or simulator reads the data.

## 5. Common portfolio mechanics

All candidate policies use the same frozen mechanics:

- starting equity: `1000 USDT`;
- spot, long-only, no borrowing, no leverage, no shorting;
- cash weight may range from `0%` to `100%`;
- decisions use completed daily candles only;
- targets are calculated after the UTC daily close and executed at the next available daily open;
- scheduled rebalance: first available daily bar on or after the first UTC calendar day of each month;
- no intramonth discretionary rebalance;
- no stop-loss, take-profit, trailing stop, pyramiding, averaging down, or position adjustment outside the scheduled rebalance;
- target-weight changes below `10` percentage points are not traded;
- one-way gross turnover at one rebalance may not exceed `50%` of pre-trade equity;
- when the unconstrained target exceeds the turnover cap, changes are scaled proportionally;
- weights are rounded down to exchange-compatible precision; residual value remains cash;
- missing, duplicate, stale, non-finite, or non-positive prices fail closed.

## 6. Frozen candidate policies

Exactly three policies are screened. No parameter search, Hyperopt, random search, Bayesian optimization, ML, LLM signal generation, sentiment, on-chain data, order-book data, or private API data is allowed.

### 6.1 `C2AEqualWeightRiskOn`

At each rebalance:

1. an asset is eligible when its completed-candle `90`-day total return is strictly positive;
2. the portfolio is risk-on only when BTC's completed-candle close is strictly above its `200`-day simple moving average;
3. when risk-on, eligible assets receive equal target weights;
4. ineligible allocations and all allocations when risk-off remain cash.

### 6.2 `C2AInverseVolRiskOn`

The eligibility and BTC regime rules are identical to `C2AEqualWeightRiskOn`.

When risk-on, eligible assets receive inverse-volatility weights using `30` completed daily log returns. Each asset is capped at `50%`; excess is redistributed once among uncapped eligible assets, and any remaining excess stays cash.

### 6.3 `C2ATopTwoPersistentMomentum`

At each rebalance:

1. an asset is eligible when both its completed-candle `90`-day and `180`-day total returns are strictly positive;
2. rank eligible assets by `180`-day return, then `90`-day return, then fixed symbol order `BTC`, `ETH`, `SOL`;
3. hold at most the top two eligible assets;
4. one eligible asset receives `50%` and the remaining `50%` stays cash;
5. two eligible assets receive `50%` each;
6. no eligible asset means `100%` cash.

This is a monthly portfolio allocation rule, not an in-place modification of the rejected C1A dual-momentum trade strategy.

## 7. Cost model

Costs are applied to absolute traded notional on every buy and sell.

- `1.0x`: `0.0015` per side.
- `1.5x`: `0.00225` per side.
- `2.0x`: `0.0030` per side.
- slippage is included in these all-in rates and must not be added twice.
- cash earns zero.

The economic decision uses `1.0x` as expected cost and `1.5x` as stress cost. `2.0x` is retained as severe-cost evidence.

## 8. Required comparators

The artifact must include non-selectable comparators calculated with the same dates and accounting conventions:

1. `100%` cash;
2. BTC buy-and-hold;
3. static equal-weight BTC/ETH/SOL buy-and-hold, established at S1 start and never rebalanced;
4. the frozen C1A result document as historical context only.

Comparators cannot be selected as C2A winners.

## 9. Accounting and retained evidence

A deterministic portfolio simulator must retain, for every policy/window/cost cell:

- input candle hashes and boundary report;
- signal dates and the exact completed candles used;
- pre-trade weights, unconstrained targets, no-trade-band decisions, turnover-cap scaling, final targets, fills, fees, and post-trade weights;
- daily equity, cash, holdings, gross return, net return, drawdown, and asset-level PnL attribution;
- rebalance count, one-way turnover, annualized turnover, time in cash, and exposure by asset;
- source SHA, merge-ref SHA, workflow source snapshot, effective runtime configuration, dependency versions, command/log hashes, result hashes, source inventory, and independent final evidence.

An independent finalizer must recompute the ledger from retained candles and decisions rather than trusting summary fields.

## 10. Implementation validity

The stage is an evidence failure, not an economic rejection, when any of the following occurs:

- the exact source or merge-ref cannot be verified;
- a closed date is read;
- a signal uses an incomplete candle or same-bar execution;
- any price, weight, fee, turnover, equity, or attribution reconciliation fails;
- candidate count is not exactly `3`;
- retained economic rows are not exactly `27` (`3 policies × 3 windows × 3 costs`);
- hidden pointers, source snapshots, manifests, or required logs are absent from the artifact;
- private credentials are non-empty, API server is enabled, or execution is not spot dry-run/research-only;
- final evidence reports an error.

Workflow success alone is not economic success.

## 11. Frozen eligibility gates

A policy is eligible only when every condition below passes at expected cost unless stated otherwise:

1. at least `2` of `3` windows have strictly positive net return;
2. median window net return is strictly positive;
3. aggregate net return is strictly positive;
4. aggregate net return at `1.5x` cost is non-negative;
5. maximum window drawdown is at most `15%`;
6. aggregate daily-return Sharpe ratio, using `365` annualization and zero risk-free rate, is at least `0.75`;
7. total scheduled rebalances with a non-zero executed trade are at least `4`;
8. every window contains at least `1` non-zero executed rebalance unless the policy is continuously and correctly `100%` cash, in which case it remains economically ineligible rather than failing implementation;
9. annualized one-way turnover is at most `6.0` times equity;
10. no asset contributes more than `70%` of total positive asset-level PnL;
11. no window contributes more than `60%` of total positive window PnL;
12. the largest single positive daily contribution is at most `25%` of total positive daily contributions;
13. the top three positive daily contributions together are at most `50%` of total positive daily contributions;
14. positive asset breadth is at least `2` assets;
15. when static equal-weight buy-and-hold is positive, the policy's aggregate net return must be at least `50%` of that comparator or its maximum drawdown must be at least `40%` lower; when the comparator is non-positive, this gate passes if the policy aggregate net return is positive.

No gate may be weakened after results are visible.

## 12. Frozen ranking

Select at most one eligible policy. Rank only eligible policies by:

1. highest minimum window net return;
2. highest median window net return;
3. highest aggregate `1.5x`-cost net return;
4. lowest maximum window drawdown;
5. lowest annualized turnover;
6. lexical policy name.

If no policy is eligible, the result is `REJECTED` and `selected_policy=null`.

## 13. Workflow and review sequence

1. Freeze this contract on main through a planning-only PR.
2. Open a separate implementation PR from the exact frozen-contract main SHA.
3. Keep the implementation PR Draft during development.
4. Validate its exact head with focused tests, CI, and Freqtrade Validation for repository/runtime safety.
5. Perform an independent read-only exact-SHA readiness review.
6. Mark Ready exactly once to trigger one authoritative C2A workflow.
7. Independently download and verify the artifact digest and retained evidence.
8. Record a comment-only artifact review anchored to the exact source SHA.
9. Freeze the valid `SELECTED` or `REJECTED` result before merge.
10. Merge only after exact-head post-result validation and final merge review.

Queued or in-progress runs are never PASS. Obsolete SHAs are never rerun or reused as evidence.

## 14. Post-result rules

- `SELECTED` authorizes only preparation of a separate C2B confirmation contract.
- C2B remains closed until that contract is frozen on main.
- `REJECTED` is a valid result and does not authorize threshold reduction or in-place retuning.
- Neither outcome authorizes paper, shadow, holdout, private OKX APIs, derivatives, leverage, or live execution.

`CONFIRMATION_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
