# C6A Historical Metadata Source-Authority Gate V1

## 1. Status and authority

- Stage: `C6A_SOURCE_AUTHORITY_GATE`
- Change type: `DESIGN_ONLY`
- Base main: `c806b41eed36ecf2058a0dec7615aef102751070`
- C6A economic result: `NOT_RUN`
- C6A implementation: `NOT_AUTHORIZED`
- C6B: `CLOSED`
- C5B: `CLOSED_AND_UNTOUCHED`
- Holdout: `CLOSED`
- Paper: `CLOSED`
- Shadow: `CLOSED`
- Live: `FORBIDDEN`

This document preregisters the separate pre-economic source-authority gate required by `C6A_TRANSITION_SAFE_METADATA_CLARIFICATION_V1.md`. It authorizes neither C6A implementation nor economic market-data capture. Its sole purpose is to determine whether complete, public, timestamp-effective instrument metadata can be proven before any economic screen is allowed.

The merged data-authority closeout at `692c3544971801c1de51759ffe5a0cc228cffdc1` remains the historical record for abandoned implementation PR #57. A PASS under this new gate would establish authority only for a future separately reviewed implementation; it would not retroactively validate PR #57 or create an economic result.

## 2. Gate question

The gate answers exactly one question:

> Can retained official-public evidence prove one valid metadata authority state for every modeled transaction timestamp for all four fixed C6A instruments from the warm-up start through the exclusive economic boundary, while using transition-safe intersection only inside the four frozen official adjustment windows?

The gate result is binary:

- `PASS`: every required interval and field is proven with immutable source binding and zero contradiction;
- `FAIL`: any required field, interval, provenance record, completeness proof, or transition condition is missing or contradictory.

There is no partial pass, provisional pass, economic fallback, zero-trade substitution, or manual override.

## 3. Frozen scope

### 3.1 Instruments

- `BTC-USDT`
- `ETH-USDT`
- `BTC-USDT-SWAP`
- `ETH-USDT-SWAP`

### 3.2 Time boundary

- Inclusive authority start: `2023-06-05T00:00:00Z`
- First scored timestamp: `2023-07-03T00:00:00Z`
- Exclusive authority end: `2025-12-29T00:00:00Z`

No source row, announcement, snapshot, derived state, or diagnostic may use economic information at or after the exclusive authority end to modify the frozen C6A signal, threshold, cost, gate, or candidate. Later official material may be used only when it explicitly and immutably documents an earlier metadata change and does not disclose or depend on C6A economic performance.

### 3.3 Required metadata fields

For spot instruments:

- instrument ID and type;
- base and quote currencies;
- `lotSz`;
- `minSz`;
- tick size;
- listing/state information needed to prove tradability;
- inclusive `effective_from`;
- exclusive `effective_to` or explicit open-ended state.

For perpetual instruments:

- instrument ID and type;
- base, quote, and settlement currencies;
- `ctVal`;
- `ctValCcy`;
- `lotSz`;
- `minSz`;
- tick size;
- listing/state information needed to prove tradability;
- inclusive `effective_from`;
- exclusive `effective_to` or explicit open-ended state.

Every field must preserve its original exact decimal or string representation. Binary floating-point inference is forbidden.

## 4. Permitted authority classes

A retained record may derive authority only from the following classes.

### 4.1 Direct official OKX response

An exact response from a public OKX endpoint permitted by the merged C6A contract, including `GET /api/v5/public/instruments`, when the response timestamp and retained bytes prove the state at that time.

A current response proves only its captured state. It may not be projected backward.

### 4.2 Official OKX announcement or specification-change notice

An official OKX publication may prove:

- affected instrument IDs;
- the old and new values;
- an exact effective timestamp; or
- a closed UTC adjustment window when the exact internal switch timestamp is not published.

A notice that omits the before-state, after-state, affected field, exact instrument, or time boundary cannot independently fill an interval.

### 4.3 Exact archived copy of an official OKX response

An archive is eligible only as storage of an exact official OKX response. Each archived item must retain:

- original OKX URL;
- archive retrieval URL;
- archive capture timestamp;
- HTTP status and relevant headers when available;
- raw archived bytes;
- decoded official-response bytes;
- raw-byte SHA-256;
- decoded-byte SHA-256;
- deterministic decoding method;
- proof that the decoded content is an official OKX response rather than archive-generated commentary.

The archive provider is not an independent authority. Missing captures do not prove absence or continuity.

### 4.4 Official downloadable metadata file

An official OKX downloadable file is eligible only if it explicitly contains the required instrument metadata and effective-time semantics. Candles, trades, order books, funding rates, or other economic files cannot be repurposed as instrument-metadata authority.

### 4.5 Forbidden substitutes

The following are forbidden as authority:

- third-party exchange datasets;
- private account responses or exports;
- current account settings;
- exchange SDK defaults;
- Freqtrade market metadata caches;
- inferred values from order size acceptance, trades, candles, prices, funding, or volume;
- undocumented continuity assumptions;
- search-engine snippets;
- screenshots without retained source bytes;
- manually transcribed values without an immutable source object;
- a union of old and new transition states;
- today's metadata projected backward.

