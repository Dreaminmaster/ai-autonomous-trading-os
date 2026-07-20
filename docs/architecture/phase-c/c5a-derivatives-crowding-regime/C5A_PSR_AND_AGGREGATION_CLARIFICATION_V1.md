# C5A PSR and Aggregation Clarification V1

## 1. Normative status

This document is a normative clarification of `C5A_DERIVATIVES_CROWDING_REGIME_CONTRACT_V1.md`.

It changes no instrument, signal, threshold, cost, window, gate, candidate, ablation, safety state, or authorization. It freezes exact statistical and aggregation semantics before implementation.

## 2. Independent half-window accounting

`D1` and `D2` are simulated independently from `1000 USDT` starting equity.

For each half and cost scenario:

- the first weekly bucket starts from `1000 USDT`;
- each subsequent weekly bucket starts from the immediately preceding Sunday post-close equity;
- the Sunday-close-to-Monday-open gap belongs to the new week;
- the Monday rebalance fee belongs to the new week;
- terminal liquidation at the final Sunday `20:00:00Z` close belongs to the final week;
- exactly `13` full-week post-cost returns must be retained.

The aggregate candidate series is the ordered concatenation of D1's 13 weekly returns followed by D2's 13 weekly returns. It therefore contains exactly `26` observations.

## 3. Aggregate net return

For half-window net returns `R_D1` and `R_D2`:

```text
aggregate_net_return = (1 + R_D1) * (1 + R_D2) - 1
```

This definition applies separately to every cost scenario and to the candidate, ablation, and descriptive comparators.

## 4. Four-hour annualized Sharpe

For each independent half, calculate one four-hour equity return for every retained economic bar after all open transactions, marking, close transactions, and fees applicable to that bar.

Concatenate D1's four-hour returns followed by D2's four-hour returns.

For the concatenated finite vector `r`:

```text
sharpe_4h_annualized
  = mean(r) / sample_std(r, ddof=1) * sqrt(6 * 365)
```

Rules:

- fewer than two observations fail closed;
- non-finite values fail closed;
- zero standard deviation with zero mean produces Sharpe `0`;
- zero standard deviation with nonzero mean fails closed.

The same semantics apply to the candidate and price-only ablation used by the incremental-information gates.

## 5. Weekly raw Sharpe for PSR

For the exact 26-element weekly return vector `w`:

```text
SR_weekly_raw = mean(w) / sample_std(w, ddof=1)
```

This value is not annualized inside the probabilistic Sharpe ratio calculation.

A separately labeled report-only value may be retained:

```text
SR_weekly_annualized = SR_weekly_raw * sqrt(52)
```

The annualized value must not be substituted into the PSR equation.

## 6. Skewness and kurtosis

Use the 26 weekly returns and retain:

```text
skewness = scipy.stats.skew(w, bias=False)
ordinary_kurtosis = scipy.stats.kurtosis(w, fisher=False, bias=False)
```

`ordinary_kurtosis` is non-excess kurtosis.

If the weekly standard deviation and mean are both zero, use:

```text
SR_weekly_raw = 0
skewness = 0
ordinary_kurtosis = 3
PSR = 0
```

A nonzero weekly mean with zero weekly standard deviation fails closed.

## 7. Probabilistic Sharpe ratio

The benchmark raw weekly Sharpe is fixed at:

```text
SR_benchmark = 0
```

With `n = 26`, define:

```text
radicand
  = 1
    - skewness * SR_weekly_raw
    + ((ordinary_kurtosis - 1) / 4) * SR_weekly_raw^2
```

The radicand must be finite and strictly positive.

```text
z
  = (SR_weekly_raw - SR_benchmark)
    * sqrt(n - 1)
    / sqrt(radicand)

PSR = standard_normal_cdf(z)
```

The frozen gate remains:

```text
PSR >= 0.90
```

Because C5A has exactly one selectable candidate, this is a probabilistic Sharpe ratio, not a deflated Sharpe ratio and not a correction for the broader C0C–C5A sequential research program.

## 8. Concentration denominators

For half-window, asset, single-week, and top-three-week concentration metrics:

- include only strictly positive PnL contributions in the denominator;
- if total positive PnL is zero, the metric is undefined and its gate fails;
- the single-week share is the largest positive weekly PnL divided by total positive weekly PnL;
- the top-three-week share is the sum of the three largest positive weekly PnLs divided by total positive weekly PnL;
- D1 and D2 half-window PnL are calculated from their independent `1000 USDT` starts;
- asset PnL must reconcile additively to D1 plus D2 total net PnL within `1e-9`.

## 9. Incremental-information comparison

The three incremental gates compare the candidate and ablation at the `1.0x` expected-cost scenario using the exact aggregate metrics defined above:

- `candidate_sharpe_4h_annualized > ablation_sharpe_4h_annualized`;
- `candidate_maximum_half_window_drawdown <= ablation_maximum_half_window_drawdown`;
- `candidate_annualized_one_way_turnover <= ablation_annualized_one_way_turnover`.

No rounding is permitted before gate comparison. Display rounding is report-only.

## 10. Evidence retention

The authoritative artifact must retain for candidate and ablation:

- ordered D1 and D2 four-hour return vectors;
- ordered 26-week return vector;
- mean, sample standard deviation, raw weekly Sharpe, annualized report-only weekly Sharpe;
- skewness, ordinary kurtosis, radicand, z-score, and PSR;
- D1 and D2 net PnL and net return;
- aggregate return calculation;
- all concentration numerators and denominators;
- exact unrounded incremental differences.

The independent reference implementation must recompute these values without importing the production C5A engine.

## 11. Safety state

`C5A_DESIGN_ONLY`

`C5B_CLOSED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
