# C5A Public-Derivatives Crowding Regime Allocation — Contract V1

## 1. Status and purpose

This document preregisters one structurally new Phase C research thesis after the frozen C4A rejection.

- Stage: `C5A`
- Change type: `DESIGN_ONLY`
- Economic result: `NOT_RUN`
- Candidate count: `1`
- C5B confirmation: `CLOSED`
- Holdout: `CLOSED`
- Paper execution: `CLOSED`
- Shadow execution: `CLOSED`
- Live execution: `FORBIDDEN`

This contract does not authorize implementation, market-data download, an economic run, paper trading, shadow trading, private OKX APIs, derivative orders, leverage, shorting, or live execution.

## 2. Why C5A is structurally distinct

The prior Phase C research families are frozen and must not be retuned:

- C0C: cost-aware EMA walk-forward;
- C1A: price-only breakout, pullback, and dual-momentum families;
- C2A: low-turnover BTC/ETH/SOL spot allocation;
- C3A: ETH/SOL residual mean reversion relative to BTC;
- C4A: weekly cross-sectional price-momentum ranking.

C5A does not alter any prior threshold or rerun any prior candidate. It tests a different proposition:

> Public perpetual-swap crowding information may improve the risk-adjusted timing of a spot-only BTC/ETH/SOL allocation relative to the identical price-only construction.

The candidate uses perpetual mark-price basis and swap-versus-spot quote-volume participation only as public signals. All modeled holdings remain unlevered spot assets plus cash.

## 3. Program-level anti-overfitting reset

The 2024 development screen has already informed several sequential research stages. C5A therefore must not use `2024-01-01` through `2024-10-01` for economic selection.

C5A freezes a new temporal split before any C5A data are downloaded or inspected:

### 3.1 Warm-up and calibration

- Download start: `2024-09-02T00:00:00Z`
- Calibration decision interval: `2024-10-07T00:00:00Z` through `2025-06-30T00:00:00Z`, inclusive
- Expected calibration Mondays: `39`

Calibration is used only to build per-asset empirical distributions for the two crowding inputs. It is not a C5A performance window and cannot produce an economic pass.

### 3.2 C5A development screen

- Start: `2025-07-07T00:00:00Z`
- End exclusive: `2026-01-05T00:00:00Z`
- Full weeks: `26`
- Stability halves:
  - `D1`: `2025-07-07T00:00:00Z` to `2025-10-06T00:00:00Z`, end exclusive, `13` weeks;
  - `D2`: `2025-10-06T00:00:00Z` to `2026-01-05T00:00:00Z`, end exclusive, `13` weeks.

### 3.3 Reserved C5B confirmation

- Start: `2026-01-05T00:00:00Z`
- End exclusive: `2026-07-06T00:00:00Z`
- Full weeks: `26`

C5A tooling must fail closed if any timestamp at or after `2026-01-05T00:00:00Z` is retained, read, summarized, hashed into economic evidence, or used for calibration, testing, diagnosis, or implementation debugging.

C5B may open only if the single C5A candidate passes every unchanged gate and a separate design-only authorization is merged later.

## 4. Instruments and data

### 4.1 Spot instruments

- `BTC-USDT`
- `ETH-USDT`
- `SOL-USDT`

### 4.2 Public perpetual instruments used only as signals

- `BTC-USDT-SWAP`
- `ETH-USDT-SWAP`
- `SOL-USDT-SWAP`

### 4.3 Required public OKX data

Timeframe: `4H` UTC.

For each spot instrument:

- trade candle `open`, `high`, `low`, `close`;
- quote-currency volume `volCcyQuote`.

For each perpetual instrument:

- trade-candle quote-currency volume `volCcyQuote`;
- mark-price candle `close`.

Permitted public sources:

- `GET /api/v5/market/history-candles`;
- `GET /api/v5/market/history-mark-price-candles`.

No authenticated endpoint is permitted. No order book, funding history, liquidation feed, account data, positions, balances, orders, or fills are permitted in C5A.

