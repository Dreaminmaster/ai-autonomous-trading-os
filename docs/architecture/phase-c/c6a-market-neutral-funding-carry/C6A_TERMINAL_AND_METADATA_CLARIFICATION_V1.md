# C6A Terminal Boundary and Historical Metadata Clarification V1

## 1. Normative purpose

This clarification freezes two implementation-critical semantics before any C6A code, market-data access, or economic result. It adds no candidate, parameter, data access, or execution authority.

It supersedes any less-specific wording in the C6A main contract or accounting addendum.

## 2. Final-window terminal liquidation

Each independent 26-week window ends at its exclusive Monday `00:00:00Z` boundary.

For the final boundary only, processing order is:

1. mark carried spot and perpetual positions from the preceding completed marks to the boundary spot and perpetual trade opens;
2. do **not** apply a funding settlement stamped exactly at the exclusive boundary, because that settlement belongs outside the window;
3. record pre-terminal equity;
4. close both spot and perpetual legs at their boundary trade opens;
5. charge both leg transaction costs;
6. record post-terminal equity with zero remaining position.

The final weekly bucket's `end_reference_equity`, the window's `final_equity`, and every window/aggregate return use the post-terminal value. Terminal price movement and terminal fees therefore belong to the final scored week.

For ordinary non-terminal Monday boundaries, the accounting addendum's existing rule remains unchanged: the prior week's end reference is immediately before the new boundary's funding and ordinary rebalance events.

No position, funding entitlement, collateral, fee, or PnL may cross the exclusive boundary.

## 3. Historical instrument metadata authority

Contract and spot quantity conversion must use public metadata that was effective at the modeled transaction timestamp.

Every retained metadata record must include:

- instrument ID and instrument type;
- base and quote/settlement currencies;
- `ctVal`, `ctValCcy`, `lotSz`, `minSz`, and tick size where applicable;
- spot lot size and minimum size;
- an inclusive `effective_from` timestamp;
- an exclusive `effective_to` timestamp or explicit open-ended state;
- public-source provenance and SHA-256 binding.

A metadata record is usable only when:

```text
effective_from <= transaction_time < effective_to
```

or, for an explicitly open-ended record:

```text
effective_from <= transaction_time
```

A current `GET /api/v5/public/instruments` snapshot may validate current schema and overlap, but it must not be silently projected backward over the historical C6A interval.

If public historical metadata cannot establish the effective lot, minimum-size, contract-value, and currency-conversion rules for every modeled transaction, C6A fails before economic evaluation. Private account information, current-account settings, or inferred historical values may not fill the gap.

## 4. Rounding and gate consequence

The deterministic joint-rounding solver must select only quantities valid under the metadata record effective at that exact transaction timestamp. A metadata transition may change feasible quantities and must be retained in evidence.

Any ambiguous interval, overlapping contradictory metadata records, uncovered transaction timestamp, or use of a future-effective record is an evidence failure, not a zero-trade observation.

## 5. Claim and safety boundary

This clarification does not authorize implementation, data download, an economic run, C6B, C5B access, account access, paper execution, shadow execution, or live execution.

`C6A_DESIGN_ONLY`

`C6A_ECONOMIC_RESULT_NOT_RUN`

`C6B_CLOSED`

`C5B_CLOSED_AND_UNTOUCHED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
