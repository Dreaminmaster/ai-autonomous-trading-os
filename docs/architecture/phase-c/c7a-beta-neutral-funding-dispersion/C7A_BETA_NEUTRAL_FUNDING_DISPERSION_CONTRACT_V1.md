# C7A beta-neutral funding-dispersion — contract V1

## 1. Status and authority

- stage: `C7A`
- change type: `DESIGN_ONLY`
- selectable candidate count: `1`
- economic result: `NOT_RUN`
- C6A: `CLOSED_SELECTED_POLICY_NULL`
- C6B: `CLOSED_NOT_OPENED`
- C7B confirmation: `CLOSED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

This document preregisters one new thesis. It authorizes no implementation, real-data access, download, economic run, authenticated API, account access, order placement, paper execution, shadow execution, or live execution.

## 2. Structural reset after C6A

C6A required point-in-time historical spot and perpetual instrument metadata to prove exact same-asset hedge conversion. That authority could not be established and must not be weakened or reconstructed backward from current metadata.

C7A removes that dependency rather than rescuing C6A:

- both legs are USDT-margined perpetuals;
- research PnL is computed in continuous USDT notional and percentage returns;
- no historical contract count, lot size, minimum size, contract value, or listing-state transition is used in economic selection;
- any future paper implementation must separately validate current executable sizing and rounding from current official metadata;
- no C6A threshold, result, or blocked source is reused as evidence that C7A should pass.

## 3. Falsifiable thesis

At a weekly decision time, BTC and ETH perpetual funding can differ because leveraged demand is not identical across the two markets. A conservatively sized position that is long the lower-funding perpetual and short the higher-funding perpetual, with a rolling beta hedge, may earn the funding differential while reducing broad crypto-market exposure.

This is not risk-free arbitrage. Cross-asset basis risk, beta instability, funding-rank reversals, trading costs, mark-price dislocations, and exchange risk can dominate the carry.

Candidate ID:

`C7ABetaNeutralFundingDispersion`

References motivate the mechanism but do not validate this exact candidate:

- OKX API Guide: <https://www.okx.com/docs-v5/en/>
- Schmeling, Schrimpf, and Todorov, “Crypto Carry,” *Management Science* (2026): <https://doi.org/10.1287/mnsc.2024.05069>
- Angeris, Chitra, Evans, and Lorig, “A Primer on Perpetuals”: <https://ssrn.com/abstract=4215510>

## 4. Prospective anti-overfitting boundary

No timestamp before the preregistered prospective boundary may enter C7A economics.

- prospective data start: `2026-07-27T00:00:00Z`
- warm-up length: exactly `28` days
- first scored decision: `2026-08-24T00:00:00Z`
- scored end exclusive: `2027-02-22T00:00:00Z`
- scored weeks: exactly `26`
- first half: `2026-08-24T00:00:00Z` to `2026-11-23T00:00:00Z`
- second half: `2026-11-23T00:00:00Z` to `2027-02-22T00:00:00Z`

C7B is reserved as a prospective confirmation interval from `2027-02-22T00:00:00Z` to `2027-08-23T00:00:00Z`. It remains unreadable and closed unless C7A passes every unchanged gate and a separate design-only authorization is merged.

Before the C7A scored interval closes, implementation work may use synthetic fixtures and schema examples only. Project code, CI, artifacts, reports, prompts, and reviewers must not retain, summarize, hash, or inspect real C7A economic rows or partial performance.

No historical C0C–C6A or closed C5B timestamp may be used to tune this contract.

## 5. Instruments and permitted public inputs

Fixed instruments:

- `BTC-USDT-SWAP`
- `ETH-USDT-SWAP`

Permitted future public inputs are limited to:

- one-hour perpetual trade candles;
- one-hour perpetual mark-price candles;
- realized historical funding rates with exact settlement timestamps and realized rates;
- current public instrument metadata only for a future execution-readiness gate, never for C7A historical economic selection.

Permitted official surfaces are limited to:

- OKX downloadable historical-data files;
- `GET /api/v5/market/history-candles`;
- `GET /api/v5/market/history-mark-price-candles`;
- `GET /api/v5/public/funding-rate-history`;
- `GET /api/v5/public/instruments` only after an economic PASS and only for a separately authorized current execution-readiness check.

No spot leg, order book, trade tape, open interest, account, balance, position, order, fill, private fee tier, borrowing, lending, staking, external yield, or non-OKX execution venue is part of C7A.

## 6. Data integrity

For every retained series:

- timestamps are UTC, unique, and strictly increasing;
- only completed one-hour candles are permitted;
- the prospective warm-up and scored ranges are gap-free;
- prices are finite and strictly positive;
- funding rates are finite and applied once at their actual settlement timestamps;
- duplicate or contradictory funding settlements fail closed;
- no fixed funding interval is assumed;
- all overshoot rows are removed before research read and recorded;
- all retained source bytes, normalized rows, decisions, and results are hashed into the final evidence manifest.

Missing or ambiguous data causes a pre-economic failure, not interpolation or backward projection.

## 7. Weekly signal

A decision occurs every Monday at `00:00:00Z`. Only completed rows with timestamps strictly earlier than the decision may be used.

For asset `i` at decision `t`:

```text
F_i(t) = sum(realized funding rates in [t - 28 days, t))
```

The higher-funding asset is `H`; the lower-funding asset is `L`. Ties produce no position.

Using one-hour mark-price log returns over the same 28-day lookback, estimate the ordinary least-squares slope:

```text
r_L = alpha + beta * r_H + error
```

No winsorization, outlier deletion, alternate window, robust-regression variant, or post-result estimator selection is allowed.

The beta estimate is valid only when:

- all `672` expected one-hour mark candles exist for both assets;
- return variance for `H` is positive;
- `0.50 <= beta <= 2.00`;
- regression `R^2 >= 0.50`.

## 8. Position construction and eligibility

Maximum gross perpetual notional is `0.50` of current portfolio equity. Each leg is modeled as fully collateralized at one times notional; the remaining equity stays as uncredited USDT cash.

For valid `beta`:

```text
long_weight_L  = 0.50 / (1 + beta)
short_weight_H = 0.50 * beta / (1 + beta)
```

The projected 28-day funding contribution to portfolio equity is:

```text
projected_carry_28d
  = short_weight_H * F_H(t)
  - long_weight_L  * F_L(t)