### 4.4 Data integrity

For all six instruments and all required series:

- exact four-hour alignment is required;
- only completed candles are permitted;
- timestamps must be unique and strictly increasing;
- OHLC values and quote volumes must be finite and non-negative;
- prices must be strictly positive;
- missing bars, duplicate bars, unordered bars, field drift, or post-boundary rows fail the run;
- API overshoot at or after the exclusive C5A boundary must be removed before any research read and recorded in a boundary report;
- every retained input file must be hashed and included in the final manifest.

## 5. Decision schedule and no-lookahead rule

A decision occurs every Monday at `00:00:00Z`.

The decision may use only completed four-hour bars through the immediately preceding Sunday `20:00:00Z` bar.

Execution is modeled at the Monday `00:00:00Z` spot open. The Sunday-close-to-Monday-open gap belongs to the new week. The Monday rebalance fee also belongs to the new week.

The final modeled holdings are liquidated at the final retained Sunday `20:00:00Z` spot close before each window boundary.

## 6. Frozen signal definitions

For asset `i` at a Monday decision time `t`, using data ending at Sunday `20:00:00Z`:

### 6.1 Spot trend

```text
trend_28d_i(t) = spot_close_i(t-1) / spot_close_i(t-169) - 1
```

The index difference is `168` four-hour intervals, equal to `28` days.

### 6.2 Realized volatility

Use the previous `168` completed four-hour log returns of the spot close.

```text
rv_28d_i(t) = sample_std(log_return_4h) * sqrt(6 * 365)
```

A zero, negative, non-finite, or insufficient volatility estimate fails closed.

### 6.3 Perpetual-spot basis

For each of the previous `42` completed four-hour bars:

```text
basis_i = mark_close_i / spot_close_i - 1
```

The decision input is:

```text
basis_7d_i(t) = median(previous 42 basis_i values)
```

### 6.4 Derivatives participation

```text
participation_7d_i(t)
  = sum(previous 42 swap volCcyQuote values)
    / sum(previous 42 spot volCcyQuote values)
```

A zero spot-volume denominator, negative volume, non-finite ratio, or missing volume fails closed.

### 6.5 Formation-only empirical percentiles

For each asset and each crowding field separately, retain the `39` Monday calibration observations.

For a screen value `x`, define the right-continuous empirical percentile:

```text
percentile(x) = count(calibration_value <= x) / 39
```

No screen-period observation may alter the calibration distribution.

### 6.6 Crowding score

```text
crowding_score_i(t)
  = max(
      percentile_basis_i(t),
      percentile_participation_i(t)
    )
```

An asset is `not_crowded` only when:

```text
crowding_score_i(t) < 0.80
```

The threshold is fixed before implementation and is not tunable.

## 7. Single selectable candidate

Candidate ID:

```text
C5ADerivativesCrowdingFilteredRiskBalance
```

### 7.1 Asset eligibility

An asset is eligible only when:

```text
trend_28d_i(t) > 0
AND
crowding_score_i(t) < 0.80
```

### 7.2 Market risk-on rule

The portfolio is risk-on only when:

- `BTC-USDT` has positive `trend_28d`;
- at least two of BTC, ETH, and SOL are eligible.

Otherwise the target is `100%` cash.

### 7.3 Raw target weights

For eligible assets during risk-on:

```text
raw_i = 1 / rv_28d_i
normalized_i = raw_i / sum(raw)
```

Total invested weight is exactly `0.80`. Cash target weight is exactly `0.20`.

Each asset has a hard target-weight cap of `0.40`. If a cap binds, excess weight is redistributed among uncapped eligible assets in ascending instrument-ID order until either the invested total reaches `0.80` or no eligible uncapped asset remains. Failure to allocate exactly `0.80` within `1e-12` fails closed.

### 7.4 No-trade band

At the Monday open, compute current pre-trade spot weights using current quantities and Monday open prices.

