# C6A Accounting, Margin, and Statistics Addendum V1

## 1. Normative role

This addendum is normative and resolves the exact accounting semantics for `C6AMarketNeutralFundingCarry`. It changes no stage state and authorizes no implementation or data access.

If the main contract and this addendum appear inconsistent, the more conservative fail-closed interpretation applies and the design must be amended before implementation.

## 2. Numeric and time conventions

- All monetary, price, quantity, contract, fee, funding, PnL, and ratio calculations use decimal arithmetic.
- Binary floating-point values may be emitted only as derived display fields, never as decision authority.
- All times are UTC.
- Intervals are start-inclusive and end-exclusive.
- The scored interval contains five independent 26-week windows. Each window begins with exactly `1000 USDT` cash and no position.
- No position, PnL, funding, or state carries across windows.

## 3. Candle and funding boundary semantics

For a one-hour candle labeled by open time `h`:

- its open is the modeled transaction price at `h`;
- its close becomes available only at `h + 1 hour`;
- a decision at Monday `00:00:00Z` may use candle closes whose labeled open time is at most Sunday `22:00:00Z`;
- the Sunday `23:00:00Z` candle has not completed at the decision timestamp and is unavailable.

Funding records satisfy:

```text
fundingTime < decision_time
```

for signal construction.

For funding PnL at settlement `s`, the funding notional uses the perpetual mark close from the completed one-hour candle immediately preceding `s`. Absence of that exact predecessor candle fails closed.

When settlement and transaction share timestamp `s`:

1. mark the carried position to the pre-transaction perpetual trade open at `s`;
2. apply funding to the carried position using the preceding completed mark close;
3. record pre-trade equity;
4. execute spot and perpetual quantity changes at their respective trade opens;
5. charge both leg costs;
6. record post-trade equity.

A position opened at `s` receives no funding at `s`. A position closed at `s` first receives or pays funding at `s`.

## 4. Public instrument conversion

Only linear USDT-margined perpetuals whose public metadata gives an unambiguous base-currency contract value are permitted.

For asset `i`:

```text
contract_base_quantum_i = ctVal_i * lotSz_i
perpetual_base_quantity_i = contract_count_i * ctVal_i
```

Requirements:

- `ctValCcy` must equal the spot base currency;
- `ctVal`, `lotSz`, `minSz`, and spot lot/minimum sizes must be positive and effective for the modeled timestamp;
- contract count must be a non-negative permitted multiple of `lotSz` and at least `minSz` when nonzero;
- spot quantity must satisfy the public spot lot and minimum-size rules.

For desired base quantity `q*`, the deterministic joint-rounding solver enumerates feasible perpetual contract counts not exceeding the desired notional by more than one contract quantum, pairs each with the closest non-exceeding feasible spot quantity, and selects by this ordering:

1. minimum relative hedge error;
2. maximum paired notional not above the post-cost target;
3. minimum contract count;
4. lexical instrument ID.

Relative hedge error is:

```text
hedge_error
  = abs(spot_base_quantity - perpetual_base_quantity)
    / max(spot_base_quantity, perpetual_base_quantity)
```

A nonzero sleeve is valid only when:

```text
hedge_error <= 0.001
```

The exact spot quantity and perpetual base-equivalent quantity are retained. Net delta is never silently set to zero.

## 5. Post-cost target solver

At a weekly decision, the target allocation is based on current pre-trade total equity. Trading costs reduce the capital available to establish the target.

The implementation must solve a single deterministic scale `lambda` in `[0, 1]` applied to all desired new sleeve notionals so that, after:

- spot cash flows;
- perpetual collateral allocation;
- spot transaction costs;
- perpetual transaction costs;
- deterministic quantity rounding;

post-trade free cash is non-negative and the unallocated residual is minimized.

The solver must use monotone bisection followed by deterministic downward quantum search. Required tolerance:

```text
0 <= post_trade_free_cash <= 0.01 USDT
```

unless the residual is caused solely by the minimum public spot or contract quantum, in which case the exact quantum residual is retained and explained. Negative cash, implicit borrowing, hidden collateral creation, or fee payment outside modeled equity fails closed.

## 6. Sleeve ledger

Each active asset sleeve retains separate fields:

- free cash allocated to the sleeve;
- spot base quantity and spot cost basis;
- perpetual contract count and base-equivalent quantity;
- dedicated perpetual collateral;
- cumulative spot mark PnL;
- cumulative perpetual mark PnL;
- cumulative funding PnL;
- cumulative spot fees;
- cumulative perpetual fees;
- current collateral equity;
- current hedge error;
- current mark/spot basis;
- current risk-exit state.