## 5. Frozen transition-safe windows

Only the following windows may use `TRANSITION_SAFE_INTERSECTION`:

| Instrument | UTC window | Frozen change |
|---|---|---|
| `ETH-USDT-SWAP` | `[2024-04-18T06:00:00Z, 2024-04-18T08:00:00Z)` | `lotSz`/`minSz` step `1` to `0.1` |
| `BTC-USDT-SWAP` | `[2024-04-25T06:00:00Z, 2024-04-25T08:00:00Z)` | `lotSz`/`minSz` step `1` to `0.1` |
| `ETH-USDT-SWAP` | `[2025-01-09T06:00:00Z, 2025-01-09T10:00:00Z)` | `lotSz`/`minSz` step `0.1` to `0.01` |
| `BTC-USDT-SWAP` | `[2025-01-22T06:00:00Z, 2025-01-22T08:00:00Z)` | `lotSz`/`minSz` step `0.1` to `0.01` |

For each window, the gate must prove all transition-safe prerequisites from the merged clarification, including unchanged identity, currencies, `ctVal`, `ctValCcy`, and tick size; nested exact lot increments; exact before and after states; official UTC window bounds; and validity of every admitted quantity under both states.

No additional transition window may be added during gate execution. Discovery of another relevant transition produces `FAIL_NEW_UNFROZEN_TRANSITION` and requires a new design-only clarification before any rerun.

## 6. Source-discovery protocol

The source-discovery implementation must execute before any C6A candle, mark-price, funding-rate, return, signal, comparator, or strategy-result read.

### 6.1 Frozen query inventory

Before network access, the implementation must commit a machine-readable query inventory containing:

- every official OKX endpoint URL and parameter set to be requested;
- every official OKX announcement category, pagination range, locale, and search term to be scanned;
- exact instrument aliases and legacy names to be checked;
- exact date bounds;
- archive lookup URL templates;
- expected response type and parser version;
- retry, timeout, and rate-limit policy.

The inventory SHA-256 is part of the gate result. It may not be broadened after any source content is inspected. A required correction must close the attempt as pre-authority failure and require a new exact-head review.

### 6.2 Announcement-catalog completeness

The implementation must retain a complete pagination transcript for each frozen official OKX announcement catalog surface used. Each page must record:

- requested URL and parameters;
- retrieval timestamp;
- status code;
- raw bytes and SHA-256;
- parsed item IDs, titles, publication timestamps, canonical URLs, and next-page state;
- duplicate and overlap checks;
- terminal-page proof.

Search terms alone are insufficient. The catalog scan must enumerate the frozen date range and relevant announcement categories so that a missing search hit cannot silently imply no change.

### 6.3 Endpoint and archive capture

Every direct or archived response must be retained before parsing. Derived metadata states may reference only retained source objects already present in the immutable source inventory.

Redirects, compressed responses, character encoding, and archive wrappers must be resolved deterministically and recorded. Any anti-bot page, truncated response, unstable dynamic content, locale mismatch, or undecodable object fails that source object.

### 6.4 No economic access

The gate implementation must contain explicit guards that reject requests to:

- candle endpoints;
- mark-price candle endpoints;
- funding-rate history endpoints;
- trade-history downloads;
- account or private endpoints;
- any timestamp at or after `2025-12-29T00:00:00Z` except later-published official notices that explicitly document an earlier metadata state.

A guard violation ends the gate as `FAIL_FORBIDDEN_DATA_ACCESS`.

## 7. Required canonical outputs

A gate run must produce all of the following in one immutable artifact.

### 7.1 `query_inventory.json`

The pre-network frozen request and catalog inventory, including its own SHA-256.

### 7.2 `source_inventory.json`

One record per retained source object with:

- stable source ID;
- authority class;
- canonical official URL;
- retrieval/archive URL when different;
- publication, response, capture, and retrieval timestamps where applicable;
- HTTP metadata;
- raw and decoded paths;
- byte sizes;
- SHA-256 hashes;
- parser and decoding versions;
- eligibility status and rejection reason.

### 7.3 `announcement_catalog.json`

The complete deduplicated official announcement inventory for the frozen scan, with page provenance and classification of every potentially relevant item.

### 7.4 `metadata_states.json`

Canonical exact-decimal states for each instrument. Each record must include:

- all required fields;
- `authority_mode` equal to `EXACT_EFFECTIVE_STATE` or `TRANSITION_SAFE_INTERSECTION`;
- inclusive `effective_from`;
- exclusive `effective_to`;
- source IDs proving each field and boundary;
- derivation rule ID;
- contradiction status.

### 7.5 `transition_proofs.json`

For each frozen transition:

- old and new source IDs;
- official window source ID;
- exact old/new values;
- unchanged-field proof;
- exact nested-increment proof using decimal or rational arithmetic;
- derived `transition_lot` and `transition_min`;
- exhaustive generated boundary cases proving every admitted quantity rule is valid under both states.

