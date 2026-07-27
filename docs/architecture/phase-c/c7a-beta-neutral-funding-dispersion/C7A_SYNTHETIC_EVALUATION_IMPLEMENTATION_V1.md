# C7A synthetic evaluation implementation V1

## Scope

This change implements the next synthetic-only C7A layer after the frozen design and synthetic signal/accounting core.

It authorizes no real OKX data, network access, partial prospective performance, economic run, C7B read, paper, shadow, private API, or live execution.

## Producer aggregation

The producer accepts exactly 26 weekly accounting rows on the frozen C7A decision grid for each cost label: `1.0x`, `1.5x`, and `2.0x`.

Every row must reconcile:

- starting and ending equity;
- net funding PnL against gross funding receipts and payments;
- relative-price PnL;
- trading costs;
- one-way turnover;
- active state and orientation;
- BTC weekly mark return;
- zero missing decisions and zero unaccounted funding settlements.

The aggregator derives:

- first-half, second-half, and aggregate net return;
- maximum drawdown;
- annualized weekly Sharpe;
- weekly probabilistic Sharpe ratio;
- weekly return beta to BTC;
- funding receipts-to-cost ratio;
- carry-only stress return;
- active-week and orientation concentration;
- annualized turnover;
- positive-week PnL concentration.

The fixed C7A gate evaluator applies every preregistered economic, risk, attribution, activity, concentration, and comparator requirement without ranking or parameter search.

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
