# C10A Cross-Sectional Residual Momentum — Contract V1

## 1. Status and authority

- Stage: `C10A`
- Change type: `DESIGN_AND_PROGRAM_GUARD`
- Required design base: `7c799ea993787ff2d5298cc15450d1fac4e4e8b4`
- Selectable candidate count: `1`
- Historical economic result: `NOT_RUN`
- Data status: `HISTORICAL_DEVELOPMENT_ONLY`
- Execution-feasibility evidence: `NOT_ESTABLISHED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This document prospectively freezes one economic-mechanism screen and the
program-history correction that applies to it. It authorizes no market-data
download until the design is merged, no authenticated request, no account
access, no order, no Paper or Shadow side effect, and no Live path.

The implementation may reuse reviewed public-data custody, replay, manifest,
and independent-review infrastructure. It may not reuse a prior strategy's
economic result as an input or change the values below after seeing C10A
economics.

## 2. Falsifiable hypothesis and separation from prior stages

C10A tests this proposition:

> Within a fixed pool of large, liquid OKX USDT perpetual swaps, the component
> of each instrument's recent return that is not explained by the concurrent
> leave-one-out cross-sectional market factor persists over the next week. A
> low-gross, dollar-neutral long-winner/short-loser portfolio may therefore
> retain positive return after funding and conservative complete transaction
> costs, and may add value beyond an otherwise identical raw-price-momentum
> portfolio.

This is not a C8A or C9A retune:

- C8A was two-asset directional time-series momentum. C10A is an eight-asset
  cross-sectional ranking with simultaneous long and short legs.
- C9A was a spot/perpetual funding-carry hedge selected by funding and basis.
  C10A has no spot leg, no carry threshold, and funding never enters its signal.
- C4A was long-only raw return/high-proximity momentum on spot. C10A removes a
  contemporaneous cross-sectional factor, uses a dollar-neutral swap
  portfolio, and must beat a fixed raw-return-momentum comparator.
- No threshold, lookback, universe size, cost, or gate from an earlier result
  may be tried as a C10A alternative.

Research motivating the test includes evidence of short-horizon
cross-sectional cryptocurrency momentum, evidence that survivor-only fixed
universes can eliminate apparent momentum, and recent work using residual
momentum in cryptocurrency factor models. These sources motivate a falsifiable
test; they do not establish that C10A will pass:

- Hoffstein, Drogen, and Otte, “Cross-sectional Momentum in Cryptocurrency
  Markets,” SSRN 4322637: <https://doi.org/10.2139/ssrn.4322637>
- Grobys et al., “On survivor cryptocurrency momentum,” *Finance Research
  Letters* 92 (2026): <https://doi.org/10.1016/j.frl.2026.109602>
- Li and Zhu, “Taming crypto anomalies: A Lasso-type factor model,” *Research
  in International Business and Finance* 83 (2026), article 103298:
  <https://doi.org/10.1016/j.ribaf.2026.103298>

## 3. Program-level multiple-testing boundary

The machine-readable authority is
`implementation/config/phase_c_research_program_registry_v1.json`.

Before C10A, Phase C has a declared lower bound of `626` observed economic
trials:

| Stage | Count | Treatment |
|---|---:|---|
| C0B | 9 | three strategies by three base timeframes |
| C0C | 600 | three 200-epoch Hyperopt searches |
| C1A | 3 | three selectable families |
| C2A | 3 | three selectable allocation policies |
| C3A | 3 | three residual-reversion policies |
| C4A | 3 | three cross-sectional policies |
| C5A | 2 | selectable candidate plus observed ablation |
| C6A | 0 | economics never ran |
| C7A | 1 | one candidate |
| C8A | 1 | one candidate |
| C9A | 1 | one candidate |

C10A is prospective trial `627`. This count is explicitly a lower bound. It
does not pretend to enumerate unpublished human ideas or pre-Phase-C
discretion, so even a pass is historical development evidence rather than a
global proof of edge.

Let `PSR` be the one-sided probabilistic Sharpe probability versus zero from
the complete 130-week candidate series. The declared-program family-wise
adjustment is:

```text
bonferroni_adjusted_psr = max(0, 1 - 627 * (1 - PSR))
```

Eligibility requires both `PSR >= 0.95` and
`bonferroni_adjusted_psr >= 0.95`. The latter is equivalent to an unadjusted
probability of at least `1 - 0.05 / 627`. This is not called a Deflated Sharpe
Ratio and must not be relabelled as one.

Removing a prior trial, excluding a weak diagnostic, treating a previously
seen interval as pristine, renaming the raw comparator, or changing the trial
count after economic inspection is `PROGRAM_FAILURE`.

## 4. Historical boundary and independent windows

All C10A market outcomes are already exposed by earlier Phase C work and must
always be labelled `HISTORICAL_DEVELOPMENT_ONLY`.

Formation-only liquidity interval:

- start inclusive: `2023-07-03T00:00:00Z`;
- end exclusive: `2024-01-01T00:00:00Z`.

Mark-price warm-up begins at `2023-10-08T22:00:00Z`. Warm-up and formation
observations may select the universe or initialize the first signal but may
not contribute economic PnL.

The five independent economic windows are:

| Window | Start inclusive | End exclusive |
|---|---|---|
| H1 | `2024-01-01T00:00:00Z` | `2024-07-01T00:00:00Z` |
| H2 | `2024-07-01T00:00:00Z` | `2024-12-30T00:00:00Z` |
| H3 | `2024-12-30T00:00:00Z` | `2025-06-30T00:00:00Z` |
| H4 | `2025-06-30T00:00:00Z` | `2025-12-29T00:00:00Z` |
| H5 | `2025-12-29T00:00:00Z` | `2026-06-29T00:00:00Z` |

Each window starts with `1000 USDT`, no position, no PnL, and no carried risk
state. Each contains exactly 26 Monday decisions. All five windows must be
captured and evaluated together once after implementation is frozen. Partial
inspection, best-window selection, changed-window reruns, and post-result
retuning are forbidden.

A later prospective confirmation may be designed separately, but C10A does
not wait for 2027 and does not authorize such a window.

## 5. Fixed candidate pool and liquidity formation

The exact candidate pool is:

1. `ADA-USDT-SWAP`
2. `AVAX-USDT-SWAP`
3. `BCH-USDT-SWAP`
4. `BTC-USDT-SWAP`
5. `DOGE-USDT-SWAP`
6. `DOT-USDT-SWAP`
7. `ETH-USDT-SWAP`
8. `LINK-USDT-SWAP`
9. `LTC-USDT-SWAP`
10. `SOL-USDT-SWAP`
11. `TRX-USDT-SWAP`
12. `XRP-USDT-SWAP`

For every instrument, formation uses every completed official one-hour trade
candle in the exact formation interval. OKX defines derivative candle fields
as `[ts,o,h,l,c,vol,volCcy,volCcyQuote,confirm]`; the liquidity observation is
the eighth field, `volCcyQuote`, in USDT. The contract-count field `vol`, the
base-currency field `volCcy`, and `close * vol` are forbidden substitutes.

The liquidity score is the median finite, non-negative `volCcyQuote`. Sort
descending, break exact ties by lexical instrument ID, and freeze exactly the
top eight. Missing formation hours, unconfirmed candles, inconsistent field
counts, or an instrument without complete coverage is `DATA_FAILURE`; no
replacement asset is allowed.

The selected top eight remain fixed in H1–H5. Formation returns, volatility,
funding, or later liquidity may not affect selection.

## 6. Official-public data and custody

Permitted source material is limited to official public OKX data:

- historical one-hour swap trade candles;
- historical one-hour swap mark-price candles for the selected instruments
  and the fixed `BTC-USDT-SWAP` beta benchmark;
- realized funding records for selected instruments.

Official references:

- OKX historical market data: <https://www.okx.com/historical-data>
- OKX API guide: <https://www.okx.com/docs-v5/en/>

The API's recent history endpoint may supplement or overlap-check official
download files but may not silently replace missing historical coverage.
Funding uses actual `fundingTime` and `realizedRate`; no fixed eight-hour
interval may be assumed because historical intervals can vary.

The capture sequence is fixed:

1. persist raw formation responses for all twelve instruments;
2. strictly normalize formation candles and freeze the top eight;
3. persist raw trade, mark, and funding responses required for those eight;
   `BTC-USDT-SWAP` benchmark mark candles are always retained even if BTC is
   not selected, and may affect only the frozen BTC-beta diagnostic;
4. strictly normalize and inner-align only after raw persistence;
5. create recursive SHA-256 manifests over source, normalized, replay,
   independent-review, and final-classification evidence.

Every retained request records requested URL, final URL, collection time,
media type, byte length, retry history, and SHA-256. Redirects may not change
official host, path, or query semantics. Writes are atomic, may not overwrite,
and may not escape the package root.

All normalized timestamps are UTC, unique, strictly increasing, and on the
one-hour grid. Candles must be confirmed, complete, finite, and have positive
OHLC with valid geometry. Duplicate or contradictory funding settlements,
missing required hours, non-progressing pagination, cross-page duplicates,
overshoot leakage, or non-finite values fail closed. Actual funding gaps
greater than eight hours plus one minute fail closed unless exact official
evidence records a different settlement interval for that instrument and
timestamp.

No authenticated request may occur. Every package states:

```text
authenticated = false
contains_account_data = false
contains_order_data = false
paper_side_effect = false
shadow_side_effect = false
live = FORBIDDEN
```

## 7. Decision clock and anti-lookahead rule

Decisions occur every Monday at `00:00:00Z`. At decision `t`:

- the most recent permitted mark candle is stamped `t - 2 hours` and closes
  at `t - 1 hour`;
- the candle stamped `t - 1 hour`, which closes at `t`, is forbidden;
- funding and any other record stamped at or after `t` is forbidden to the
  signal;
- modeled transactions use the separate trade-candle open stamped `t`.

The 84-day regression uses exactly `2016` one-hour log-return observations
ending at the most recent permitted mark close. The score uses the final
`672` of those returns. All eight selected instruments must have the identical
timestamp grid; forward filling and asynchronous last-known values are
forbidden.

## 8. Frozen residual-momentum signal

For selected instrument `i`, define its hourly mark log return `r_i`. At a
decision, for every timestamp in the 2016-return regression window define the
leave-one-out factor:

```text
f_i = arithmetic mean of the other seven instruments' log returns
```

Fit ordinary least squares with intercept over all 2016 paired observations:

```text
r_i = alpha_i + beta_i * f_i + epsilon_i
```

The fit is invalid if either input variance is zero, any value is non-finite,
the row count differs from 2016, or timestamps do not match exactly.

The frozen score is:

```text
score_i = sum(r_i - alpha_i - beta_i * f_i)
          over the final 672 regression-window observations