```text
one_way_distance = 0.5 * sum(abs(target_weight_i - current_weight_i))
```

Cash is included in the weight vector.

If `one_way_distance < 0.10`, no rebalance occurs and current quantities remain unchanged. Otherwise rebalance to the frozen target using the post-cost solver.

The no-trade threshold is fixed and is not tunable.

## 8. Non-selectable price-only ablation

Ablation ID:

```text
C5APriceOnlyRiskBalanceAblation
```

The ablation is identical to the candidate in every respect except that asset eligibility ignores basis and participation:

```text
trend_28d_i(t) > 0
```

It remains subject to the BTC-positive and two-asset breadth rules, inverse-volatility sizing, 40% cap, 80% total investment, cash allocation, no-trade band, costs, accounting, windows, and terminal liquidation.

The ablation is not selectable and cannot open C5B. Its only purpose is to test whether the derivative crowding inputs add incremental risk-adjusted information beyond the identical price-only construction.

## 9. Descriptive comparators

- `cash`;
- `btc_buy_hold`;
- `btc_eth_sol_equal_weight_buy_hold`.

Comparators use the same window boundaries and cost scenarios. They are descriptive and are not selectable.

## 10. Costs and accounting

Starting equity for each independent half-window: `1000 USDT`.

One-side proportional costs:

- `1.0x`: `0.0015`;
- `1.5x`: `0.00225`;
- `2.0x`: `0.0030`.

Every rebalance must solve post-cost equity before setting quantities:

```text
E_after + fee_rate * sum(abs(target_weight_i * E_after - current_value_i))
  = E_before
```

Requirements:

- no leverage;
- no negative cash;
- no negative quantity;
- no borrowing;
- no shorting;
- no derivative position;
- cash plus marked spot values must reconcile to post-cost equity within `1e-9`;
- fees, trade deltas, target values, quantities, and residuals must be retained per rebalance;
- bar exposure is determined from quantities immediately after candle-open transactions;
- a position held through the final bar counts as exposed even if liquidated at that bar close.

## 11. Metrics

For candidate, ablation, and comparators, retain each half-window and each cost scenario.

Candidate aggregates at expected cost must include:

- D1 and D2 net returns;
- compounded aggregate net return;
- four-hour annualized Sharpe;
- 26 full-week cost-inclusive returns;
- skewness and ordinary kurtosis of weekly returns;
- probabilistic Sharpe ratio against weekly Sharpe `0`;
- maximum half-window drawdown;
- annualized one-way turnover;
- exposure ratio;
- active rebalance count and minimum per-half active count;
- additive asset PnL contributions;
- positive-asset count;
- half-window, asset, single-week, and top-three-week positive-PnL concentration;
- exact incremental differences versus the price-only ablation.

Because there is exactly one selectable C5A candidate, within-stage DSR is not used. The evidence must explicitly state that this does not erase the program-level sequential research history from C0C through C5A.

## 12. Frozen eligibility gates

The candidate is eligible only if every condition below passes without tolerance relaxation.

### 12.1 Absolute economic gates

- D1 net return `> 0`;
- D2 net return `> 0`;
- aggregate expected-cost net return `> 0`;
- aggregate `1.5x`-cost net return `>= 0`;
- aggregate four-hour annualized Sharpe `>= 0.75`;
- weekly probabilistic Sharpe ratio versus zero `>= 0.90`;
- maximum half-window drawdown `<= 0.15`;
- annualized one-way turnover `<= 8.0`;
- exposure ratio `<= 0.80`;
- active rebalance count `>= 4`;
- minimum active rebalances per half `>= 2`;
- positive asset count `>= 2`;
- maximum positive half-window PnL share `<= 0.70`;
- maximum positive asset PnL share `<= 0.60`;
- maximum single-week positive PnL share `<= 0.25`;
- maximum top-three-week positive PnL share `<= 0.55`.

### 12.2 Incremental-information gates versus the ablation

