# C7A PR #103 Differential Security Review

## Executive Summary

| Severity | Unresolved | Resolved during review |
|---|---:|---:|
| Critical | 0 | 0 |
| High | 0 | 0 |
| Medium | 0 | 1 |
| Low | 0 | 0 |

**Overall residual risk:** Low

**Recommendation:** Conditional approval after exact-head CI and Freqtrade Validation succeed

**Reviewed head before the review hardening commit:** `eef50867ae4fede8b72373aac9bc2f94fb15f128`
**Base:** `4936e53e2c2b6e90aa037c164ec63f406a87afa1`

Key metrics:

- Files initially changed: 2 of 244 Python/JSON/workflow files.
- Production validation functions changed: 2 (`_exact_decimal`, `_normalize_funding_records`).
- `_exact_decimal` static call sites: 14; only the funding normalizer opts into exponent support.
- Test gaps after review: 0 for the changed behavior and identified denial-of-service boundary.
- Security regressions detected: 0.
- Economic results observed before the fix: 0.

## What Changed

The first post-merge authoritative run `30424874089` failed during capture with
`DATA_FAILURE` before the producer or independent economic recomputation ran. The
retained official OKX January 2024 archive contained this finite value:

```text
BTC-USDT-SWAP,6.77685581E-8,1705075200000
```

The base implementation rejected exponent notation globally. PR #103 scopes exponent
support to funding rates, parses with `Decimal`, emits canonical fixed-point text, and
preserves the default exponent rejection for candles and all other call sites. The
review additionally added bounded input and exponent expansion checks.

| File | Initial lines | Risk | Blast radius |
|---|---:|---|---|
| `implementation/src/atos/c7a_okx_public_data.py` | +11 / -2 | High validation path | 14 helper callers; 1 relaxed caller |
| `implementation/tests/test_c7a_okx_public_data.py` | +41 / -0 | Low | Direct regression coverage |

## Baseline Context and Trust Boundaries

The base helper was introduced by commit `8527b068` (`C7A: add official OKX public
acquisition adapter`). It required trimmed string input, rejected all exponents,
parsed through `Decimal`, rejected non-finite values, and returned non-exponent text.
The exponent ban was not introduced by a CVE or earlier security fix; it was part of
the initial strict adapter.

The relevant trust path is:

```text
official-public OKX HTTP response / historical ZIP (untrusted bytes)
  -> fetch_raw_strict + immutable raw retention
  -> normalize_funding_download / normalize_funding_download_csv
  -> _normalize_funding_records
  -> _exact_decimal(allow_exponent=True)
  -> canonical non-exponent funding series
  -> interval completeness checks
  -> frozen producer + physically separate independent recomputation
```

Core invariants:

1. Raw external bytes remain immutable and SHA-256-addressed before normalization.
2. Only funding rates may use exponent notation; candle prices and volumes retain the
   stricter non-exponent contract.
3. Every normalized rate is a finite `Decimal` rendered as deterministic fixed-point
   text before any replay code sees it.
4. Instrument identity, timestamp validity, uniqueness, ordering, interval coverage,
   and settlement-gap checks remain unchanged.
5. A normalization error stops capture and prevents all economic calculation.

## Function Micro-Analysis: `_exact_decimal`

**Purpose:**

`_exact_decimal` at `c7a_okx_public_data.py:L136-L161` is the common numeric text
boundary for external OKX data. It converts untrusted text into deterministic
fixed-point form while rejecting ambiguity, non-finite values, and unsafe expansion.

**Inputs & Assumptions:**

- `value: Any` originates from an external JSON or CSV field and is untrusted.
- `label: str` is internal diagnostic context, not source-controlled data.
- `positive: bool` is selected by internal callers for price fields.
- `allow_exponent: bool` defaults to `False`; only the funding normalizer sets it.
- The caller expects exact decimal semantics rather than binary floating-point parsing.
- Valid official numeric text fits within 128 input characters.
- A safe fixed-point representation has an adjusted exponent between -128 and 128.

**Outputs & Effects:**

- Returns one canonical fixed-point decimal string.
- Performs no filesystem, network, account, order, or shared-state mutation.
- Raises `C7APublicDataError` on every invalid or unsafe representation.
- Removes insignificant trailing fractional zeros without changing numeric value.

**Block-by-Block Analysis:**

