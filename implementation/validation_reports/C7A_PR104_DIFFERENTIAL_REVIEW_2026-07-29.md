# C7A PR #104 Differential Security Review

## Executive Summary

| Severity | Unresolved | Resolved during review |
|---|---:|---:|
| Critical | 0 | 0 |
| High | 0 | 1 |
| Medium | 0 | 0 |
| Low | 0 | 0 |

**Overall residual risk:** Low

**Recommendation:** Conditional approval after exact-head CI and Freqtrade Validation
succeed.

**Base:** `3432d34e396001a39400b865ba60e39ea7e2ae6d`

Key review outcomes:

- The second authoritative H1-H5 run `30432931354` failed during capture, before its
  producer and independent economic recomputation ran.
- Artifact `8716416451`, SHA-256
  `b736636182ad8eb5e309d078bffb5bd10f9eb0d21609f956aaf7164f4a7d5a45`, retains
  the public source bytes that caused the failure.
- Official ETH funding history contains settlement-completion timestamps one or two
  seconds after the nominal hour. The maximum observed interval is `28,802` seconds.
- Capture now permits at most the documented one-minute completion delay, while
  preserving each source timestamp and rejecting `60.001` seconds of excess.
- Review found and fixed a second, high-severity implementation defect: both replay
  implementations would reject or omit every non-hour settlement after capture
  accepted it.
- No window, strategy rule, cost, comparator, gate, or threshold changed.
- No authenticated, account, order, Paper, Shadow, or Live surface is introduced.

## Failure Evidence and Source Characterization

The exact failing classification was:

```text
DATA_FAILURE: funding settlement coverage gap exceeds eight hours: ETH-USDT-SWAP
```

The capture step failed and the economic step was skipped. No authoritative economic
result was observed from run `30432931354`.

All 31 retained official monthly funding archives per instrument were independently
parsed from the failed-run artifact:

| Instrument | Selected rows | First timestamp | Last timestamp | Maximum gap |
|---|---:|---|---|---:|
| BTC-USDT-SWAP | 2,814 | 2023-12-04T00:00:00Z | 2026-06-28T16:00:00Z | 28,800 s |
| ETH-USDT-SWAP | 2,814 | 2023-12-04T00:00:00Z | 2026-06-28T16:00:00Z | 28,802 s |

ETH contains 24 intervals over exactly eight hours. Their excess is at most two
seconds. Seventy-five retained ETH records have second `01`, one has second `02`, and
there are no duplicates or unordered rows. OKX's official funding documentation says
that actual fee assessment may take up to one minute, so a two-second completion stamp
is source-compatible rather than missing evidence:

- <https://www.okx.com/en-us/help/perps-funding-fee-mechanism>
- <https://www.okx.com/en-us/help/funding-fees-for-perpetual-contracts-faq>

## What Changed

| File | Purpose | Risk and blast radius |
|---|---|---|
| `implementation/src/atos/c7a_historical_capture.py` | Bound coverage tolerance to 60 seconds | High-integrity external-data gate; funding only |
| `implementation/src/atos/c7a_historical_replay.py` | Process exact and post-boundary funding events at actual timestamps | High economic-accounting path |
| `implementation/src/atos/c7a_historical_independent.py` | Independently recompute the same actual-time event semantics | High independent evidence path |
| `implementation/tests/test_c7a_historical_capture.py` | Cover 2-second acceptance and 60.001-second rejection | Direct boundary regression |
| `implementation/tests/test_c7a_historical_replay.py` | Cover causal ordering, predecessor mark, and independent agreement | Direct accounting regression |

The retained timestamp is never snapped, rounded, interpolated, or replaced. Funding
lookbacks continue to select `funding_time < decision_time` using the actual source
timestamp.

## Trust Boundary and Invariants

```text
official-public OKX bytes (untrusted)
  -> immutable raw retention + SHA-256 custody
  -> strict normalization and duplicate/order checks
  -> start-boundary and maximum-gap checks (8h + at most 60s completion)
  -> actual timestamp retained
  -> primary chronological replay
  -> physically separate primitive recomputation
  -> unchanged comparators and economic gates
```

Preserved invariants:

1. The first settlement must still equal the requested inclusive boundary.
2. Funding timestamps remain UTC, unique, and strictly increasing.
3. A gap greater than eight hours plus 60 seconds fails capture.
4. Price candles must remain aligned to exact hours and gap-free.
5. Funding is applied exactly once at its actual timestamp.
6. An exact-hour settlement is applied to the carried position before a modeled trade
   at that same timestamp.
7. A settlement completed after the boundary is applied after that boundary's modeled
   trade, using the last completed one-hour mark candle.
8. Missing predecessor prices or unaccounted scored settlements fail closed.
9. Raw responses, normalized rows, and final evidence remain SHA-256-bound.
10. Live remains forbidden and no private endpoint or side effect is reachable.

## Function Micro-Analysis

### `_assert_complete_funding_interval`

**Purpose:** fail capture when retained public funding evidence is empty, starts late,
is unordered, or has an unexplained coverage gap.

**Inputs and assumptions:** rows have already passed strict funding normalization and
exact interval selection. Timestamps are untrusted public-source values. OKX may stamp
actual assessment up to one minute after the nominal assessment time.