No collateral or PnL may be transferred between BTC and ETH sleeves between weekly decisions. No sleeve may draw on another sleeve's spot value or collateral to avoid a breach.

## 7. Price and funding PnL

### 7.1 Spot leg

For unchanged spot quantity `q_s` between consecutive marks:

```text
spot_price_pnl = q_s * (spot_price_new - spot_price_old)
```

Spot is valued at the completed spot candle close for hourly equity records and at trade open for transactions.

### 7.2 Short perpetual leg

For unchanged perpetual base-equivalent short quantity `q_p`:

```text
perpetual_price_pnl = q_p * (perpetual_mark_old - perpetual_mark_new)
```

A mark increase therefore produces negative short PnL.

### 7.3 Funding leg

At actual settlement `j`:

```text
funding_notional_j
  = perpetual_base_quantity_before_settlement
    * preceding_completed_mark_close_j

funding_pnl_j
  = funding_notional_j * realizedRate_j
```

This sign convention is for a short perpetual position: positive realized rate is a receipt; negative realized rate is a payment.

Every realized rate is applied once and only once. Funding PnL is zero when the sleeve had no short position immediately before settlement.

### 7.4 Transaction costs

For each changed leg:

```text
spot_cost = abs(delta_spot_quantity) * spot_trade_price * cost_rate
swap_cost = abs(delta_perpetual_base_quantity) * swap_trade_price * cost_rate
```

Costs are charged even when a transaction is a forced close or terminal liquidation.

### 7.5 Net sleeve PnL

```text
net_sleeve_pnl
  = spot_price_pnl
  + perpetual_price_pnl
  + funding_pnl
  - spot_cost
  - swap_cost
```

Every weekly, window, asset, and aggregate net PnL must reconcile exactly to these components.

## 8. Collateral equity and conservative risk buffer

Dedicated perpetual collateral equity is:

```text
collateral_equity
  = initial_or_rebalanced_dedicated_collateral
  + cumulative_perpetual_price_pnl_since_rebalance
  + cumulative_funding_pnl_since_rebalance
  - cumulative_perpetual_cost_since_rebalance
```

Current short notional is:

```text
short_notional = perpetual_base_quantity * current_mark_price
```

For an active sleeve:

```text
collateral_buffer_ratio = collateral_equity / short_notional
```

A zero or negative short notional while the sleeve is marked active fails closed.

The main-contract risk exit is triggered by the first completed hourly observation with:

```text
collateral_buffer_ratio < 1.25
```

This is a conservative research buffer, not a claim about OKX liquidation tiers. The model does not use private account mode, maintenance-margin tier, cross margin, portfolio margin, or emergency transfers.

The forced close occurs at the next one-hour spot and perpetual trade opens. The breach remains an eligibility failure even if the realized forced-close PnL is positive.

## 9. Weekly accounting buckets

For weekly boundary `t` and next boundary `u = t + 7 days`:

- `start_reference_equity` is total equity immediately before the funding settlement at `t` and before any trade at `t`;
- funding at `t`, boundary mark movement, transaction costs, and post-trade quantities belong to the new week;
- `end_reference_equity` is total equity immediately before the funding settlement and transactions at `u`;
- funding at `u` belongs to the next week.

```text
weekly_pnl = end_reference_equity - start_reference_equity
weekly_return = weekly_pnl / start_reference_equity
```

Each bucket retains:

- start time/equity;
- same-time funding by asset;
- pre-trade equity;
- every leg delta and fee;
- post-trade equity;
- hourly minimum equity;
- funding, spot, perpetual, and cost components;
- end time/equity;
- active sleeve flags;
- risk-exit flags;
- exact reconciliation residual.

Absolute reconciliation residual must be `<= 1e-8 USDT`.

## 10. Independent windows and aggregate return

Each 26-week window begins from `1000 USDT`, evaluates the same frozen candidate independently, and terminally liquidates before its exclusive end.

For window `w`:

```text
window_return_w = final_equity_w / 1000 - 1
```

Program aggregate return uses equal initial capital across the five windows:

```text
aggregate_return
  = sum(final_equity_w for w in W1..W5) / 5000 - 1
```

The 130 weekly returns are concatenated only for weekly distribution statistics. Equity is not compounded from one independent window into the next.

## 11. Turnover and exposure

For a transaction event:

```text
paired_one_way_notional
  = 0.5 * (
      abs(delta_spot_quantity) * spot_trade_price
      + abs(delta_perpetual_base_quantity) * swap_trade_price
    )

normalized_one_way_turnover
  = paired_one_way_notional / pre_trade_total_equity
```

