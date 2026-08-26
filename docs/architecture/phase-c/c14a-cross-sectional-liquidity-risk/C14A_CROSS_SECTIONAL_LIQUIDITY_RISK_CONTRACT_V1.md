# C14A Cross-Sectional Liquidity Risk — Contract V1

## 1. Status and authority

- Stage: `C14A`
- Change type: `DESIGN_AND_PROGRAM_GUARD`
- Required design base: `9fad58a768517a63eedbe5a11a4cbad16e3dee7a`
- Selectable candidate count: `1`
- Historical economic result: `NOT_RUN`
- Data status: `HISTORICAL_DEVELOPMENT_ONLY`
- Execution feasibility: `NOT_ESTABLISHED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This contract freezes one new historical candidate before any C14A volume,
liquidity score, rank, position, PnL, return, comparator, or economic gate is
computed. It authorizes no authenticated request, account access, order,
Paper or Shadow side effect, or Live path.

## 2. Hypothesis and economic mechanism

C14A tests one proposition:

> Among eight fixed large OKX USDT perpetual swaps, instruments with greater
> price impact per unit of quote turnover over the preceding 28 complete UTC
> days earn a liquidity-risk premium relative to the most liquid instruments,
> after conservative costs, actual funding, and market-neutral sizing.

The score is the Amihud illiquidity measure: mean daily absolute log return
divided by same-day quote-currency volume. Zhang and Li, “Liquidity risk and
expected cryptocurrency returns,” report a negative cross-sectional relation
between liquidity and subsequent cryptocurrency returns using the Amihud
measure. Their robustness result motivates a falsifiable test; their absence
of a significant time-series relation for three leading cryptocurrencies is
also an explicit reason C14A may fail:

- <https://doi.org/10.1002/ijfe.2431>

The official OKX candle schema supplies `volCcyQuote` alongside confirmed
OHLC data:

- <https://www.okx.com/docs-v5/en/#rest-api-market-data-get-candlesticks-history>

Neither source proves that this implementation will pass.

## 3. Structural separation and complete history disclosure

C14A is not a rescue or retune of an exposed candidate:

- it does not use price direction, cumulative momentum, breakout, pullback,
  residual return, maximum return, skewness, funding rank, basis, open
  interest, volatility rank, or a regime filter as its selectable signal;
- unlike C3A/C4A/C8A/C10A/C13A, the signal cannot be computed without quote
  turnover;
- unlike C5A/C7A/C9A/C12A, funding and derivatives state never select a side;
  realized funding is only an unavoidable cash flow;
- unlike C11A, it estimates no beta or residual variance;
- C14A ranks price impact per unit of volume, while two fixed non-selectable
  comparators separately rank the numerator and denominator. C14A must beat
  both, so ordinary volatility or low-volume exposure cannot masquerade as a
  liquidity-risk premium.

The machine history is
`implementation/config/phase_c_research_program_registry_v5.json`. It records
`628` prior observed economic trials: C13A adds one valid `ECONOMIC_FAIL`;
C10A and C12A remain zero-trial program/data failures. Nothing is erased,
renamed, relabelled, or rerun.

C14A is prospective economic trial `629`:

```text
bonferroni_adjusted_psr = max(0, 1 - 629 * (1 - raw_weekly_PSR))
```

Eligibility requires raw and adjusted PSR of at least `0.95`. This declared
count is only a lower bound and does not claim to correct untracked human
discretion. No C14A score, rank, trade, PnL, return, Sharpe, PSR, comparator,
or H1–H5 gate was computed or inspected during this design.

## 4. Fixed universe, windows, and clocks

The exact universe is fixed before C14A data access:

1. `BTC-USDT-SWAP`
2. `ETH-USDT-SWAP`
3. `SOL-USDT-SWAP`
4. `BCH-USDT-SWAP`
5. `DOGE-USDT-SWAP`
6. `XRP-USDT-SWAP`
7. `LTC-USDT-SWAP`
8. `LINK-USDT-SWAP`

There is no volume-based universe selection, listing substitution, asset
removal, survivorship repair, or adaptive eligibility. Missing coverage is
`DATA_FAILURE`.

| Window | Start inclusive | End exclusive | Decisions |
|---|---|---|---:|
| H1 | `2024-01-01T00:00:00Z` | `2024-07-01T00:00:00Z` | 26 |
| H2 | `2024-07-01T00:00:00Z` | `2024-12-30T00:00:00Z` | 26 |
| H3 | `2024-12-30T00:00:00Z` | `2025-06-30T00:00:00Z` | 26 |
| H4 | `2025-06-30T00:00:00Z` | `2025-12-29T00:00:00Z` | 26 |
| H5 | `2025-12-29T00:00:00Z` | `2026-06-29T00:00:00Z` | 26 |

Every decision executes at Monday `00:00:00Z`; its signal cutoff is the
preceding Sunday `00:00:00Z`, leaving a fixed 24-hour gap. The 28 signal days
are complete UTC days ending at that cutoff. Daily log return uses the
confirmed `00:00Z` open to the next confirmed `00:00Z` open. Daily quote
volume is the sum of the exact 24 confirmed hourly `volCcyQuote` values over
the same half-open UTC day. The first required trade source timestamp is
`2023-12-03T00:00:00Z`.

Each window begins with `1000 USDT`, cash, and no inherited position. Its last
position closes at the exclusive Monday boundary. There are exactly `130`
decisions and `520` non-flat instrument directions.

## 5. Official-public source custody

Only reviewed public OKX sources are allowed:

1. confirmed one-hour trade candles from
   `GET /api/v5/market/history-candles`, including exact `volCcyQuote`;
2. one-hour historical mark-price candles; and
3. official OKX monthly funding archives with actual `fundingTime`.

Every raw response must be persisted before parsing with requested/final URL,
status, media type, byte length, capture time, retry history, and SHA-256.
Non-HTTPS, unreviewed host, redirect path/query drift, overwrite, path escape,
unmanifested bytes, HTML, malformed JSON/CSV, or cursor non-progress fails
closed.

Trade and mark rows must be finite, unique, strictly increasing, complete,
hour-grid aligned, geometrically valid, and confirmed where the schema
supplies confirmation. Every hourly `volCcyQuote` must be finite and strictly
positive. It is quote-currency turnover and may not be reconstructed from
base volume, current contract metadata, price, account data, or another
venue. Funding must preserve actual official timestamps and may not be
snapped. Duplicate, unordered, missing-predecessor, or unaccounted funding
settlements fail closed.

## 6. Frozen signal and portfolio

For each instrument `i` and each of the 28 complete signal days `d`:

```text
r[i,d] = ln(open[i,d+1] / open[i,d])
qv[i,d] = sum(volCcyQuote for the exact 24 hourly candles in day d)
ILLIQ[i] = mean(abs(r[i,d]) / qv[i,d] for d=1..28)
```

All arithmetic uses `Decimal`. No scaling by circulating supply, contract
size, market capitalization, price level, current metadata, or cross-venue
volume is allowed. There is no winsorization, clipping, log transform of the
score, minimum-volume filter, threshold, regime rule, optimizer, stop,
take-profit, early exit, or intraweek rebalance.

Rank descending by `(ILLIQ, inverse instrument_id)` so the implemented stable
order is score descending then instrument ID ascending. Long the two highest
ILLIQ instruments and short the two lowest. The middle four are flat.

Gross notional is `0.50` of current pre-rebalance equity: `0.25` long and
`0.25` short, four positions of absolute notional `0.125`. Equity divided by
gross notional must remain at least `1.25`; breach forces the next complete
hourly close and makes the candidate ineligible.

## 7. Execution, funding, costs, and accounting

Entry and exit use the exact confirmed Monday `00:00Z` trade-candle open.
Every changed absolute notional pays a one-side all-in cost; unchanged
quantities pay none. Costs are frozen at `1.0x=0.0015`, `1.5x=0.00225`, and
`2.0x=0.0030`.

Hourly equity uses mark prices. Actual funding is applied at exact
`fundingTime` to the position carried at that instant. At exact Monday
`00:00Z`, funding is applied before rebalance. A delayed official settlement
is not shifted to the hour. Price PnL, funding PnL, costs, realized/unrealized
PnL, cash, equity, quantities, and changed notional must reconcile within
`1e-10` USDT or fail as `PROGRAM_FAILURE`.

## 8. Fixed non-selectable comparators

All comparators use the same universe, clocks, sizing, execution, funding,
costs, and accounting. None can be selected as a fallback.

- `CashComparator`: always flat.
- `MeanAbsoluteReturnRankComparator`: long the two highest and short the two
  lowest 28-day mean absolute daily log returns. It isolates the Amihud
  numerator.
- `InverseQuoteVolumeRankComparator`: long the two lowest and short the two
  highest 28-day mean daily quote volumes. It isolates the denominator and
  ordinary low-volume exposure.

C14A must beat both active comparators on aggregate return and annualized
weekly Sharpe, be no worse on maximum drawdown, and have no greater turnover.

## 9. Frozen economic gates

C14A is `ECONOMIC_PASS` only if every condition is true at `1.0x` unless a
cost stress is named:

1. all five windows have positive net return;
2. pooled return is positive at `1.0x` and `1.5x`, and non-negative at `2.0x`;
3. annualized weekly Sharpe is at least `1.00`;
4. raw weekly PSR and 629-trial Bonferroni-adjusted PSR are each at least
   `0.95`;
5. every window's maximum drawdown is at most `0.15`;
6. pooled absolute BTC beta is at most `0.15`;
7. annualized one-way turnover is at most `30.0`;
8. at least six of eight instrument net contributions are positive;
9. maximum positive-PnL share is at most `0.35` by instrument and window,
   `0.15` by week, and `0.35` for the top three positive weeks combined;
10. C14A exceeds each active comparator's return, exceeds each comparator's
    Sharpe by at least `0.10`, has no worse drawdown, and no greater turnover;
11. there are exactly `130` decisions, `520` non-flat directions, and zero
    equity-buffer breaches.

There is one candidate and no relatively best fallback. One failed gate makes
the result `ECONOMIC_FAIL`.

## 10. Independent recomputation and final classification

The production replay and a physically separate independent implementation
must both recompute signals, ranks, quantities, funding, costs, ledger,
comparators, metrics, concentration, beta, PSR, and every gate from the
sealed normalized package. The independent path may share schemas and input
files but may not import production signal, replay, ledger, gate, or finalizer
code. Any mismatch is `PROGRAM_FAILURE`.

Classification is exactly one of:

- `ECONOMIC_PASS`: custody and independent recomputation pass and every gate
  passes;
- `ECONOMIC_FAIL`: valid custody/recomputation but at least one gate fails;
- `DATA_FAILURE`: official-public coverage or normalization fails closed;
- `PROGRAM_FAILURE`: execution, accounting, hash, schema, or independent
  recomputation fails.

Only `ECONOMIC_PASS` permits a later, separate public-data read-only Shadow
design. It does not itself open Shadow, Paper, or Live.

## 11. Anti-retuning and safety closure

After the first C14A H1–H5 economic result is exposed, no one may change its
universe, lookback, gap, score, rank, sizing, costs, clocks, comparators,
windows, or gates and rerun C14A. No best window, instrument subset, or cost
case may be selected. A new candidate must be structurally distinct,
separately preregistered, and counted as another program trial.

The implementation and authority workflow must state:

- `authenticated=false`;
- `contains_account_data=false`;
- `contains_order_data=false`;
- `paper_state=PAPER_CLOSED` and no Paper side effects;
- `shadow_state=SHADOW_CLOSED` and no Shadow side effects;
- `live_state=LIVE_FORBIDDEN`.

The AI may only produce structured research evidence. Deterministic guards
fail to HOLD/CLOSED. No private API, credential, account, order, withdrawal,
Paper balance, Shadow action, Live action, or real-funds effect is authorized.

`C14A_DESIGN_ONLY`

`C14A_ECONOMIC_RESULT_NOT_RUN`

`RETUNING_NOT_AUTHORIZED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
