# C6A Market-Neutral Funding Carry — Contract V1

## 1. Status and authority

- Stage: `C6A`
- Change type: `DESIGN_ONLY`
- Economic result: `NOT_RUN`
- Selectable candidate count: `1`
- C6B confirmation: `CLOSED`
- C5B reserved interval: `CLOSED_AND_UNTOUCHED`
- Holdout: `CLOSED`
- Paper execution: `CLOSED`
- Shadow execution: `CLOSED`
- Live execution: `FORBIDDEN`

This document preregisters one structurally distinct research thesis. It does not authorize implementation, market-data access, an economic run, authenticated APIs, account access, order placement, paper execution, shadow execution, or live execution.

## 2. Why another directional strategy is not justified

The following completed Phase C families are frozen negative results and must not be retuned or rescued:

- C0C: cost-aware EMA walk-forward;
- C1A: price-only breakout, pullback, and dual-momentum families;
- C2A: low-turnover BTC/ETH/SOL spot allocation;
- C3A: ETH/SOL residual mean reversion relative to BTC;
- C4A: weekly cross-sectional price momentum;
- C5A: public-derivatives crowding filter applied to spot allocation.

The repeated blocker is not missing implementation infrastructure. It is the absence of a stable, post-cost return source. C6A therefore tests a different economic mechanism rather than another directional price forecast:

> When perpetual funding is persistently positive and sufficiently exceeds complete two-leg trading costs, a conservatively collateralized long-spot/short-perpetual position may earn market-neutral carry with lower regime dependence than the frozen directional families.

The proposition is falsifiable. Funding carry is not described as risk-free, guaranteed, or automatically profitable.

## 3. Research basis and claim boundary

OKX publishes historical funding-rate data from March 2022 and candlestick archives from July 2023. Its public market-data and public-data APIs require no authentication. Positive funding is paid by perpetual longs to shorts; negative funding is paid by shorts to longs. Funding settlement may occur every 1, 2, 4, or 8 hours and may change with market conditions.

Primary research documents that crypto carry can be large and time-varying because demand for leveraged exposure meets limits to arbitrage. That evidence motivates a prospective test; it does not establish that this exact OKX strategy will pass.

References:

- OKX Historical Market Data: <https://www.okx.com/historical-data>
- OKX API Guide: <https://www.okx.com/docs-v5/en/>
- OKX Perpetual Funding Fee Mechanism: <https://www.okx.com/help/perpetual-futures-funding-fee-mechanism>
- Schmeling, Schrimpf, and Todorov, “Crypto Carry,” *Management Science* (2026): <https://doi.org/10.1287/mnsc.2024.05069>

## 4. Program-level anti-overfitting boundary

### 4.1 C6A development interval

All C6A history is `DEVELOPMENT_ONLY`. No C6A result can directly authorize paper or shadow execution.

- Warm-up/download start: `2023-06-05T00:00:00Z`
- First scored week: `2023-07-03T00:00:00Z`
- Scored end exclusive: `2025-12-29T00:00:00Z`
- Scored weeks: `130`
- Independent stability windows: exactly five consecutive 26-week windows:
  - W1: `2023-07-03T00:00:00Z` to `2024-01-01T00:00:00Z`;
  - W2: `2024-01-01T00:00:00Z` to `2024-07-01T00:00:00Z`;
  - W3: `2024-07-01T00:00:00Z` to `2024-12-30T00:00:00Z`;
  - W4: `2024-12-30T00:00:00Z` to `2025-06-30T00:00:00Z`;
  - W5: `2025-06-30T00:00:00Z` to `2025-12-29T00:00:00Z`.

The implementation must fail before economic evaluation if complete warm-up and scored coverage cannot be obtained from permitted public sources.

### 4.2 C5B remains closed

No timestamp at or after `2025-12-29T00:00:00Z` may be retained, read, summarized, used for debugging, hashed into C6A economic evidence, or used to alter this contract.

In particular, the separately reserved C5B interval beginning `2026-01-05T00:00:00Z` remains closed and cannot be repurposed as C6A data.

### 4.3 Future C6B

A future confirmation period may be considered only if C6A passes every unchanged gate and a separate design-only authorization is merged. C6A does not open C6B. Any C6B interval must be prospectively collected and must not reuse the closed C5B interval.

## 5. Fixed instruments and public inputs

### 5.1 Spot legs

- `BTC-USDT`
- `ETH-USDT`

### 5.2 USDT-margined perpetual legs

- `BTC-USDT-SWAP`
- `ETH-USDT-SWAP`

### 5.3 Required public data

- one-hour spot trade candles;
- one-hour perpetual trade candles;
- one-hour perpetual mark-price candles;
- realized historical funding rates with exact `fundingTime` and `realizedRate`;
- public instrument metadata required to convert contract counts to base-currency exposure, including contract value, contract-value currency, lot size, minimum size, listing state, and tick size.

