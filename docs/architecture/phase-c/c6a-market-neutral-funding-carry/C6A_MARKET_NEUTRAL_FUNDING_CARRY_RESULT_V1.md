# C6A Market-Neutral Funding Carry — Data-Authority Closeout V1

## 1. Status

C6A closed before economic evaluation because the frozen historical-instrument-metadata authority could not be satisfied from an exact public OKX source.

- Stage result: `DATA_AUTHORITY_FAILURE`
- Economic screen: `NOT_RUN`
- Economic result: `NOT_AVAILABLE`
- Selected policy: `null`
- C6B confirmation: `CLOSED`
- C5B: `CLOSED_AND_UNTOUCHED`
- Holdout: `CLOSED`
- Paper execution: `CLOSED`
- Shadow execution: `CLOSED`
- Live execution: `FORBIDDEN`

This is not a negative or positive strategy-performance result. No return, Sharpe, PSR, drawdown, turnover, funding-coverage, concentration, comparator, or gate result exists for C6A.

## 2. Exact design authority

- Required merged design main: `071e45218e299367f3bef18832d931df7d278ace`
- Frozen implementation configuration required design SHA: `071e45218e299367f3bef18832d931df7d278ace`
- Normative metadata clarification: `C6A_TERMINAL_AND_METADATA_CLARIFICATION_V1.md`

The merged clarification requires public metadata effective at every modeled transaction timestamp, including instrument type, currencies, `ctVal`, `ctValCcy`, `lotSz`, `minSz`, tick size, inclusive `effective_from`, exclusive `effective_to` or explicit open-ended state, provenance, and SHA-256 binding.

It explicitly forbids projecting a current `GET /api/v5/public/instruments` snapshot backward over the historical interval. If complete historical metadata authority cannot be established, C6A must fail before economic evaluation.

## 3. Required interval and instruments

C6A required complete public authority for:

- `BTC-USDT`
- `ETH-USDT`
- `BTC-USDT-SWAP`
- `ETH-USDT-SWAP`
- download start: `2023-06-05T00:00:00Z`
- scored start: `2023-07-03T00:00:00Z`
- economic boundary, exclusive: `2025-12-29T00:00:00Z`

Every modeled entry, resize, risk exit, and terminal close had to use the quantity and contract-conversion rules effective at that exact timestamp.

## 4. Public-source findings

### 4.1 Funding-rate history is publicly available

OKX's official historical-data catalog states that perpetual funding-rate history is downloadable from March 2022 onward:

- `https://www.okx.com/en-us/historical-data`

The official public API also documents realized funding-rate history with `fundingTime`, `fundingRate`, and `realizedRate`:

- `GET /api/v5/public/funding-rate-history`
- `https://www.okx.com/docs-v5/`

Therefore, funding-history availability alone was not the closing blocker.

### 4.2 Current instrument metadata is not historical authority

The official instruments documentation exposes fields including `ctVal`, `ctValCcy`, `lotSz`, `minSz`, tick size, currencies, listing time, state, and `upcChg`.

However:

- the endpoint describes current instrument information;
- `upcChg` contains upcoming changes and their future effective times;
- it does not provide a complete public history of past values and past effective intervals for the full C6A period.

Official reference:

- `GET /api/v5/public/instruments`
- `https://www.okx.com/docs-v5/`

### 4.3 The official historical-data catalog has no instrument-metadata archive

The official historical-data catalog lists downloadable categories for:

- trade history;
- candlesticks;
- funding rates;
- order books;
- borrowing rates.

It does not expose a historical instrument-specification or timestamp-effective metadata archive covering `ctVal`, `lotSz`, `minSz`, tick size, and currency-conversion changes.

No exact official public source was established that proves complete effective metadata intervals for all four required instruments from `2023-06-05T00:00:00Z` through `2025-12-29T00:00:00Z`.

## 5. Why inference was rejected

The following substitutions were not allowed:

- applying today's `ctVal`, `lotSz`, `minSz`, or tick size to earlier dates;
- assuming no historical changes because no change was observed in a current snapshot;
- reconstructing historical rules from third-party datasets without exact public OKX authority;
- using private account exports or account-specific instrument settings;
- treating uncovered intervals as zero-trade periods;
- weakening the metadata requirement after implementation work had begun.

Any of those choices would change the frozen research contract and could alter feasible quantities, hedge error, costs, turnover, collateral use, funding PnL, and the final selection gate.

## 6. Implementation PR disposition

Implementation PR `#57` explored the complete C6A accounting, simulation, evidence, and independent-review path, but it did not contain an exact non-placeholder source plan satisfying the historical metadata contract.

The implementation is not merged into `main` and is not economic evidence. It remains available in the closed PR history for possible reuse only if a future exact official historical-metadata authority is independently established.

No authoritative C6A economic workflow was created or run. No market-data artifact was accepted as a C6A economic dataset.

## 7. Interpretation

C6A does not show that market-neutral funding carry is unprofitable. It shows that this repository's preregistered C6A test cannot be conducted honestly under its frozen quantity-conversion and timestamp-effective metadata requirements using the official public authority that was established.

Running with current metadata projected backward would produce a precise-looking but unauditable result. Closing the stage before economic evaluation is therefore the required fail-closed outcome.

## 8. Forward boundary

C6A may not be revived by silently changing the metadata semantics or by substituting inferred historical specifications.

A future structurally separate proposal may proceed only after one of the following is prospectively established before implementation or market-data access:

1. an official public OKX archive with complete timestamp-effective instrument specifications for the modeled interval; or
2. a new design whose economics do not require unavailable historical contract/lot conversion states and whose assumptions are frozen before observing results.

This closeout grants no authority for C6B, C5B, holdout access, account access, paper execution, shadow execution, or live execution.

## 9. Final state

`C6A_DATA_AUTHORITY_FAILURE`

`C6A_ECONOMIC_RESULT_NOT_RUN`

`SELECTED_POLICY_NULL`

`C6B_CLOSED`

`C5B_CLOSED_AND_UNTOUCHED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
