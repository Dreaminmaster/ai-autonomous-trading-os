# C5A Sizing, Turnover, and Accounting Clarification V1

## 1. Normative status

This document is a normative clarification of the C5A contract.

It changes no candidate, signal, threshold, window, cost, gate, data source, or safety state. It removes ambiguity from capped inverse-volatility sizing, the no-trade decision, turnover, contribution accounting, and terminal liquidation.

## 2. Deterministic capped inverse-volatility allocation

Let `E` be the lexicographically sorted set of eligible spot instruments at a risk-on decision.

For each `i` in `E`:

```text
score_i = 1 / rv_28d_i
```

The target invested weight is `0.80`, the per-asset cap is `0.40`, and target cash is `0.20`.

Use this deterministic water-filling algorithm:

1. Set `remaining_weight = 0.80`.
2. Set `active = E` and every fixed target weight to zero.
3. For every asset in `active`, calculate:

```text
provisional_i
  = remaining_weight * score_i / sum(score_j for j in active)
```

4. Find every active asset with `provisional_i > 0.40`.
5. If none exist, assign every provisional weight and stop.
6. Otherwise, in lexicographic instrument-ID order, fix each over-cap asset at `0.40`, remove it from `active`, subtract `0.40` from `remaining_weight`, and repeat from step 3.

Requirements:

- at least two assets must be eligible before this algorithm is called;
- every target weight must be finite and within `[0, 0.40]`;
- the asset targets must sum to `0.80` within `1e-12`;
- target cash must equal `0.20` within `1e-12`;
- any violation fails closed.

## 3. Current weights at the decision open

Before any Monday transaction, mark every spot quantity at the Monday open.

```text
E_before = cash_before + sum(quantity_i * monday_open_i)
current_asset_weight_i = quantity_i * monday_open_i / E_before
current_cash_weight = cash_before / E_before
```

`E_before` must be finite and strictly positive. Current asset and cash weights must reconcile to one within `1e-12`.

## 4. Frozen no-trade decision

Construct vectors over BTC, ETH, SOL, and cash. Missing asset targets are zero.

```text
one_way_distance
  = 0.5 * (
      sum(abs(target_asset_weight_i - current_asset_weight_i))
      + abs(target_cash_weight - current_cash_weight)
    )
```

Rules:

- if `one_way_distance < 0.10`, execute no transaction;
- if `one_way_distance >= 0.10`, execute the full frozen target;
- equality therefore triggers a rebalance;
- no partial band-edge adjustment is permitted;
- no-trade decisions retain quantities and cash unchanged and record turnover `0`;
- a scheduled no-trade decision is not an active rebalance.

## 5. Post-cost target solver

When a rebalance is required, target asset values are defined relative to post-cost equity `E_after`.

```text
E_after
  + fee_rate * sum(
      abs(target_weight_i * E_after - current_value_i)
    )
  = E_before
```

The sum is over BTC, ETH, and SOL. Cash is not charged a transaction fee.

After solving:

```text
target_value_i = target_weight_i * E_after
trade_delta_i = target_value_i - current_value_i
fee_i = fee_rate * abs(trade_delta_i)
total_fee = sum(fee_i)
cash_after = E_after - sum(target_value_i)
quantity_after_i = target_value_i / monday_open_i
```

Requirements:

- root bracketing and convergence must be deterministic;
- `E_before - total_fee - E_after` must reconcile within `1e-9`;
- `cash_after + sum(target_value_i) - E_after` must reconcile within `1e-9`;
- cash and quantities must be non-negative;
- a cash target uses the same solver with all asset target weights zero;
- every solver input, iteration count, residual, price, delta, fee, target value, and before/after quantity must be retained.

## 6. One-way turnover metric

For every executed rebalance, retain the exact pre-trade `one_way_distance` from Section 4 as the rebalance's one-way turnover contribution.

For no-trade decisions, the contribution is zero.

For terminal liquidation, calculate current pre-liquidation weights at the final close and use a target of `100%` cash:

```text
terminal_one_way_turnover
  = 0.5 * (
      sum(abs(0 - current_asset_weight_i))
      + abs(1 - current_cash_weight)
    )
```

Aggregate annualized one-way turnover is:

```text
annualized_one_way_turnover
  = sum(all D1 and D2 turnover contributions)
    / total_years
```

where:

```text
total_years
  = (
      duration_seconds(D1)
      + duration_seconds(D2)
    ) / (365 * 24 * 60 * 60)
```

No display rounding is permitted before the frozen `<= 8.0` gate or the candidate-versus-ablation turnover comparison.

## 7. Exposure

For each four-hour economic bar:

- apply any Monday-open transaction first;
- define `bar_exposed = true` when any post-open spot quantity is strictly positive;
- a position held through the final bar remains exposed even when liquidated at that bar's close;
- an open-time liquidation makes that bar unexposed.

```text
exposure_ratio = exposed_bar_count / economic_bar_count
```

D1 and D2 exposed and economic bar counts are added before calculating the aggregate ratio.

## 8. Asset contribution accounting

For each asset, additive net PnL contribution includes:

- Sunday-close-to-Monday-open gap PnL on quantities held across the boundary;
- Monday-open-to-bar-close PnL;
- every subsequent close-to-open and open-to-close marked PnL;
- negative entry, rebalance, exit, and terminal fees assigned to the traded asset.

Cash earns zero interest and has no independent PnL contribution.

For each half:

```text
sum(asset_contribution_i)
  = final_equity - 1000
```

For the aggregate:

```text
sum(D1 asset contributions + D2 asset contributions)
  = (D1 final equity - 1000)
    + (D2 final equity - 1000)
```

Both identities must hold within `1e-9`.

## 9. Weekly bucket reconciliation

Each half must retain exactly 13 weekly buckets.

For every week retain:

- prior Sunday post-close starting equity, or `1000` for the first week;
- Monday pre-trade open equity;
- boundary-gap PnL;
- Monday fee;
- Monday post-trade equity;
- final Sunday post-close equity after any terminal liquidation;
- net weekly PnL;
- net weekly return.

For each half:

```text
sum(13 weekly net PnL values)
  = final_equity - 1000
```

within `1e-9`.

## 10. Terminal liquidation

At each half-window's final Sunday `20:00:00Z` close:

- mark all spot quantities at that close;
- solve a post-cost target of zero asset weights;
- apply exit fees;
- set every quantity to zero;
- retain terminal turnover and complete ledger fields;
- finish with cash equal to final equity within `1e-9`.

A half that does not end entirely in cash fails closed.

## 11. Comparator accounting

`btc_buy_hold` and `btc_eth_sol_equal_weight_buy_hold`:

- enter at the first Monday open of each independent half;
- use the same expected/stress cost rates and post-cost solver;
- hold without intermediate rebalance;
- liquidate at the final Sunday close;
- use the same drawdown, return, fee, and weekly-bucket semantics.

Cash remains exactly `1000 USDT` with zero return, zero drawdown, zero turnover, and zero exposure.

## 12. Candidate and ablation identity

The candidate and price-only ablation must share the same:

- data and timestamps;
- trend and volatility values;
- sizing algorithm;
- cap and total investment;
- no-trade computation;
- costs and solver;
- accounting and terminal rules;
- metrics and evidence code paths.

The only allowed difference is whether the two frozen derivative-crowding conditions participate in asset eligibility.

Any additional behavioral difference invalidates the incremental-information comparison.

## 13. Safety state

`C5A_DESIGN_ONLY`

`C5B_CLOSED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