At expected cost:

- candidate aggregate Sharpe must be strictly greater than ablation aggregate Sharpe;
- candidate maximum half-window drawdown must be less than or equal to ablation drawdown;
- candidate annualized one-way turnover must be less than or equal to ablation turnover.

If the ablation has undefined Sharpe because of invalid or degenerate returns, the run fails closed rather than granting an automatic incremental pass.

## 13. Decision rule

There is no candidate ranking and no parameter selection.

```text
if every frozen gate passes:
    economic_result = SELECTED
    selected_policy = C5ADerivativesCrowdingFilteredRiskBalance
else:
    economic_result = REJECTED
    selected_policy = null
```

The relatively better of candidate and ablation must not be promoted if any gate fails.

## 14. Evidence requirements

An authoritative C5A artifact must retain at minimum:

- exact source SHA and merge-ref SHA;
- frozen contract hash;
- boundary and continuous-coverage reports;
- all retained spot, swap-volume, and mark-price inputs with hashes;
- 39 calibration observations per asset per crowding field;
- immutable calibration-distribution hashes;
- every candidate and ablation Monday decision;
- every per-asset signal row;
- complete post-cost rebalance ledger;
- D1, D2, aggregate, stress-cost, comparator, ablation, and incremental metrics;
- probabilistic Sharpe inputs and output;
- exact gate results and rejection reasons;
- source inventory and source snapshots;
- complete self-verifying manifest;
- independent plain-array recomputation that does not import the production C5A engine;
- `C5B_CLOSED`, `HOLDOUT_CLOSED`, `PAPER_CLOSED`, `SHADOW_CLOSED`, and `LIVE_FORBIDDEN` in every final decision surface.

## 15. Implementation and workflow policy

Implementation requires a separate PR after this design is merged.

Routine implementation validation must use the repository's existing CI and Freqtrade Validation workflows. A temporary dedicated C5A workflow may be added only after:

1. exact-head normal validation passes;
2. an independent exact-SHA static review passes;
3. the implementation candidate is frozen;
4. the workflow checks out the frozen source and exact merge-ref;
5. C5B data remain inaccessible.

The authoritative workflow may run exactly once unless an infrastructure or evidence failure occurs before any C5A economic output is observed. After the result is frozen, the temporary workflow must be deleted before merge.

## 16. Failure and stopping rules

The following are valid `REJECTED` outcomes and must not trigger in-place retuning:

- one half-window is non-positive;
- costs erase the result;
- risk-adjusted evidence is insufficient;
- drawdown, turnover, exposure, or concentration exceeds a gate;
- derivative crowding information does not beat the price-only ablation on all three incremental gates.

After a valid C5A rejection:

- do not alter the 80th-percentile crowding threshold;
- do not alter the 28-day or 7-day windows;
- do not alter the 80% investment target, 40% cap, or 10% no-trade threshold;
- do not add variants to the same stage;
- do not access C5B;
- do not claim that the strongest-looking failed result is paper eligible.

## 17. Research basis and claim boundary

C5A is motivated by published evidence that cryptocurrency futures basis contains information distinct from simple momentum, while deliberately testing that proposition out of sample rather than assuming it is true.

Primary references:

- Chi, Hao, Hu, and Ran, “An empirical investigation on risk factors in cryptocurrency futures,” *Journal of Futures Markets* 43(8), 2023, DOI `10.1002/fut.22425`;
- OKX API V5 public market-data documentation for historical trade candles, mark-price candles, and quote-currency volume semantics.

A C5A pass would apply only to the exact three assets, exact public OKX series, exact calibration distribution, exact fresh screen, exact costs, and exact spot-only construction. It would not establish general performance across all cryptocurrencies, exchanges, derivative venues, later periods, private execution, leverage, shorts, or live trading.

## 18. Final design state

`C5A_DESIGN_ONLY`

`C5A_ECONOMIC_RESULT_NOT_RUN`

`C5B_CLOSED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