For 130 scored weeks:

```text
annualized_one_way_turnover
  = sum(normalized_one_way_turnover) / (130 / 52)
```

Terminal liquidation and forced closes are included.

Hourly gross exposure is:

```text
gross_exposure
  = spot_notional + short_perpetual_notional
exposure_ratio
  = gross_exposure / total_equity
```

Net base exposure and hedge error are retained separately. Gross exposure must not be mislabeled as net exposure.

## 12. Drawdown

Within each independent window, construct hourly post-event total equity after applying all marks, funding, transactions, and costs available at that timestamp.

```text
drawdown_t = 1 - equity_t / running_peak_equity_t
window_max_drawdown = max(drawdown_t)
maximum_drawdown = max(window_max_drawdown across W1..W5)
```

No cross-window artificial drawdown or cross-window compounding is permitted.

## 13. Sharpe and PSR

Use all `130` raw weekly returns, including zero-activity weeks.

```text
weekly_sharpe = mean(weekly_returns) / sample_std(weekly_returns)
annualized_weekly_sharpe = weekly_sharpe * sqrt(52)
```

Zero or non-finite sample standard deviation fails eligibility.

Use unbiased sample skewness and unbiased ordinary kurtosis, not excess kurtosis. For benchmark weekly Sharpe `SR* = 0`:

```text
PSR
  = Phi(
      (weekly_sharpe - SR*) * sqrt(n - 1)
      / sqrt(
          1
          - skewness * weekly_sharpe
          + ((ordinary_kurtosis - 1) / 4) * weekly_sharpe^2
        )
    )
```

Required retained fields:

- `n = 130`;
- mean and sample standard deviation;
- raw weekly Sharpe;
- annualized weekly Sharpe;
- unbiased skewness;
- unbiased ordinary kurtosis;
- PSR numerator, denominator, z-score, and probability;
- `weekly_statistic = PSR_NOT_DSR`;
- `program_level_sequential_history_corrected = false`.

## 14. Funding-cost coverage

```text
gross_funding_receipts
  = sum(max(funding_pnl_j, 0))

gross_funding_payments
  = sum(max(-funding_pnl_j, 0))

total_trading_costs
  = sum(spot_cost + swap_cost)

funding_cost_coverage
  = gross_funding_receipts / total_trading_costs
```

A zero cost denominator fails eligibility. The ratio does not net negative funding payments out of the numerator; negative funding remains in net PnL.

## 15. Attribution and concentration

Asset contribution is the exact sum of that asset sleeve's spot PnL, perpetual PnL, funding PnL, and costs.

For a positive-contribution group `G`:

```text
positive_denominator = sum(max(pnl_g, 0) for g in G)
share_g = max(pnl_g, 0) / positive_denominator
```

This definition is applied separately to assets, windows, and weeks. A zero positive denominator fails every positive-concentration gate.

Retain exact numerators, denominators, shares, sorted positive-week list, largest positive week, and top-three positive weeks.

## 16. Always-on comparator equivalence

`AlwaysOnDeltaNeutralComparator` must use identical:

- data and boundaries;
- sleeve capital rule;
- 1/3 spot and 2/3 collateral split;
- contract conversion and hedge tolerance;
- post-cost solver;
- transaction prices and cost rates;
- funding application;
- collateral-buffer and basis-risk exits;
- weekly resizing band;
- terminal liquidation;
- accounting, turnover, drawdown, attribution, and statistics.

Its only permitted difference is that both BTC and ETH target active sleeves at every Monday decision, without the C6A funding-eligibility signal.

Candidate-minus-comparator return, Sharpe, drawdown, and turnover differences must be retained at full internal precision. Favorable direction must be explicit; rounding cannot decide a gate.

## 17. Independent recomputation boundary

The independent finalizer must reconstruct all quantities, funding applications, PnL components, weekly buckets, statistics, comparators, gates, and decision from primitive public inputs and frozen configuration.

It must not import:

- the production candidate engine;
- production gate/ranking functions;
- production aggregate or statistic outputs;
- precomputed production decisions as authority.

Agreement must be exact for discrete states and within prospectively frozen decimal tolerances for numeric outputs. Any mismatch is an evidence failure.

## 18. Final state

`C6A_DESIGN_ONLY`

`C6A_ECONOMIC_RESULT_NOT_RUN`

`C6B_CLOSED`

`C5B_CLOSED_AND_UNTOUCHED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
