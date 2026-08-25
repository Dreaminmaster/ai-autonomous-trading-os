# C12A Fixed-Maturity Basis Carry — Contract V1

## 1. Status and authority

- Stage: `C12A`
- Change type: `DESIGN_AND_PROGRAM_GUARD`
- Required design base: `2b561e86cb0f708559e0821db1ba9bf0210b817c`
- Selectable candidate count: `1`
- Historical economic result: `NOT_RUN`
- Data status: `HISTORICAL_DEVELOPMENT_ONLY`
- Execution-feasibility evidence: `NOT_ESTABLISHED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This contract prospectively freezes one historical economic screen. It does
not authorize authenticated requests, account access, orders, Paper or Shadow
side effects, or a Live path. Public-data custody and accounting components
may be reused; prior Phase C outcomes may not become C12A features or tuning
inputs.

## 2. Hypothesis and structural separation

C12A tests one falsifiable proposition:

> A delta-neutral long-spot/short-fixed-maturity-futures position in BTC-USDT
> and ETH-USDT earns positive net carry when its entry futures premium,
> normalized by the combined two-leg notional, strictly exceeds twice the
> complete conservative round-trip cost, after marking both legs and closing
> one hour before expiry.

The mechanism is contractual convergence of a dated future toward spot, not a
cross-sectional anomaly or perpetual-swap funding forecast. The candidate has
no optimizer, rank, selected universe, model, regime, LLM, or learned weight:

- C6A, C7A, and C9A used perpetual swaps and realized funding; C12A uses fixed
  quarterly futures and has no funding cash flow.
- C5A used derivatives crowding variables; C12A uses only contemporaneous
  spot/futures prices and time to a predeclared expiry.
- C8A and C10A used momentum; C3A used reversal; C11A used idiosyncratic
  volatility. C12A uses none of those signals.
- The two assets, ten expiries, decision clocks, cost threshold, and sizing are
  fixed before any C12A basis, return, comparator, or gate is computed.

The economic mechanism is consistent with the BIS working paper “Crypto
carry” and OKX's institutional description of cash-and-carry basis trading:

- <https://www.bis.org/publ/work1087.htm>
- <https://www.okx.com/learn/basis-trading-report>

Those references motivate the mechanism only. They do not establish that this
exact public-data OKX implementation will pass.

## 3. Pre-design source-feasibility probe

Before this freeze, non-economic source probes inspected the official OKX
historical-data portal and small archive samples only to answer whether a
strict implementation was possible. The probes established:

1. settled quarterly futures are not reliably retrievable through the current
   `history-candles` endpoint;
2. the official monthly `FUTURES` chain trade archives (`module=1`) contain
   timestamped public prints and exact instrument identifiers for the fixed
   BTC-USDT and ETH-USDT contracts below;
3. the tested official derivative candlestick archives (`module=2`) marked
   every sampled row `confirm=0`, so C12A rejects that source rather than
   reinterpreting an unconfirmed flag; and
4. exactly nineteen distinct contract-holding months per asset family cover
   every frozen signal, entry, carried interval, and exit, and form a feasible
   finite capture set.

No C12A entry basis, return, PnL, Sharpe, PSR, comparator, asset subset, window
subset, or gate was computed or inspected. File sizes and schema presence are
not economic observations. This disclosure is part of the frozen authority.

## 4. Multiple-testing boundary

The machine-readable authority is
`implementation/config/phase_c_research_program_registry_v3.json`.

Before C12A, Phase C has a declared lower bound of `627` observed economic
trials. C10A remains a zero-trial `PROGRAM_FAILURE`; C11A contributes exactly
one observed `ECONOMIC_FAIL`. Neither may be relabelled or rerun.

C12A is prospective economic trial `628`. For one-sided weekly PSR versus
zero:

```text
bonferroni_adjusted_psr = max(0, 1 - 628 * (1 - PSR))
```

Eligibility requires raw `PSR >= 0.95` and adjusted `PSR >= 0.95`. The count
is a lower bound and does not claim correction for all unpublished human
discretion. Removing a prior trial, changing an observed result, or changing
the trial count after inspection is `PROGRAM_FAILURE`.

## 5. Frozen windows, instruments, and clocks

The five independent windows are:

| Window | Start inclusive | End exclusive | Expiries |
|---|---|---|---|
| H1 | `2024-01-01T00:00:00Z` | `2024-07-01T00:00:00Z` | `240329`, `240628` |
| H2 | `2024-07-01T00:00:00Z` | `2024-12-30T00:00:00Z` | `240927`, `241227` |
| H3 | `2024-12-30T00:00:00Z` | `2025-06-30T00:00:00Z` | `250328`, `250627` |
| H4 | `2025-06-30T00:00:00Z` | `2025-12-29T00:00:00Z` | `250926`, `251226` |
| H5 | `2025-12-29T00:00:00Z` | `2026-06-29T00:00:00Z` | `260327`, `260626` |

Each expiry is `08:00:00Z`. For each suffix, the exact instruments are
`BTC-USDT-<suffix>` and `ETH-USDT-<suffix>`, paired with spot `BTC-USDT` and
`ETH-USDT`. This produces exactly twenty asset-contract decisions.

For expiry `T`:

```text
entry_timestamp = T - 28 days
signal_cutoff = entry_timestamp - 1 hour
exit_timestamp = T - 1 hour
```

The signal uses only the last complete hour ending at `signal_cutoff`.
Transactions use data beginning at their separate entry or exit timestamp.
No position is held into delivery. A window begins with `1000 USDT`, no
position, and no state carried from another window.

Spot capture begins at `2023-12-31T23:00:00Z`, exactly one completed hour
before H1, so all 130 BTC benchmark weekly returns are independently defined.

## 6. Official-public data custody

Only these official public OKX sources are allowed:

1. confirmed one-hour spot trade candles for `BTC-USDT` and `ETH-USDT`; and
2. official monthly historical `FUTURES` chain trade archives for families
   `BTC-USDT` and `ETH-USDT`, filtered to the twenty exact contract IDs.

The official references are the OKX
[historical-data portal](https://www.okx.com/historical-data) and
[API guide](https://www.okx.com/docs-v5/en/). Archive discovery must be bound
to the reviewed official portal/API response. Every requested URL and final
URL, HTTP status, media type, byte length, capture time, retry, and SHA-256 is
persisted. Redirects must remain in the reviewed official host allowlist and
must not drift path or query semantics. Raw bytes are atomically persisted
before parsing; overwrite, path escape, silent partial reuse, HTML bodies, and
unmanifested files fail closed.

Spot candles must be UTC, confirmed, finite, unique, strictly increasing,
hour-grid aligned, geometrically valid, and complete over required hours.
Futures CSV rows must contain the exact expected header, exact instrument ID,
unique trade ID, side in the official vocabulary, positive finite price and
size, and parseable UTC millisecond timestamp. Rows are normalized to UTC and
sorted only after preserving the raw file. Duplicate IDs, contradictory
duplicates, unexpected instruments in a filtered output, timestamps outside
the archive's official `UTC+08:00` calendar month, missing required entry/exit
intervals, or malformed values fail closed.

For every futures contract, derive an hourly last-trade mark from all prints in
each closed UTC hour. Every carried hour from entry up to the exit requires at
least one print; there is no forward fill. Entry and exit execution use the
first eligible trade at or after the frozen timestamp and no later than five
minutes afterward. Absence fails closed. Spot execution uses the corresponding
confirmed hourly candle open; its exact timestamp must equal the frozen
transaction time. No interpolation, alternate venue, perpetual proxy,
replacement contract, or settlement-price substitution is permitted.

The exact official archive basename is
`<family>-futureschain-trades-<YYYY-MM>.zip` with one same-basename CSV member.
Compressed transport is capped by the shared 64 MiB limit; the single CSV is
capped at 256 MiB and a 200:1 expansion ratio. The source-feasibility sample
that motivated these prospective caps was 12.64 MB compressed and 83,579,382
bytes expanded; no signal or economic field was computed from it.

The capture and recursive manifests must state:

```text
authenticated = false
contains_account_data = false
contains_order_data = false
paper_side_effect = false
shadow_side_effect = false
live_state = LIVE_FORBIDDEN
```

## 7. Frozen signal and entry rule

At the signal cutoff, let `S` be the confirmed spot candle close for the hour
ending at the cutoff and `F` the futures last-trade mark for that same closed
hour. Define the combined-notional-normalized premium:

```text
normalized_basis = (F - S) / (F + S)
```

This denominator is the two-leg gross notional for one unit of base asset. It
is intentionally not the conventional `(F-S)/S` quote. The conservative
`2.0x` one-side all-in rate used only for entry gating is `c = 0.0030`;
therefore the frozen entry threshold is:

```text
2 * complete_round_trip_cost_on_combined_notional = 4 * c = 0.0120
enter iff normalized_basis > 0.0120
```

Equality does not enter. Negative, zero, missing, stale, or non-finite basis
does not enter. There is no annualization, interest-rate adjustment, forecast,
relative ranking, asset selection, threshold alternative, early exit, stop,
take-profit, or re-entry.

## 8. Sizing, ledger, and costs

Each asset receives a fixed sleeve equal to `0.50` of that window's current
pre-entry equity. At actual entry prices `S_entry` and `F_entry`, with the
frozen worst-case `2.0x` cost reserve `c = 0.0030`, base quantity is:

```text
q = sleeve_equity / ((S_entry + F_entry) * (1 + c))
spot_quantity = +q
futures_quantity = -q
```

The two base quantities must match within `1e-10`. Initial total gross across
both sleeves may not exceed `1.00 * equity`. Cash cannot be negative. Equity
allocated as futures collateral divided by absolute futures notional must
remain at least `0.25`; any breach makes the candidate ineligible and closes
the position at the next available frozen hourly mark with costs. There is no
leverage expansion, borrowing credit, rehypothecation, funding payment,
delivery, liquidation benefit, rebate, or interest on idle cash.

At hourly marks:

```text
price_pnl = q * (spot_mark_t - spot_mark_previous)
          - q * (futures_mark_t - futures_mark_previous)
