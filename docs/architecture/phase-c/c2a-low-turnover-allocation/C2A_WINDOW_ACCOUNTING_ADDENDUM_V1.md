# C2A Window Accounting Addendum V1

## Authority

This is a normative part of `C2A_LOW_TURNOVER_ALLOCATION_CONTRACT_V1.md`. Both documents must be hash-bound, snapshotted, reviewed, and retained in every authoritative C2A artifact. Where accounting detail is ambiguous, this addendum controls.

- Stage: `C2A`
- Economic execution: `NOT_STARTED`
- C2B confirmation: `CLOSED`
- Holdout: `CLOSED`
- Live: `FORBIDDEN`

## Independent window cells

Each policy/window/cost cell is an independent simulation.

- It starts with exactly `1000 USDT` cash.
- It inherits no equity, holdings, target weights, turnover state, or pending action from another window.
- Indicator candles before the window start are startup data only and never contribute economic return.
- The first scheduled deployment is subject to the same `10` percentage-point no-trade band and `50%` scheduled-rebalance turnover cap as later scheduled rebalances.

## Terminal liquidation

At the last completed daily close strictly before the window's exclusive end, all remaining holdings must be liquidated to cash.

- The cell's frozen cost rate is charged on the liquidation notional.
- Terminal liquidation is mandatory.
- It is not subject to the no-trade band or the scheduled-rebalance turnover cap.
- It counts in fees, traded notional, and turnover.
- It does not count as a scheduled non-zero rebalance for the activity gate.
- Every economic cell must therefore begin and end in cash.

## Aggregate metrics

No additional aggregate backtest row is allowed. The retained economic row count remains exactly `27`.

Derived aggregate metrics are calculated from the three independent windows as follows:

- aggregate net return: `product(1 + window_net_return) - 1`, in S1, S2, S3 order;
- aggregate daily-return series: concatenate the three independent net daily-return series in S1, S2, S3 order, with no synthetic boundary return;
- aggregate Sharpe: calculate from that concatenated daily-return series with the frozen `365` annualization and zero risk-free rate;
- aggregate asset PnL: sum absolute USDT asset-level PnL from three equal-starting-capital windows;
- aggregate window PnL: use each window's absolute USDT PnL from its `1000 USDT` start;
- annualized one-way turnover: sum every `traded_notional / pre_trade_equity` term, including terminal liquidations, then multiply by `365 / total_screen_calendar_days`.

All aggregate formulas must be independently recomputed by the finalizer.

## Comparator accounting

Comparators are non-selectable and are calculated independently for each window using the same starting equity, dates, terminal liquidation, and cost treatment.

- `100% cash` remains cash throughout.
- BTC buy-and-hold is established at the first executable open in each window and terminally liquidated.
- Static equal-weight BTC/ETH/SOL buy-and-hold is established at the first executable open in each window, is not rebalanced, and is terminally liquidated.
- Comparator aggregate metrics use the same frozen window-combination formulas above.

## Evidence failure conditions

C2A is an evidence failure, not an economic rejection, when:

- a cell does not start and end in cash;
- terminal liquidation or its costs are missing;
- window state leaks into another window;
- an aggregate formula differs from this addendum;
- aggregate metrics are stored without independently reproducible window inputs;
- either contract document is absent from the effective source inventory or retained source snapshot.

`CONFIRMATION_CLOSED` / `HOLDOUT_CLOSED` / `LIVE_FORBIDDEN`
