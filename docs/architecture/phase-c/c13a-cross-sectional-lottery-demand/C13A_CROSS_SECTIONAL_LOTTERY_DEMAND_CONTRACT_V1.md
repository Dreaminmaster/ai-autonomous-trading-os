# C13A Cross-Sectional Lottery-Demand Reversal — Contract V1

## 1. Status and authority

- Stage: `C13A`
- Change type: `DESIGN_AND_PROGRAM_GUARD`
- Required design base: `3bba7d51355dc5291f5ef6771974844814e5ed76`
- Selectable candidate count: `1`
- Historical economic result: `NOT_RUN`
- Data status: `HISTORICAL_DEVELOPMENT_ONLY`
- Execution-feasibility evidence: `NOT_ESTABLISHED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This design freezes one new historical candidate before any C13A H1–H5
return, position, funding cash flow, comparator, or gate is computed. It
authorizes no authenticated request, account access, order, Paper or Shadow
side effect, or Live path.

## 2. Hypothesis and economic mechanism

C13A tests one proposition:

> Among eight fixed large OKX USDT perpetual swaps, coins with the largest
> single complete UTC-day return during the preceding week subsequently
> underperform coins without an extreme upside day, after conservative costs,
> actual funding, and market-neutral sizing.

The mechanism is lottery demand and extrapolative overpricing after a salient
extreme upside payoff. It is motivated prospectively by “Speculation and
Lottery-Like Demand in Cryptocurrency Markets,” which uses a weekly horizon
and last week's maximum daily return, and by “Skewness Risk and the
Cross-Section of Cryptocurrency Returns,” which reports a negative relation
between asymmetry risk and subsequent crypto returns:

- <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3551948>
- <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4869652>

Those studies motivate one fixed candidate only. They do not prove that this
OKX implementation will pass.

## 3. Structural separation from closed candidates

C13A is not a rescue or retune of an exposed candidate:

- C3A ranked residual cumulative underperformance; C13A uses only the largest
  one-day upside observation and has no residual model.
- C4A and C10A tested price continuation; C13A takes the opposite side of an
  extreme upside tail event and ignores cumulative momentum for selection.
- C11A ranked residual dispersion; C13A does not estimate OLS, beta, residual
  volatility, or a 28-day variance. A fixed total-volatility rank is computed
  only as a non-selectable comparator, and C13A must beat it on return and
  Sharpe while being no worse on drawdown or turnover.
- C5A used derivatives crowding; C7A and C9A used funding as a signal; C12A
  used dated-futures convergence. C13A uses none of these signals. Funding is an unavoidable realized cash flow, never a feature.

The raw seven-day cumulative reversal is also a fixed non-selectable
comparator. C13A must beat it, so success cannot be attributed to an ordinary
winner-minus-loser reversal hidden behind a MAX label.

## 4. Program-history and multiple-testing boundary

The machine authority is
`implementation/config/phase_c_research_program_registry_v4.json`.

The declared prior lower bound remains `627` observed economic trials. C10A
is a zero-trial `PROGRAM_FAILURE`; C12A is a zero-trial `DATA_FAILURE` whose
economics did not start. C11A remains one `ECONOMIC_FAIL`. None may be
relabelled or rerun.

C13A is prospective economic trial `628`:

```text
bonferroni_adjusted_psr = max(0, 1 - 628 * (1 - PSR))
```

Eligibility requires raw weekly PSR at least `0.95` and adjusted PSR at least
`0.95`. The count is a lower bound and does not claim to correct unrecorded
human discretion.

No C13A score, rank, trade, PnL, return, Sharpe, PSR, comparator, or H1–H5
gate was computed or inspected during this design.

## 5. Frozen instruments, windows, and clocks

The exact universe, already fixed as large liquid instruments before C13A,
is:

1. `BTC-USDT-SWAP`
2. `ETH-USDT-SWAP`
3. `SOL-USDT-SWAP`
4. `BCH-USDT-SWAP`
5. `DOGE-USDT-SWAP`
6. `XRP-USDT-SWAP`
7. `LTC-USDT-SWAP`
8. `LINK-USDT-SWAP`

There is no formation ranking, listing substitution, survivorship repair,
asset removal, or adaptive universe. Missing required coverage is
`DATA_FAILURE`.

The five windows are:

| Window | Start inclusive | End exclusive | Weekly decisions |
|---|---|---|---:|
| H1 | `2024-01-01T00:00:00Z` | `2024-07-01T00:00:00Z` | 26 |
| H2 | `2024-07-01T00:00:00Z` | `2024-12-30T00:00:00Z` | 26 |
| H3 | `2024-12-30T00:00:00Z` | `2025-06-30T00:00:00Z` | 26 |
| H4 | `2025-06-30T00:00:00Z` | `2025-12-29T00:00:00Z` | 26 |
| H5 | `2025-12-29T00:00:00Z` | `2026-06-29T00:00:00Z` | 26 |

Every position is rebalanced at Monday `00:00:00Z`. Its signal cutoff is the
preceding Sunday `00:00:00Z`, a fixed 24-hour gap. The seven signal days are
the seven complete UTC days ending at that cutoff. Each daily log return is
the confirmed hourly trade-candle open at `00:00Z` to the next day's
confirmed `00:00Z` open. The first required source timestamp is
`2023-12-24T00:00:00Z`.

A window starts with `1000 USDT`, cash, and no inherited position. Its final
position closes at the window's exclusive Monday boundary. There are exactly
130 decisions and 520 non-flat instrument directions.

## 6. Official-public source custody

Only existing reviewed public OKX sources are allowed:

1. confirmed one-hour trade candles from
   `GET /api/v5/market/history-candles` for the eight exact swaps;
2. one-hour historical mark-price candles for those swaps; and
3. the official OKX monthly funding archives with actual `fundingTime`.

The [OKX API guide](https://www.okx.com/docs-v5/en/) defines historical
candle pagination and the `confirm` flag. Every request URL, final URL,
status, media type, byte length, timestamp, retry, and SHA-256 must be retained
before parsing. Redirect path or query drift, non-HTTPS, unreviewed host,
overwrite, path escape, unmanifested bytes, HTML, malformed JSON/CSV, or
cursor non-progress fails closed.

Trade and mark rows must be finite, unique, strictly increasing, hour-grid
aligned, geometrically valid, confirmed where the schema supplies
confirmation, and complete over every required hour. Funding must preserve
the actual official timestamp; it may not be snapped to an hour. Duplicate,
unordered, missing-predecessor, unaccounted, or cross-file funding settlements
fail closed.

The manifests must state `authenticated=false`,
`contains_account_data=false`, `contains_order_data=false`,
`paper_side_effect=false`, `shadow_side_effect=false`, and
`live_state=LIVE_FORBIDDEN`.

## 7. Frozen signal and portfolio

For instrument `i`, calculate seven daily log returns `r[i,d]` using only
complete days ending at the Sunday cutoff:

```text
MAX7[i] = max(r[i,1], ..., r[i,7])
```

Rank ascending by `(MAX7, instrument_id)`. Long the two lowest and short the
two highest. Equal scores use ascending instrument ID. The middle four are
flat. There is no sign filter, threshold, optimizer, volatility scaling,
regression, winsorization, regime rule, stop, take-profit, early exit, or
intraweek rebalance.

Gross notional is `0.50` of current pre-rebalance equity: `0.25` long and
`0.25` short, with four positions of absolute notional `0.125`. Equity divided
by gross notional must remain at least `1.25`; breach forces the next complete
hourly close and makes the candidate ineligible. Quantities cannot use future
prices, funding, or account state.

## 8. Execution, funding, costs, and ledger

Entry and exit use the exact confirmed Monday `00:00Z` hourly trade-candle
open. Every changed absolute notional pays a one-side all-in cost. Unchanged
positions retain their existing quantity and pay no fictitious turnover.
Costs are replayed at `1.0x=0.0015`, expected `1.5x=0.00225`, and
`2.0x=0.0030`.

Actual OKX funding timestamps are preserved. Funding exactly at the
rebalance timestamp is applied first to the position that carried the prior
interval; delayed funding applies to the position carried at its actual
timestamp. Valuation uses the last complete preceding mark. These semantics
are fixed and cannot be changed by the observed sign of funding.

Price PnL, funding PnL, costs, instrument, window, and week contributions must
reconcile within `1e-10 USDT`. Non-positive equity, missing execution open,
invalid mark, negative unallocated cash, non-finite state, or reconciliation
residual is `DATA_FAILURE` or `PROGRAM_FAILURE`, never an economic loss.

Annualized one-way turnover is one half of total absolute changed notional,
divided by mean weekly equity, multiplied by `52 / observed_week_count`.

## 9. Fixed non-selectable comparators

Every window and cost cell computes:

1. `CashComparator`: cash only;
2. `TotalVolatilityRankComparator`: same universe, clocks, portfolio, ledger,
   funding, and costs, but ranks the sample standard deviation (`ddof=1`) of
   the same seven daily returns, long low and short high; and
3. `RawSevenDayReversalComparator`: identical mechanics but ranks the sum of
   the seven daily log returns, long low and short high.

Comparators are never selectable. Candidate return and Sharpe must exceed
both, while candidate drawdown and turnover must be no worse than each.

## 10. Evidence and economic decision

Production replay and a physically separate implementation must reconstruct
signals, exact ranks, quantities, event ordering, price/funding/cost ledgers,
comparators, weekly paths, statistics, attribution, every gate, and final
classification from primitive normalized rows. Independent code may not
import production signal, replay, ledger, metric, gate, or finalizer modules.
Any mismatch above absolute or relative `1e-10` is `PROGRAM_FAILURE`.

C13A is `HISTORICAL_ECONOMIC_PASS` only if every frozen gate passes:

- all five expected-cost window returns and pooled `1.0x` and `1.5x` returns
  are strictly positive; pooled `2.0x` return is non-negative;
- annualized weekly Sharpe is at least `1.00`, raw PSR at least `0.95`, and
  Bonferroni-adjusted PSR over 628 trials at least `0.95`;
- every window drawdown is at most `0.15`, absolute BTC beta at most `0.15`,
  annualized one-way turnover at most `30.0x`, and equity-buffer breaches zero;
- at least six instruments contribute positively; maximum positive
  instrument, window, week, and top-three-week shares are `0.35`, `0.35`,
  `0.15`, and `0.35`;
- all 130 decisions and 520 directions exist;
- versus each non-cash comparator, pooled return improvement is strictly
  positive, Sharpe improvement at least `0.10`, drawdown no worse, and
  turnover no greater; and
- data completeness, numerical safety, funding accounting, reconciliation,
  and safety checks have zero violations.

There is one candidate and no relatively best fallback. Any gate miss is
`ECONOMIC_FAIL`; source failure and program failure remain separate.

## 11. One-shot and promotion boundary

Design must merge before implementation. Implementation must merge and pass
exact-head CI/Freqtrade review before one temporary explicit workflow input
may authorize one C13A H1–H5 run. It binds exact SHA, run ID, clean checkout,
raw and normalized manifests, independent evidence, and immutable artifacts.

After any source or economic observation, the candidate, universe, MAX
definition, clocks, direction, sizing, costs, comparators, windows, and gates
cannot change. Closeout removes the one-shot input/job. Even an economic pass
authorizes only a separately designed public-data read-only Shadow; it does
not establish execution feasibility and cannot open Paper or Live.

`C13A_DESIGN_FROZEN`

`HISTORICAL_DEVELOPMENT_ONLY`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