```

Each of the four transactions—spot entry, futures entry, spot exit, futures
exit—pays its leg's absolute notional times the one-side all-in cost. Costs are
replayed independently at `1.0x = 0.0015`, expected `1.5x = 0.00225`, and
stress `2.0x = 0.0030`; the entry decision always uses the frozen `2.0x`
threshold and cannot change between cells. Sizing also reserves `2.0x`, so
entry cash is non-negative in every cost cell and quantities cannot grow in a
cheaper cell. Exit occurs one hour before expiry even when the basis remains
open.

Weekly returns include zero buckets and all mark-to-market PnL. Contract,
asset, window, week, price, and cost contributions must reconcile within
`1e-10 USDT`. Non-positive equity, missing marks, hedge mismatch, negative
cash, non-finite state, or unreconciled PnL fails closed.

Annualized one-way turnover is frozen as one half of total absolute entry and
exit notional across both legs, divided by mean weekly equity, multiplied by
`52 / observed_week_count`. It is not a netted notional measure.

## 9. Fixed non-selectable comparators

Every window and cost cell computes:

1. `CashComparator`: cash only;
2. `AlwaysEnterQuarterlyBasisComparator`: identical instruments, clocks,
   sizing, ledger, and costs, but enters all twenty asset-contracts regardless
   of the frozen basis threshold; and
3. `SpotOnlyQuarterlyHoldComparator`: on every candidate entry, holds the same
   `q` of spot over the same effective interval (including a candidate margin-
   buffer forced exit), retains the unused futures allocation as cash, and pays
   identical spot-leg costs, but has no futures position.

Comparators are never selectable or promotable. The first isolates absolute
edge, the second isolates the threshold's value, and the third exposes any
remaining directional spot contribution.

## 10. Evidence and independent recomputation

The production replay and a physically separate implementation must
independently recompute archive filtering, hourly marks, signals, decisions,
execution rows, exact base hedge, all three cost cells, comparators, ledger,
weekly paths, statistics, attribution, every gate, and every manifest hash
from primitive normalized data. Independent code may not import production
capture normalization, signal, replay, ledger, gate, or finalizer modules.
Any mismatch above absolute and relative `1e-10` is `PROGRAM_FAILURE`.

The 130 weekly buckets span H1-H5 and include zeros. Annualized Sharpe uses
sample standard deviation (`ddof=1`); PSR uses the frozen non-normality
correction. BTC beta uses the same weekly clock and confirmed BTC-USDT spot
returns. The evidence package must distinguish `DATA_FAILURE`,
`PROGRAM_FAILURE`, and a valid economic result.

C12A is `HISTORICAL_ECONOMIC_PASS` only if every frozen gate passes:

- all five window returns and expected-cost pooled return are strictly
  positive; the `1.0x` pooled return is strictly positive and `2.0x` is
  non-negative;
- annualized weekly Sharpe is at least `1.00`, raw PSR at least `0.95`, and
  Bonferroni-adjusted PSR over 628 trials at least `0.95`;
- every window drawdown is at most `0.15`, absolute BTC beta at most `0.10`,
  annualized one-way turnover at most `6.0x`, and margin-buffer breaches and
  base-hedge mismatches equal zero;
- all twenty decisions exist, at least ten asset-contracts enter, every window
  has at least one entry, and both assets contribute positively;
- maximum positive asset, window, contract, and week PnL shares are `0.70`,
  `0.35`, `0.25`, and `0.25`; top-three positive-week share is at most `0.50`;
- versus `AlwaysEnterQuarterlyBasisComparator`, pooled return and Sharpe
  improvements are strictly positive, drawdown is no worse, and turnover is
  no greater; and
- missing decisions, missing hours, delayed execution, non-positive equity,
  invalid marks, reconciliation errors, and safety-boundary violations are
  all zero.

No relatively best ineligible result, comparator, cost cell, asset subset,
contract subset, or window subset may be promoted. A valid gate miss is
`ECONOMIC_FAIL`, not a program or data failure.

## 11. One-shot and promotion boundary

After design merge, implementation merge, exact-head CI, tests, secret scan,
and independent review, one temporary explicit workflow input/job may
authorize exactly one C12A H1-H5 run. It binds requested and observed SHA,
run ID/attempt, clean checkout, source/evidence manifests, and immutable
artifact. It may not be retriggered, tuned, narrowed, or relabelled after any
economic inspection.

A closeout removes the temporary input/job and records exact commit, run, job,
artifact, digest, classification, tests, failed gates, and safety state. Even
a historical pass establishes neither execution feasibility nor forward edge.
It permits only a separately designed public-data read-only Shadow. Live
remains forbidden without independent security work and explicit user
authorization.

`C12A_DESIGN_FROZEN`

`HISTORICAL_DEVELOPMENT_ONLY`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