```

Rank descending by numeric score and break exact ties lexically. The candidate
is long the top two and short the bottom two. No sign filter, volatility
scaler, beta cap inside the signal, regime rule, funding filter, alternative
lookback, alternate factor, winsorization, outlier deletion, optimizer,
machine learning model, or LLM output is permitted.

## 9. Continuous-notional portfolio and accounting

C10A is a continuous-notional economic-mechanism screen. It does not use or
claim historical contract count, `ctVal`, lot size, minimum size, tick size,
order admissibility, fill probability, or liquidation mechanics.

At every decision, using pre-trade equity `E` and the trade open:

- total long notional: `+0.25 * E`;
- total short notional: `-0.25 * E`;
- each of two long targets: `+0.125 * E`;
- each of two short targets: `-0.125 * E`;
- gross notional: `0.50 * E`;
- signed target notional: exactly zero within `1e-10 USDT`.

Signed continuous base quantity equals signed target notional divided by the
instrument trade open. Rebalance every target to its exact new quantity; no
no-trade band exists. Quantity changes pay cost independently.

Between trades, signed mark-price PnL is:

```text
price_pnl = signed_base_quantity * (mark_new - mark_old)
```

At an actual funding settlement, using the last completed preceding mark:

```text
funding_pnl = -signed_base_quantity * preceding_mark * realizedRate
```

Thus a positive rate is a debit to a long and a credit to a short. A funding
event at the same timestamp as a scheduled trade applies first to the carried
position. A newly opened position cannot receive that event. Funding at an
exclusive window boundary is excluded before terminal liquidation.

Every hourly state retains cash/equity, quantities, marked notionals, price
PnL, funding PnL, costs, gross, net, and contribution by instrument. If
`equity / gross_notional < 1.25`, the portfolio is marked for fail-closed
liquidation at the next trade open and records a buffer breach. Eligibility
requires zero breaches. Non-positive equity, missing next opens, gross or net
drift, or a reconciliation residual above `1e-10 USDT` is `PROGRAM_FAILURE`
or `DATA_FAILURE`, never an economic loss.

Every exclusive boundary liquidates at its boundary trade opens, charges
costs, and leaves exactly cash. No state crosses windows.

## 10. Frozen costs

One-side all-in costs applied to absolute changed notional are:

- expected `1.0x`: `0.0015`;
- stress `1.5x`: `0.00225`;
- stress `2.0x`: `0.0030`.

Entry, exit, change, reversal, forced close, and terminal close all pay the
applicable cost. The three cells replay independently because costs alter
equity and therefore later target quantities. No maker rebate, VIP tier,
spread income, cash yield, collateral yield, lending, staking, or other credit
is allowed.

## 11. Fixed non-selectable comparators

Every window and cost cell computes:

1. `CashComparator`: 100% USDT and zero return;
2. `RawReturnMomentumComparator`: same top-two/bottom-two construction,
   schedule, gross, costs, funding, accounting, and tie rules, but ranks the
   sum of each instrument's raw log returns over the same final 672 hours;
3. `AlwaysLongSelectedUniverseComparator`: equal-weight long positions across
   all eight selected instruments at total gross `0.50`, rebalanced weekly
   with identical costs, funding, and boundary liquidation.

Comparators are never selectable. The raw-return comparator is the fixed
incremental-information test: the candidate must beat it on return and
Sharpe without worse drawdown or turnover.

## 12. Metrics and independent recomputation

Each window retains 26 decision-to-decision weekly buckets, including zero
return buckets. Window return is `final_equity / 1000 - 1`. Because windows
are independently funded, pooled return is:

```text
pooled_return = sum(final_equity_H1..H5) / 5000 - 1
```

The 130 weekly returns are concatenated only for statistics. Annualized
weekly Sharpe uses sample standard deviation with `ddof=1`. PSR versus zero
uses raw weekly Sharpe, bias-corrected sample skewness, ordinary kurtosis, and
the non-normality correction. Invalid variance or radicand is PSR zero unless
caused by invalid source/program state, which fails the run.

BTC beta is OLS beta of candidate weekly arithmetic returns on BTC weekly
arithmetic mark returns, with intercept, over the same 130 buckets. For a
bucket `[t, next_t)`, the benchmark return is the close of the mark candle
stamped `next_t - 1 hour` divided by the close of the mark candle stamped
`t - 1 hour`, minus one. Maximum drawdown is the worst
within-window drawdown over complete post-event hourly paths. Annualized
one-way turnover is absolute changed notional divided by pre-trade equity,
summed and divided by 2.5 years.

Instrument, window, week, price, funding, and cost contributions must
reconcile to equity within `1e-10 USDT`.

A physically separate independent implementation must read primitive
normalized data, must not import the production replay, signal, ledger, gate,
or finalizer modules, and must recompute:

- liquidity formation and exact top eight;
- regression inputs, alphas, betas, residual scores, ranks, and directions;
- all three cost replays and all comparators;
- funding and cost accounting;
- weekly and pooled statistics, PSR, Bonferroni adjustment, beta, drawdown,
  turnover, attribution, concentration, and every gate;
- complete source and evidence manifest hashes.

Any mismatch above absolute and relative tolerance `1e-10` is
`PROGRAM_FAILURE`.

## 13. Frozen all-gates decision

C10A is `HISTORICAL_ECONOMIC_PASS` only if every gate below passes at expected
cost unless a different cost is stated.

### 13.1 Return and stability

- all five window returns are strictly positive;
- pooled return is strictly positive;
- pooled return at `1.5x` cost is strictly positive;
- pooled return at `2.0x` cost is non-negative.

### 13.2 Statistics and risk

- annualized weekly Sharpe is at least `1.00`;
- weekly PSR versus zero is at least `0.95`;
- declared-program Bonferroni-adjusted PSR across 627 trials is at least
  `0.95`;
- maximum drawdown in every window is at most `0.15`;
- absolute BTC beta is at most `0.20`;
- equity-buffer breaches equal zero;
- missing decisions, invalid regressions, unaccounted funding, non-finite
  states, non-positive equity, gross/net drift, and reconciliation failures
  all equal zero.

### 13.3 Activity, cost, breadth, and concentration

- decision count equals `130`;
- non-flat instrument directions equal `520`;
- annualized one-way turnover is at most `18.0x`;
- at least six of eight instruments have positive net contribution;
- maximum positive-instrument PnL share is at most `0.35`;
- maximum positive-window PnL share is at most `0.40`;
- maximum positive-week PnL share is at most `0.15`;
- top-three positive-week PnL share is at most `0.35`.

### 13.4 Incremental value over raw momentum

- candidate pooled return minus raw-momentum pooled return is strictly
  positive;
- candidate annualized Sharpe minus raw-momentum annualized Sharpe is at
  least `0.10`;
- candidate maximum drawdown is no greater than raw momentum;
- candidate turnover is no greater than raw momentum.

No relatively best ineligible result, comparator, cost cell, instrument
subset, or window subset may be promoted. A valid run that misses one or more
gates is `ECONOMIC_FAIL`, distinct from `DATA_FAILURE` and `PROGRAM_FAILURE`.

## 14. One-shot authority and closeout

After design merge, implementation, tests, independent review, and exact-head
CI pass, one temporary explicit workflow input/job may authorize one C10A
H1–H5 authority run. It must bind requested SHA, observed checkout SHA, run ID,
attempt, clean worktree, source manifests, and result manifests.

The authority may run once. A valid `ECONOMIC_FAIL` is final and may not be
rerun or tuned. A genuine pre-economic data or program failure may be
remediated only if retained evidence proves no economic result was exposed and
the remediation changes no frozen economic semantic; each invocation still
must be disclosed.

Closeout must remove the temporary input/job and commit the exact final
classification, run/job/artifact IDs, artifact digest, manifest digests,
tests, independent review, safety state, and failed gates.

## 15. Promotion boundary

Even `HISTORICAL_ECONOMIC_PASS` establishes only idealized continuous-notional
historical development evidence. It does not establish order feasibility,
capacity, spread/slippage beyond the frozen cost, liquidation behavior,
contract-size admissibility, or forward edge.

Only after every gate passes may a separate read-only Shadow design be
proposed. Such Shadow may use public market data only, access no account,
submit no order, create no Paper balance side effect, and may never
automatically upgrade to Live. Live remains forbidden without a separate
security design and explicit user authorization.

`C10A_DESIGN_FROZEN`

`HISTORICAL_DEVELOPMENT_ONLY`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