Permitted sources are limited to:

- OKX downloadable historical-data files;
- `GET /api/v5/market/history-candles`;
- `GET /api/v5/market/history-mark-price-candles`;
- `GET /api/v5/public/funding-rate-history`;
- `GET /api/v5/public/instruments`.

No authenticated endpoint, order book, account balance, position, order, fill, private fee tier, borrowing, lending, staking, or external yield is permitted.

## 6. Data integrity and variable funding intervals

For every retained series:

- timestamps must be UTC, unique, and strictly increasing;
- only completed candles are permitted;
- required one-hour candles must be gap-free over the retained interval;
- prices must be finite and strictly positive;
- volumes and rates must be finite;
- duplicate or contradictory funding settlements fail closed;
- instrument metadata must unambiguously support base-equivalent hedge conversion;
- all overshoot rows at or after the exclusive boundary must be removed before research read and recorded;
- all retained inputs must be hashed into the final manifest.

Funding rates are applied exactly at their actual settlement timestamps. The implementation must not assume a fixed eight-hour interval, multiply a per-settlement rate by three, or compare raw rates without respecting the realized settlement schedule.

For a lookback interval, cumulative funding is the arithmetic sum of the realized per-settlement rates inside that interval. Missing expected settlement evidence, unexplained schedule gaps, or ambiguous interval semantics fail closed.

## 7. Decision and execution schedule

A portfolio decision occurs every Monday at `00:00:00Z`.

The decision may use only:

- completed one-hour candles ending before the decision timestamp;
- funding settlements with `fundingTime < decision_time`;
- frozen public instrument metadata effective no later than the decision time.

At a timestamp shared by a funding settlement and a modeled trade, funding is applied first to the position carried into that timestamp; modeled trades occur second. A newly opened position therefore cannot collect the same-timestamp settlement, while a position closed at that timestamp first pays or receives it.

Trades are modeled at the Monday one-hour trade-candle open. No intrabar price selection is permitted.

## 8. Frozen funding signal

For each asset `i` at Monday decision `t`:

```text
funding_sum_28d_i(t)
  = sum(realizedRate_j)
    for fundingTime_j in [t - 28 days, t)

positive_funding_share_28d_i(t)
  = count(realizedRate_j > 0)
    / count(all realized settlements in [t - 28 days, t))
```

The realized rate is used once per actual settlement. No fixed-frequency annualization is used in the decision.

An asset is carry-eligible only when all conditions hold:

```text
funding_sum_28d_i(t) > 0.009
positive_funding_share_28d_i(t) >= 2/3
abs(mark_close_i / spot_close_i - 1) <= 0.02
```

`0.009` equals 1.5 times the expected complete two-leg round-trip cost of `0.006` of paired notional. These thresholds are fixed and not tunable.

## 9. Single selectable candidate

Candidate ID:

```text
C6AMarketNeutralFundingCarry
```

### 9.1 Position construction

For each eligible asset, create one dedicated sleeve. Total current equity is divided equally among eligible sleeves. If neither asset is eligible, the portfolio is 100% USDT cash.

For sleeve capital `C_i`:

```text
spot_target_notional_i = C_i / 3
perpetual_short_target_notional_i = spot_target_notional_i
reserved_USDT_collateral_i = 2 * C_i / 3
```

The short perpetual base-equivalent quantity must equal the rounded spot base quantity within the frozen hedge tolerance defined in the accounting addendum.

This produces initial perpetual notional equal to at most 50% of its dedicated collateral. There is no borrowed spot, no external margin transfer, no cross-asset collateral support, and no leverage increase after entry.

### 9.2 Weekly rebalance

At each Monday decision:

- close a sleeve that is no longer eligible;
- open a newly eligible sleeve;
- equalize sleeve capital across currently eligible assets;
- preserve exact base-equivalent spot/perpetual hedge matching;
- skip resizing an already active sleeve when its one-way paired-notional adjustment is less than 10% of its current paired notional.

The 10% resizing band is fixed and not tunable.

### 9.3 Risk exits

A sleeve is forcibly closed at the next available one-hour open when either condition is first observed:

- dedicated perpetual collateral equity divided by current short notional is less than `1.25`;
- absolute mark/spot basis exceeds `0.05` at a completed one-hour observation.

The breach and forced-close economics remain in evidence. Eligibility requires zero collateral-buffer breaches; a forced close cannot be erased or reclassified as missing data.

### 9.4 Terminal liquidation

All remaining spot and perpetual positions are closed at the final scored boundary using the same cost and rounding rules. No open position may remain outside the C6A interval.

