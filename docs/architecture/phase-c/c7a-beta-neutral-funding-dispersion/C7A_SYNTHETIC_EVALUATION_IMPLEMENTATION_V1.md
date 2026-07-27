# C7A synthetic evaluation implementation V1

## Scope

This change implements the next synthetic-only C7A layer after the frozen design and synthetic signal/accounting core.

It authorizes no real OKX data, network access, partial prospective performance, economic run, C7B read, paper, shadow, private API, or live execution.

## Producer aggregation

The producer accepts exactly 26 weekly accounting rows on the frozen C7A decision grid for each cost label: `1.0x`, `1.5x`, and `2.0x`.

Every candidate row must reconcile:

- starting and ending equity;
- net funding PnL against gross funding receipts and payments;
- total and negative-only relative-price PnL;
- traded notional, one-way turnover, and the exact frozen one-side cost rate;
- a 169-point positive hourly equity path whose first and final values match the weekly boundaries;
- active state and one of the two frozen orientations, or `CASH` when inactive;
- BTC weekly mark return;
- zero missing decisions and zero unaccounted funding settlements.

Comparator rows use the same 26-week decision grid and 169-point weekly equity-path contract. Comparator identities are restricted to the three preregistered non-selectable comparators.

The aggregator derives:

- first-half, second-half, and aggregate net return;
- maximum drawdown from the complete hourly equity path rather than weekly endpoints;
- annualized weekly Sharpe;
- bias-corrected weekly probabilistic Sharpe ratio;
- weekly return beta to BTC;
- funding receipts-to-cost ratio;
- carry-only stress return that removes positive relative-price PnL while retaining negative relative-price PnL and all costs;
- active-week and orientation concentration;
- annualized one-way turnover;
- positive-week PnL concentration.

The fixed C7A gate evaluator applies every preregistered economic, risk, attribution, activity, concentration, and comparator requirement without ranking or parameter search. It independently pins the required `AlwaysOnFundingRankComparator` identity.

## Synthetic boundary

Both candidate and comparator aggregation require the exact synthetic metadata contract. Any real-market marker, network access, economic-run state, paper, shadow, or live drift fails before aggregation.

## Validation

Focused deterministic tests cover:

- a complete synthetic selected fixture;
- weekly accounting tamper rejection;
- producer real-data-boundary rejection;
- frozen orientation-concentration rejection.

Applicable merge gate: ordinary CI. Freqtrade Validation is not applicable because no Freqtrade strategy, market-data download, or execution runtime is changed.

A physically separate aggregate reviewer and retained evidence-package builder remain separate implementation-only work. This change grants no execution authorization.

`C7A_IMPLEMENTATION_ONLY_SYNTHETIC` / `NO_REAL_DATA` / `NO_ECONOMIC_RUN` / `C7B_CLOSED` / `PAPER_CLOSED` / `SHADOW_CLOSED` / `LIVE_FORBIDDEN`
