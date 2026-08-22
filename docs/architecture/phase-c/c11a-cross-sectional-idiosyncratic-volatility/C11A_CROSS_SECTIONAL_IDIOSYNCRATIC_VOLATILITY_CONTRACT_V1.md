# C11A Cross-Sectional Idiosyncratic Volatility — Contract V1

## 1. Status and authority

- Stage: `C11A`
- Change type: `DESIGN_AND_PROGRAM_GUARD`
- Required design base: `4fea1df7e7def3323199c278555f5b9308da50a9`
- Selectable candidate count: `1`
- Historical economic result: `NOT_RUN`
- Data status: `HISTORICAL_DEVELOPMENT_ONLY`
- Execution-feasibility evidence: `NOT_ESTABLISHED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This document prospectively freezes one new economic-mechanism screen. It
authorizes no market-data download until the design is merged, no authenticated
request, no account access, no order, no Paper or Shadow side effect, and no
Live path. Public-data custody and accounting infrastructure may be reused;
prior economic results may not be used as C11A inputs.

## 2. Hypothesis and separation from prior stages

C11A tests one falsifiable proposition:

> Within a formation-frozen pool of large, liquid OKX USDT perpetual swaps,
> instruments with higher recent volatility unexplained by a concurrent
> leave-one-out market factor earn a positive next-week cross-sectional risk
> premium relative to low-idiosyncratic-volatility instruments, after actual
> funding and conservative complete transaction costs.

The candidate is a weekly long-high/short-low idiosyncratic-volatility sort.
It is not momentum, reversal, carry, basis, crowding, or an AI-selected rule:

- C10A ranked the signed sum of recent OLS residual returns; C11A discards
  residual sign and ranks their sample dispersion.
- C8A and C4A ranked directional past returns. C11A does not use cumulative
  return in its signal.
- C7A and C9A used funding or basis in their signals. C11A records funding
  only as realized PnL.
- C3A traded residual-return reversal. C11A makes no forecast from residual
  direction.

Published evidence reports a positive cross-sectional relationship between
cryptocurrency idiosyncratic volatility and subsequent return, including
weekly portfolio sorts and robustness to liquidity screens. It also reports
no reliable time-series relation, so C11A is explicitly cross-sectional:

- Zhang and Li, “Is idiosyncratic volatility priced in cryptocurrency
  markets?”, *Research in International Business and Finance* 54 (2020),
  101252: <https://doi.org/10.1016/j.ribaf.2020.101252>
- Liu, Tsyvinski, and Wu, “Common Risk Factors in Cryptocurrency,” *Journal
  of Finance* 77 (2022), 1133–1177: <https://doi.org/10.3386/w25882>

These sources motivate the direction; they do not establish that this exact
OKX perpetual-swap implementation will pass.

## 3. Multiple-testing boundary

The machine-readable authority is
`implementation/config/phase_c_research_program_registry_v2.json`.

Before C11A, Phase C has a declared lower bound of `626` observed economic
trials. C10A contributes zero economic trials because its frozen evaluator
failed before replay and produced no return, statistic, comparator, or gate.
Its `PROGRAM_FAILURE` and no-rerun state remain registered and immutable.

C11A is prospective economic trial `627`. For one-sided weekly PSR versus
zero:

```text
bonferroni_adjusted_psr = max(0, 1 - 627 * (1 - PSR))
```

Eligibility requires raw `PSR >= 0.95` and adjusted `PSR >= 0.95`. The count
is a declared lower bound, not a claim that unpublished human discretion is
fully corrected. Removing a prior trial, relabelling C10A as economic,
changing a weak result, or changing this count after inspection is
`PROGRAM_FAILURE`.

## 4. Historical windows and fixed universe

All outcomes are already-exposed historical development evidence. Formation
uses every confirmed official one-hour trade candle in
`[2023-07-03T00:00:00Z, 2024-01-01T00:00:00Z)`. For each of these twelve
instruments, rank median OKX derivative-candle `volCcyQuote` descending and
break exact ties lexically:

`ADA`, `AVAX`, `BCH`, `BTC`, `DOGE`, `DOT`, `ETH`, `LINK`, `LTC`, `SOL`,
`TRX`, and `XRP`, each as `-USDT-SWAP`.

Freeze exactly the top eight before H1. The selected set cannot change. A
missing formation hour, unconfirmed row, invalid quote volume, or incomplete
candidate fails closed; no replacement is allowed.

Mark warm-up begins `2023-12-03T22:00:00Z`. The independent windows are:

| Window | Start inclusive | End exclusive |
|---|---|---|
| H1 | `2024-01-01T00:00:00Z` | `2024-07-01T00:00:00Z` |
| H2 | `2024-07-01T00:00:00Z` | `2024-12-30T00:00:00Z` |
| H3 | `2024-12-30T00:00:00Z` | `2025-06-30T00:00:00Z` |
| H4 | `2025-06-30T00:00:00Z` | `2025-12-29T00:00:00Z` |
| H5 | `2025-12-29T00:00:00Z` | `2026-06-29T00:00:00Z` |

Each starts with `1000 USDT`, no position, and no carried state. Each has 26
Monday decisions. All five must be captured and evaluated together once.
Partial inspection, subset selection, and post-result retuning are forbidden.

## 5. Official-public data custody

Only official public OKX trade candles, mark-price candles, and realized
funding records are permitted. Raw responses must be durably persisted before
normalization, with requested/final URLs, timestamps, media type, byte size,
retry history, and SHA-256. Redirects must remain in the reviewed official
allowlist and may not change API path/query semantics.

Official references are the OKX [historical-data portal](https://www.okx.com/historical-data)
and [API guide](https://www.okx.com/docs-v5/en/).

All candles must be UTC, confirmed, finite, unique, strictly increasing,
hour-grid aligned, geometrically valid, and complete. Funding retains actual
`fundingTime` and `realizedRate`; small official delivery offsets are valid.
Funding preserves actual `fundingTime`, must be unique and strictly increasing,
and gaps greater than eight
hours plus one minute fail unless exact official evidence establishes another
interval. Missing hours, duplicates, contradictory settlements, cursor
stalling, overshoot, malformed records, or non-finite values fail closed.

The package and recursive manifests must state:

```text
authenticated = false
contains_account_data = false
contains_order_data = false
paper_side_effect = false
shadow_side_effect = false
live_state = LIVE_FORBIDDEN
```

## 6. Decision clock and frozen signal

Decisions occur Monday `00:00:00Z`. At decision `t`, the most recent usable
mark candle is stamped `t - 2 hours` and closes at `t - 1 hour`. The candle
stamped `t - 1 hour`, funding at or after `t`, and the trade open at `t` are
forbidden to the signal. Modeled transactions use that separate trade open.

For every selected instrument `i`, use exactly `672` one-hour log returns
ending at the last permitted mark close. Timestamp grids must match exactly.
At every return timestamp define the leave-one-out factor as the arithmetic
mean of the other seven returns, then fit OLS with intercept:

```text
r_i = alpha_i + beta_i * f_i + epsilon_i
score_i = sample_standard_deviation(epsilon_i, ddof=1)
```

Zero variance, a non-finite value, any row-count/grid mismatch, or an invalid
regression fails closed. Rank scores descending, break exact ties by lexical
instrument ID, long the highest two, and short the lowest two. No sign filter,
outlier deletion, winsorization, volatility scaler, regime rule, funding
filter, alternate lookback, optimizer, machine learning, or LLM decision is
permitted.

## 7. Portfolio, costs, and funding

C11A is a continuous-notional economic screen, not execution-feasibility
evidence. At every decision, using pre-trade equity `E`:

- two longs each target `+0.125 * E`;
- two shorts each target `-0.125 * E`;
- total gross is `0.50 * E`; signed target notional is zero within `1e-10`.

Signed quantity is target notional divided by trade open. Every quantity
change pays one-side all-in costs of `0.0015`, independently replayed at
`1.5x = 0.00225` and `2.0x = 0.0030`. Entries, changes, reversals, forced
closes, and terminal closes all pay; there are no rebates or credits.

Price PnL uses completed marks. Funding uses its actual timestamp and the last
completed preceding mark:

```text
funding_pnl = -signed_base_quantity * preceding_mark * realizedRate
```

Exact-time funding precedes a trade; delayed funding applies after the trade
to the then-carried position. Weekly-boundary funding is attributed to the
week/position carrying it. Funding at an exclusive window boundary is
excluded before terminal liquidation. Every settlement must be accounted
exactly once. Buffer checks at funding value all positions using completed
predecessor marks. `equity / gross_notional < 1.25` forces fail-closed next-open
liquidation and makes the candidate ineligible. No state crosses windows.

## 8. Fixed non-selectable comparators

Every window and cost cell computes:

1. `CashComparator`: cash only;
2. `TotalVolatilityComparator`: identical weekly top-two/bottom-two portfolio,
   accounting, costs, funding, and tie rules, but ranks the sample standard
   deviation (`ddof=1`) of each instrument's same 672 raw log returns;
3. `AlwaysLongSelectedUniverseComparator`: equal-weight long all eight at
   total gross `0.50`, weekly rebalanced with identical accounting.

Comparators are never selectable. The total-volatility comparator isolates
whether factor removal adds value beyond a simple high-volatility sort.

## 9. Evidence, independent recomputation, and gates

The production replay and a physically separate implementation must
independently recompute universe selection, signal regressions/scores/ranks,
all portfolios and cost cells, actual funding, weekly paths, statistics,
attribution, every gate, and all manifest hashes from primitive normalized
data. The independent code may not import the production replay, signal,
ledger, gate, or finalizer. Any mismatch above absolute and relative `1e-10`
is `PROGRAM_FAILURE`.

The 130 weekly returns include zero buckets. Annualized Sharpe uses sample
standard deviation (`ddof=1`); PSR uses sample skewness, ordinary kurtosis,
and the frozen non-normality correction. BTC beta uses the same weekly clock.
All price, funding, cost, instrument, window, and week contributions must
reconcile within `1e-10 USDT`.

C11A is `HISTORICAL_ECONOMIC_PASS` only if every gate passes:

- all five window returns and pooled expected-cost return are strictly
  positive; `1.5x` pooled return is positive; `2.0x` is non-negative;
- weekly Sharpe is at least `1.00`, PSR at least `0.95`, and Bonferroni-
  adjusted PSR across 627 trials at least `0.95`;
- every window drawdown is at most `0.15`, absolute BTC beta at most `0.20`,
  and buffer breaches equal zero;
- decisions equal `130`, non-flat directions equal `520`, annualized one-way
  turnover is at most `18.0x`, and at least six instruments contribute
  positively;
- maximum positive instrument/window/week shares are `0.35`, `0.40`, and
  `0.15`; top-three positive-week share is at most `0.35`;
- versus `TotalVolatilityComparator`, pooled return improvement is strictly
  positive, Sharpe improvement is at least `0.10`, drawdown is no worse, and
  turnover is no greater;
- missing decisions, invalid regressions, non-positive equity, unaccounted
  funding, non-finite state, gross/net drift, and reconciliation failures are
  all zero.

No relatively best ineligible result, comparator, cost cell, asset subset, or
window subset may be promoted. A valid gate miss is `ECONOMIC_FAIL`, distinct
from `DATA_FAILURE` and `PROGRAM_FAILURE`.

## 10. One-shot and promotion boundary

After design merge, implementation merge, exact-head CI, tests, secret scan,
and independent review, one temporary explicit workflow input/job may
authorize exactly one C11A H1–H5 run. It must bind the requested and observed
SHA, run ID/attempt, clean worktree, source/evidence manifests, and immutable
artifact. It may not be retriggered or tuned after economic inspection.

A closeout removes the temporary input/job and records exact run/job/artifact
IDs, digests, classification, tests, failed gates, and safety state. Even a
historical pass establishes neither executable orders nor forward edge. It
permits only a separately reviewed, read-only public-data Shadow design. Live
remains forbidden without separate security work and explicit authorization.

`C11A_DESIGN_FROZEN`

`HISTORICAL_DEVELOPMENT_ONLY`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