## 10. Costs

All-in one-side modeled execution cost per leg:

- expected: `0.0015`;
- stress 1.5x: `0.00225`;
- stress 2.0x: `0.0030`.

Each opening, closing, or resizing transaction charges the applicable cost separately on the spot leg and perpetual leg. At expected cost, opening and later closing a paired position costs `0.006` of paired notional before any intermediate resizing.

No maker rebate, VIP fee, referral rebate, spread income, staking yield, lending yield, or unmodeled cash yield is credited.

## 11. Non-selectable comparators

The same evidence package must compute:

1. `CashComparator`: 100% USDT, zero return;
2. `AlwaysOnDeltaNeutralComparator`: always-active equal-weight BTC/ETH sleeves using identical collateral, hedge, rounding, cost, funding, margin-buffer, and weekly resizing rules, but no funding eligibility filter;
3. `SpotBuyAndHoldComparator`: equal-weight BTC/ETH spot buy-and-hold, descriptive only.

Comparators are never selectable.

## 12. Frozen eligibility gates

The candidate is `SELECTED` only if every gate passes at expected cost unless a different cost is explicitly named:

### 12.1 Window and aggregate economics

- each of W1–W5 has net return `> 0`;
- aggregate net return `> 0`;
- aggregate net return at 1.5x cost `> 0`;
- aggregate net return at 2.0x cost `>= 0`.

### 12.2 Risk and statistical evidence

- aggregate annualized weekly Sharpe `>= 1.00`;
- weekly PSR versus zero weekly Sharpe `>= 0.95`;
- maximum drawdown `<= 10%`;
- zero collateral-buffer breaches;
- zero unhedged or over-hedged observations outside the frozen tolerance.

### 12.3 Cost and activity

- annualized one-way paired-notional turnover `<= 6.0x`;
- gross funding receipts divided by total modeled trading costs `>= 2.0`;
- at least `52` active weekly buckets overall;
- at least `6` active weekly buckets in every 26-week window;
- at least `100` retained funding settlements while positions are active.

### 12.4 Breadth and concentration

- both BTC and ETH have positive net contribution;
- maximum positive-asset PnL share `<= 70%`;
- maximum positive-window PnL share `<= 40%`;
- maximum positive-week PnL share `<= 15%`;
- top-three positive-week PnL share `<= 35%`.

### 12.5 Incremental value over always-on carry

At expected cost:

- candidate aggregate net return minus always-on aggregate net return `> 0`;
- candidate annualized Sharpe minus always-on annualized Sharpe `>= 0.10`;
- candidate maximum drawdown `<=` always-on maximum drawdown;
- candidate annualized turnover `<=` always-on annualized turnover.

No relatively best but ineligible result may be promoted.

## 13. Statistics and multiple testing

C6A has exactly one selectable candidate and no parameter variants, ranking, Hyperopt, ML, LLM signal, or post-result threshold search.

Weekly PSR is a within-stage descriptive probability for the single C6A candidate. It does not correct or erase the broader C0C-through-C6A sequential research history. The evidence must state:

```text
within_stage_dsr_used = false
weekly_statistic = PSR_NOT_DSR
program_level_sequential_history_corrected = false
```

## 14. Required evidence

A future implementation must retain and independently recompute at minimum:

- exact source, design, merge-ref, workflow, run, and input hashes;
- public-source inventory and exact source snapshots;
- candle, funding, metadata, boundary, and coverage reports;
- every weekly decision and eligibility input;
- every spot and perpetual quantity, contract conversion, fee, funding settlement, mark PnL, and cash movement;
- collateral-equity and hedge-tolerance observations;
- weekly and window equity reconciliation;
- candidate and comparator rows at all three costs;
- exact gate numerators, denominators, margins, and unrounded candidate-minus-comparator differences;
- complete manifest with independent size and SHA-256 verification.

The independent recomputation must not import the production candidate engine.

## 15. Failure handling and prohibited actions

Any ambiguity in data coverage, settlement timing, contract conversion, fee accounting, hedge equality, margin state, or evidence reconciliation is an evidence failure, not an economic pass.

Prohibited:

- changing thresholds, costs, windows, assets, lookbacks, allocation, collateral, or gates after observing results;
- using C5B timestamps;
- adding strategy variants or selecting the best lookback;
- assuming an eight-hour settlement frequency;
- claiming the strategy is arbitrage, risk-free, or paper-ready;
- using private OKX APIs or account-specific fee/margin data;
- opening C6B, holdout, paper, shadow, or live execution from this document.

## 16. Final design state

`C6A_DESIGN_ONLY`

`C6A_ECONOMIC_RESULT_NOT_RUN`

`C6B_CLOSED`

`C5B_CLOSED_AND_UNTOUCHED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