**Change:** the maximum consecutive gap changes from exactly eight hours to eight
hours plus 60 seconds. The check remains an upper bound; it does not assume or synthesize
an eight-hour schedule and therefore retains compatibility with actual 1/2/4/8-hour
schedules.

**Effects:** raises `C7AHistoricalCaptureError` before normalized custody completes.
It performs no network, account, order, or economic action.

**Security analysis:** a malformed allowlisted public source could move a settlement
up to 60 seconds later and thereby change its causal relationship to a decision at the
hour boundary. The source already controls the actual published timestamp and rate;
the mitigation is narrow bounding, immutable raw custody, no timestamp rewriting, and
actual-time replay. A `60.001`-second excess is directly rejected.

### Primary actual-time replay

**Purpose:** account for every scored settlement once while preserving the contract's
same-time funding-before-trade rule.

**Block analysis:**

1. `_parsed_stamp` accepts any timezone-aware funding timestamp; `_stamp` retains the
   exact-hour requirement for prices, decisions, and other grid values.
2. Funding events are bucketed only for efficient iteration. The tuple retains the
   original timestamp, instrument, and rate, and is deterministically sorted.
3. Events exactly equal to the hour boundary are applied before the weekly modeled
   trade.
4. Events later within the hour are applied after that trade.
5. Both cases use the completed mark candle immediately preceding the event. For an
   event at `08:00:02`, this is the candle stamped `07:00:00`.
6. `processed_funding` records the original event timestamp. The final exact-set
   comparison fails if any scored event was omitted or duplicated.

**Effects:** deterministic in-memory equity and audit-row computation only. No I/O or
external state mutation occurs.

### Independent actual-time recomputation

The reviewer continues to import none of the producer, replay, contract, or schedule
modules. Its source parser independently makes hour alignment conditional, builds one
sorted scored-event stream, advances a cursor through each half-open hour, applies
exact-boundary and post-boundary events on opposite sides of the trade, and compares
its complete signals and weekly ledgers to the producer.

The independent path uses an event cursor instead of the producer's hour buckets. A
cursor drift, missing event, duplicate event, unordered source, or ledger difference
causes independent review failure.

## Resolved Finding

### High: accepted second-offset settlements would fail or be omitted in replay

**Pre-fix sequence:**

1. Capture accepts a source-compatible `08:00:02` settlement.
2. The producer's funding parser requires exact-hour alignment and raises an
   implementation failure before economics.
3. If only parsing were relaxed, the hourly `.get(current)` lookup would omit the
   settlement.
4. The final unaccounted-settlement check would then fail. The independent path had
   the same incompatibility.

**Impact:** repeatable denial of the authorized historical evaluation, or incorrect
economic accounting if the final fail-closed check were ever weakened. There is no
fund-loss path because C7A has no execution surface.

**Resolution:** both paths now process original timestamps chronologically. A direct
regression shifts the first scored settlement to two seconds after the opening trade,
proves that the newly opened position receives it, proves use of the predecessor mark,
and requires the physically separate recomputation to match.

## Test and Evidence Coverage

| Behavior | Result |
|---|---|
| 2-second completion stamp accepted | Direct capture assertion |
| Source timestamp preserved | Direct normalized-row assertion |
| 60.001-second excess rejected | Direct capture assertion |
| Exact-hour settlement remains before same-time trade | Baseline-vs-delayed replay assertion |
| Post-boundary settlement applies to new position | Direct PnL assertion |
| Predecessor completed mark is used | Independently calculated expected PnL |
| Every settlement accounted once | Producer exact-set check plus independent recomputation |
| Price hour alignment unchanged | Existing exact-hour and gap tests |
| Real failed-run artifact | 2,814 rows per instrument; full H1-H5 replay and independent review |

Validation completed locally under Python 3.11.15:

- Focused capture and replay suite: `27 passed`.
- Complete ATOS suite: `1260 passed, 7 skipped in 22.26s`.
- Ruff on all changed Python files: passed.
- Secret leakage scan: passed.
- `git diff --check`: passed.

The retained failed-run artifact was also reconstructed read-only through the modified
code. Both instruments passed coverage; all five frozen windows completed producer
and independent replay. This preflight is not authoritative because it is not bound to
a committed checkout/evidence manifest. It showed zero active candidate weeks and a
pooled `ECONOMIC_FAIL`. No result-dependent tuning is authorized or performed. The
next merged-main workflow result is the only final economic verdict.

## Merge Conditions and Next Action

- [x] Preserve exact source timestamps.
- [x] Bound the source-compatible tolerance and test the first rejected value.
- [x] Fix both producer and independent replay paths.
- [x] Prove causal ordering and predecessor-mark accounting.
- [x] Run complete Python 3.11 tests, scoped Ruff, and secret scan.
- [ ] Require exact-head CI and Freqtrade Validation success.
- [ ] Merge only the reviewed exact head.
- [ ] Dispatch one authoritative H1-H5 workflow from the merged main SHA.

An authoritative `ECONOMIC_FAIL` closes C7A Shadow eligibility and must not trigger
retuning or another run of the frozen windows.