### 7.6 `coverage_matrix.json`

For each instrument and each canonical interval:

- interval start/end;
- governing metadata state ID;
- all required fields present;
- source coverage status;
- overlap count;
- contradiction count;
- uncovered duration;
- whether any modeled transaction timestamp class can fall outside authority.

### 7.7 `gate_result.json`

The only authoritative decision file, containing:

- exact source commit SHA;
- exact PR merge ref when applicable;
- query-inventory SHA-256;
- all source and output hashes;
- total source objects;
- total eligible objects;
- catalog pages and items scanned;
- state and interval counts;
- uncovered interval count and duration;
- ambiguous interval count;
- contradiction count;
- unsupported projection count;
- forbidden-access count;
- newly discovered transition count;
- result `PASS` or one exact `FAIL_*` reason;
- `implementation_authorized = false` regardless of result.

### 7.8 `manifest.json`

A complete recursive file manifest containing path, byte size, and SHA-256 for every retained input, transcript, derived output, log, and report.

### 7.9 `independent_review.json`

A physically separate read-only recomputation must independently verify source hashes, exact-decimal parsing, interval coverage, transition arithmetic, contradictions, manifest completeness, and the final decision without importing the production gate decision function.

## 8. Exact PASS conditions

The gate is `PASS` only when all conditions hold:

1. the frozen query inventory existed before network access and matches its recorded hash;
2. all network requests are permitted metadata/announcement/archive requests;
3. all four instruments have complete authority coverage over `[2023-06-05T00:00:00Z, 2025-12-29T00:00:00Z)`;
4. every required metadata field is proven for every governing interval;
5. every interval boundary is source-supported;
6. there are zero uncovered intervals and zero uncovered duration;
7. there are zero ambiguous or contradictory intervals;
8. there are zero unsupported backward projections;
9. each frozen transition passes every transition-safe proof;
10. no unfrozen relevant transition is discovered;
11. every retained source and output matches the complete manifest;
12. independent recomputation returns the same PASS decision with no errors.

A PASS proves only metadata source authority. It does not authorize implementation merge or economic data access. A later implementation PR must bind itself to the exact merged gate design and exact PASS artifact through a separate review.

## 9. Exact failure taxonomy

The gate must fail closed with one primary reason and may retain secondary diagnostics:

- `FAIL_QUERY_INVENTORY_MISSING_OR_CHANGED`
- `FAIL_FORBIDDEN_DATA_ACCESS`
- `FAIL_SOURCE_BYTES_MISSING`
- `FAIL_SOURCE_HASH_MISMATCH`
- `FAIL_SOURCE_NOT_OFFICIAL_OKX`
- `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`
- `FAIL_ANNOUNCEMENT_CATALOG_INCOMPLETE`
- `FAIL_REQUIRED_FIELD_MISSING`
- `FAIL_INTERVAL_BOUNDARY_UNPROVEN`
- `FAIL_UNCOVERED_INTERVAL`
- `FAIL_AMBIGUOUS_OR_CONTRADICTORY_STATE`
- `FAIL_UNSUPPORTED_BACKWARD_PROJECTION`
- `FAIL_TRANSITION_WINDOW_UNPROVEN`
- `FAIL_TRANSITION_FIELDS_CHANGED`
- `FAIL_TRANSITION_INCREMENT_NOT_NESTED`
- `FAIL_TRANSITION_INTERSECTION_INVALID`
- `FAIL_NEW_UNFROZEN_TRANSITION`
- `FAIL_MANIFEST_INCOMPLETE`
- `FAIL_INDEPENDENT_REVIEW_MISMATCH`

A failed source or request may not be replaced by a weaker authority class after source content has been inspected. Any materially changed source plan requires a new design-only commit and exact-head review before another run.

## 10. Workflow and repository hygiene

Normal implementation validation must use the existing `CI` and `Freqtrade Validation` workflows whenever their path filters apply.

The eventual one-time source-authority execution may use one temporary dedicated workflow only because it requires controlled public-source capture and immutable artifact retention. That workflow must:

- be added only after implementation code and ordinary validation pass;
- run exactly once after exact-head independent authorization;
- contain no economic endpoint or private credential;
- upload the complete source-authority artifact even on failure;
- be deleted after the result is frozen;
- leave durable provenance in the exact workflow commit, run logs, artifact digest, and a merged result document;
- not be reused for implementation or economic screening.

No series of small temporary workflows is permitted.

## 11. Claim boundary

This document does not claim that sufficient historical metadata exists. It only freezes how that question must be tested.

It does not authorize:

- C6A implementation;
- candle, mark-price, or funding-history access;
- an economic screen;
- strategy selection;
- C6B or C5B access;
- account access;
- paper or shadow execution;
- any live behavior.

`C6A_SOURCE_AUTHORITY_GATE_DESIGN_ONLY`

`C6A_ECONOMIC_RESULT_NOT_RUN`

`C6A_IMPLEMENTATION_NOT_AUTHORIZED`

`C6B_CLOSED`

`C5B_CLOSED_AND_UNTOUCHED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