1. `L143-L144` requires a non-empty, trimmed string.
   - **What:** rejects alternate Python types and whitespace variants.
   - **Why here:** type/shape rejection must precede parsing.
   - **Assumption:** OKX represents these fields as strings.
   - **First principles:** deterministic evidence requires one textual input domain.

2. `L145-L146` bounds raw input length.
   - **What:** rejects numeric text longer than 128 characters.
   - **Why here:** prevents expensive parsing before any conversion.
   - **5 Whys:** the bound is needed because archive size limits do not prevent one
     adversarially long field from consuming disproportionate CPU and memory.

3. `L147-L148` preserves the exponent ban unless explicitly enabled.
   - **What:** keeps 13 non-funding call sites on the original strict contract.
   - **Why here:** exponent syntax must be rejected before `Decimal` accepts it.
   - **5 Hows:** scope is controlled through a keyword-only default-false flag, so an
     accidental positional opt-in is impossible.

4. `L149-L152` parses with `Decimal` and maps parse errors to the public-data error.
   - **What:** preserves decimal coefficient and exponent exactly.
   - **Why here:** canonical formatting requires a parsed exact value.
   - **Assumption:** Python `Decimal` is deterministic for the bounded string input.

5. `L153-L155` rejects non-finite values and enforces positivity when required.
   - **What:** blocks NaN, infinities, zero prices, and negative prices.
   - **Why here:** semantic checks require the parsed value.
   - **5 Whys:** a syntactically valid token is not necessarily economically or
     computationally valid.

6. The adjusted-exponent guard before fixed formatting bounds expansion.
   - **What:** rejects values such as `1E+129`, `1E-129`, and `0E-129`.
   - **Why here:** `format(parsed, "f")` can expand compact exponent text enormously.
   - **5 Hows:** checking `Decimal.adjusted()` is constant-space relative to the
     bounded input and happens before allocating the fixed-point output.

7. Fixed-point formatting and zero trimming produce canonical output.
   - **What:** converts `6.77685581E-8` to `0.0000000677685581`.
   - **Why here:** downstream producer and independent recomputation must consume the
     same representation.
   - **Invariant:** the returned text never contains exponent notation.

**Cross-Function Dependencies:**

- Called from trade, mark, selected-interval, and funding normalization paths.
- `_normalize_funding_records` is the only caller with `allow_exponent=True`.
- Canonical output is later parsed by replay `_number` and contract `finite` checks.
- It has no external calls or shared mutable state.
- Its exponent invariant couples capture evidence to both independent economic paths.

## Function Micro-Analysis: `_normalize_funding_records`

**Purpose:**

`_normalize_funding_records` at `c7a_okx_public_data.py:L910-L943` converts either
official REST funding rows or reviewed-schema CSV rows into the single canonical
funding shape. It is the only point where exponent-form funding text is accepted.

**Inputs & Assumptions:**

- `records` is an iterable derived from untrusted official JSON or CSV.
- `instrument` was validated by the public entrypoint.
- Each record must be a mapping with exact instrument, timestamp, and rate fields.
- Settlement timestamps must be unique within this source.
- The function does not assume the source is ordered.
- `_exact_decimal` enforces finite, bounded, canonical numeric output.

**Outputs & Effects:**

- Returns an immutable tuple sorted by funding time.
- Emits rows containing only instrument, canonical UTC timestamp, and canonical rate.
- Raises on empty input, shape drift, instrument mismatch, invalid timestamp,
  duplicate settlement, unsafe numeric value, or non-finite float conversion.
- Performs no external calls or state mutation.

**Block-by-Block Analysis:**

1. The mapping and instrument checks establish row identity before value use.
   - **Why here:** accepting a rate before binding it to the requested instrument could
     cross-contaminate BTC and ETH evidence.
   - **Invariant:** every output row belongs to the requested instrument.

2. `_millis` plus the `seen` set validate positive timestamps and uniqueness.
   - **5 Whys:** duplicate settlements would double-count funding and alter economics,
     so duplicates fail rather than being silently deduplicated.

3. `_exact_decimal(..., allow_exponent=True)` accepts only the required source-format
   variation and immediately removes it from normalized evidence.
   - **First principles:** source syntax and economic value are separate; exact value
     preservation matters, while retaining arbitrary syntax downstream does not.
   - **Invariant:** downstream rows never contain exponent notation.