```

For each of the 28 completed UTC days in the lookback, independently sum actual settlements for BTC and ETH and compute the same weighted daily funding spread.

The candidate is eligible only when all conditions hold:

- `F_H(t) > 0`;
- `projected_carry_28d > 0.00225`;
- at least `19` of the `28` daily weighted funding spreads are strictly positive;
- the beta validity conditions pass;
- all required data-integrity checks pass.

`0.00225` is exactly 1.5 times the expected complete two-leg round-trip cost at the frozen 0.50 gross-notional cap. It is not tunable.

If eligible, hold long `L` and short `H` at the frozen weights. Otherwise hold 100% USDT cash.

## 9. Execution schedule and accounting

Trades occur at the Monday one-hour trade-candle open after the decision using no intrabar price selection.

At every weekly decision:

- close when eligibility fails;
- fully close and reverse when funding rank changes;
- open when a previously inactive candidate becomes eligible;
- update beta-neutral target weights when the one-way gross-notional change is at least 10% of current gross notional;
- skip smaller resizing adjustments.

Funding at a timestamp is applied to the position carried into that timestamp before any modeled trade at the same timestamp.

For positive funding:

- the short leg receives funding;
- the long leg pays funding.

All remaining positions are liquidated at the scored end boundary under identical cost rules. No position or PnL may cross into C7B.

## 10. Frozen costs

One-side modeled execution cost per perpetual notional:

- expected: `0.0015`;
- stress 1.5x: `0.00225`;
- stress 2.0x: `0.0030`.

Every opening, closing, reversal, and eligible resizing charges each affected leg separately. No maker rebate, VIP fee, referral rebate, spread income, cash yield, or unmodeled funding is credited.

## 11. Non-selectable comparators

The evidence package must compute, but may never select:

1. `CashComparator`: 100% USDT, zero return;
2. `AlwaysOnFundingRankComparator`: always long the lower-funding asset and short the higher-funding asset with identical beta, weights, costs, and weekly schedule, but without the eligibility threshold;
3. `EqualNotionalFundingRankComparator`: identical eligibility and schedule but fixed equal long/short notional, used only to measure the incremental effect of beta hedging.

## 12. Frozen eligibility gates

C7A is `SELECTED` only if every gate passes at expected cost unless another cost level is named.

### 12.1 Economics and stability

- first-half net return `> 0`;
- second-half net return `> 0`;
- aggregate net return `> 0`;
- aggregate net return at 1.5x cost `> 0`;
- aggregate net return at 2.0x cost `>= 0`.

### 12.2 Risk and statistical evidence

- annualized weekly Sharpe `>= 1.00`;
- weekly PSR versus zero weekly Sharpe `>= 0.95`;
- maximum drawdown `<= 10%`;
- absolute regression beta of weekly strategy returns to BTC weekly mark returns `<= 0.15`;
- no non-finite equity, negative equity, missing decision, or unaccounted funding settlement.

### 12.3 Carry attribution and costs

- aggregate funding PnL `> 0`;
- gross funding receipts divided by modeled trading costs `>= 2.0`;
- carry-only stress is positive, where positive relative-price PnL is set to zero while negative relative-price PnL and all costs are retained;
- aggregate net return exceeds the `AlwaysOnFundingRankComparator`;
- aggregate Sharpe exceeds that comparator by at least `0.10`.

### 12.4 Activity and concentration

- at least `13` active scored weeks overall;
- at least `5` active weeks in each 13-week half;
- maximum single orientation share of active weeks `<= 85%`;
- annualized one-way gross-notional turnover `<= 8.0x`;
- maximum positive-week PnL share `<= 25%`;
- top-three positive-week PnL share `<= 50%`.

No relatively best but ineligible result may be promoted.

## 13. Multiple testing and review

C7A has one candidate, one lookback, one beta estimator, one eligibility threshold, one sizing rule, and no parameter variants.

Forbidden:

- Hyperopt, grid search, threshold search, alternate lookbacks, alternate regressions, asset expansion, post-result exclusions, LLM signal generation, or rerunning the authoritative screen after any completed economic result;
- reading C7B before a separately authorized confirmation;
- treating a failed gate as a reason to amend and rerun C7A.

The final evidence must include producer results, a physically separate recomputation, exact source identities, complete manifests, cost stresses, attribution, comparators, and a clear `SELECTED` or `REJECTED` decision.

## 14. Next implementation boundary

After this design is independently reviewed and merged, the next admissible work is implementation-only:

- schemas, guards, pure accounting, pure signal logic, independent recomputation, and synthetic deterministic tests;
- no real OKX C7A rows;
- no partial prospective performance;
- no network workflow;
- no economic authorization.

A later exact-SHA authorization may permit one data capture and one authoritative C7A economic run only after the scored interval has closed.

`C7A_DESIGN_ONLY` / `PROSPECTIVE_DATA_BOUNDARY_FROZEN` / `C7A_ECONOMIC_RESULT_NOT_RUN` / `C7B_CLOSED` / `PAPER_CLOSED` / `SHADOW_CLOSED` / `LIVE_FORBIDDEN`