4. The float-finite check preserves compatibility with downstream float calculations.
   - **5 Hows:** a Decimal that underflows or overflows during float conversion is
     rejected before the frozen strategy consumes it.

5. Non-empty enforcement and sorting establish deterministic output order.
   - **Invariant:** output timestamps are ascending and unique.

**Cross-Function Dependencies:**

- Called by both `normalize_funding_api_payload` and
  `normalize_funding_download_csv`, covering REST and historical archives.
- Historical ZIP input first passes one-member, safe-path, encryption, size, and
  compression-ratio checks in `normalize_funding_download`.
- `capture_funding_downloads` retains raw bytes before normalization, rejects
  cross-file duplicate settlements, and enforces exact interval completeness.
- Producer and independent recomputation receive only the retained normalized series.

## Resolved Finding

### Medium: exponent-to-fixed formatting expansion denial of service

**Attacker model:** a compromised or malformed allowlisted official-public OKX source.
The attacker cannot access accounts or order paths but can control one funding field in
an otherwise valid public archive.

**Pre-review attack sequence:**

1. Supply a compact finite value such as `1E+999999999`.
2. `Decimal` accepts it as finite after exponent support is enabled.
3. Fixed-point formatting attempts to materialize an enormous string.
4. The capture job exhausts memory/CPU before producing a classified evidence result.

**Exploitability:** Hard, because the request host/path is allowlisted and TLS-protected;
it requires an upstream compromise or malformed official archive. The impact is denial
of historical validation, not fund loss or order execution.

**Resolution:** input text is capped at 128 characters and exponent-enabled values are
rejected when `abs(Decimal.adjusted()) > 128`, both before fixed formatting. Regression
tests cover positive, negative, and zero exponent bombs.

## Test Coverage Analysis

| Behavior | Coverage |
|---|---|
| Exact observed API scientific rate | Direct assertion |
| Exact observed ZIP/CSV scientific rate | Direct assertion |
| Canonical fixed-point output | Direct assertion |
| NaN / positive and negative infinity | Parameterized rejection |
| Positive, negative, and zero expansion bombs | Parameterized rejection |
| Oversized decimal input | Direct rejection |
| Candle exponent remains forbidden | Direct rejection |
| Real retained January 2024 archive | 93 rows parsed; observed row matched exactly |

Validation completed locally under Python 3.11.15:

- Focused C7A public-data/capture suite: `55 passed`.
- Complete ATOS suite: `1258 passed, 7 skipped in 20.87s`.
- Ruff: passed.
- Secret leakage scan: passed.
- `git diff --check`: passed.

## Historical Context

- The exponent ban originated in initial C7A adapter commit `8527b068`.
- No access-control, authentication, private API, order, paper, or live check is removed.
- No earlier security removal is reintroduced.
- The frozen H1-H5 windows, costs, strategy, comparators, and economic gates are
  unchanged.

## Recommendations

### Immediate merge conditions

- [x] Bound exponent-to-fixed expansion before formatting.
- [x] Cover the exact observed official value through API and ZIP paths.
- [x] Preserve non-finite and candle exponent rejection.
- [x] Run complete Python 3.11 tests, Ruff, and secret scan.
- [ ] Require exact-head CI and Freqtrade Validation success.

### After merge

- Run the authoritative workflow once from the new main SHA.
- Treat another source/implementation failure independently from economic failure.
- Do not change frozen economic parameters after an economic result is observed.

## Analysis Methodology

**Strategy:** Focused review of a medium repository (244 relevant files) with deep
analysis of all changed validation code and its funding capture/replay call chain.

Techniques applied:

- Base/head diff and commit-history analysis.
- `git blame` and pickaxe history for the removed exponent check.
- Static call-site counting and blast-radius analysis.
- Bottom-up trust-boundary and invariant reconstruction.
- Adversarial upstream-response modeling.
- Synthetic regression tests plus a retained real-source replay.
- Complete test, lint, whitespace, and secret checks.

Limitations:

- CI results for the final review hardening commit were pending when this report was
  written.
- The authoritative economic run must remain post-merge and has not been executed on
  this fix head.

**Confidence:** High for the changed behavior and its direct call chain; medium for the
unexecuted post-merge authoritative capture.
