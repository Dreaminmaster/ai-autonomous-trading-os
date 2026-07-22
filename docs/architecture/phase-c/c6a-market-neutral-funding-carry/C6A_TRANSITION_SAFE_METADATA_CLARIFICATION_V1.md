# C6A Transition-Safe Historical Metadata Clarification V1

## 1. Normative purpose

This document freezes one pre-economic implementation rule for C6A historical instrument metadata when an official public source proves both the before-state and after-state but publishes only a closed UTC adjustment window rather than the exact internal switch timestamp.

It adds no candidate, parameter, market-data interval, signal, gate, comparator, account access, execution authority, or economic result. It does not authorize C6A data capture or the C6A economic screen.

For the narrow subject defined here, this document supersedes less-specific wording in the C6A contract and prior metadata clarification. All other C6A rules remain unchanged.

### 1.1 Relation to the merged data-authority closeout

Main commit `692c3544971801c1de51759ffe5a0cc228cffdc1` correctly records that implementation PR #57 could not proceed under the previously frozen requirement for an exact timestamp-effective state at every historical transaction. That closeout remains the authoritative historical record for PR #57 and does not become an economic rejection.

This document is a separate prospective design-only reopening proposal based on a stricter conservative construction that was not present in PR #57: inside a proven official adjustment window, every admitted modeled quantity must be valid under both proven states. If this document is merged, it supersedes only the closeout's forward prohibition on revisiting C6A under the earlier metadata semantics. It does not erase the closeout, retroactively validate PR #57, or authorize implementation or market-data access.

After merge, the only permitted status is:

`C6A_DESIGN_REOPENED_PRE_ECONOMIC`

Before any implementation work or C6A economic data access, a separate source-authority gate must prove complete public metadata coverage for all four fixed instruments and the entire frozen interval under the rules below. Failure leaves C6A closed before economic evaluation.

## 2. Problem statement

The existing metadata authority requires exactly one unambiguous quantity rule at every modeled transaction timestamp and forbids projecting current values backward or inventing an effective timestamp.

An official exchange announcement may instead establish:

- the exact instrument;
- the exact pre-adjustment rule;
- the exact post-adjustment rule;
- a closed UTC maintenance or adjustment window;
- but not the exact internal instant at which the new rule became active.

Choosing the beginning, midpoint, or end of that window as the effective timestamp would be an unsupported inference and remains forbidden.

## 3. Transition-safe intersection authority

C6A may use `TRANSITION_SAFE_INTERSECTION` inside a published adjustment window only when every condition below is proven from retained public evidence:

1. the official before-state is known;
2. the official after-state is known;
3. the official adjustment window has an exact UTC start and end;
4. instrument ID, instrument type, base/quote/settlement currencies, `ctVal`, `ctValCcy`, and tick size are unchanged across the transition;
5. only `lotSz` and/or `minSz` differ;
6. the old and new lot increments are nested exact integer multiples;
7. the retained old-state, new-state, and announcement sources each have immutable provenance and SHA-256 binding;
8. the resulting allowed quantity set is demonstrably valid under both the old and new rules.

Failure of any condition is a pre-economic evidence failure. The implementation may not substitute current metadata, inferred timestamps, private data, account settings, or a permissive union of the two states.

## 4. Exact interval semantics

For an official transition window `[window_start, window_end)`:

```text
transaction_time < window_start
    -> use the proven old-state rule

window_start <= transaction_time < window_end
    -> use TRANSITION_SAFE_INTERSECTION

window_end <= transaction_time
    -> use the proven new-state rule
```

The transition-safe record does not assert that the exchange changed rules at `window_start`, `window_end`, or any other internal timestamp. It asserts only that every modeled quantity admitted during the window is valid regardless of which proven state was active at that instant.

## 5. Intersection construction

Let:

```text
old_lot = old lot-size increment
new_lot = new lot-size increment
old_min = old minimum size
new_min = new minimum size
```

The increments must be nested:

```text
max(old_lot, new_lot) / min(old_lot, new_lot)
```

must be a positive integer with no rounding tolerance.

The transition-safe increment is the coarser increment:

```text
transition_lot = max(old_lot, new_lot)
```

The transition-safe minimum is the smallest exact multiple of `transition_lot` that is not less than either minimum:

```text
transition_min
  = ceil(max(old_min, new_min) / transition_lot)
    * transition_lot
```

A modeled quantity inside the window is allowed only when it:

- is an exact non-negative integer multiple of `transition_lot`;
- is either zero or at least `transition_min`;
- satisfies every unchanged contract-value, currency-conversion, tick-size, hedge, collateral, and rounding rule;
- independently validates under both retained old-state and new-state metadata records.

This construction is an intersection, never a union. It may reduce feasible quantities but may not create a quantity that either actual state would reject.

## 6. Required retained metadata fields

Every transition-safe metadata record must retain:

- `authority_mode = TRANSITION_SAFE_INTERSECTION`;
- instrument ID and type;
- unchanged currency, contract-value, contract-value-currency, and tick-size fields;
- old and new `lotSz` and `minSz`;
- derived `transition_lot` and `transition_min`;
- inclusive `effective_from = window_start`;
- exclusive `effective_to = window_end`;
- exact official adjustment-window source URL and SHA-256;
- exact old-state source URL and SHA-256;
- exact new-state source URL and SHA-256;
- an explicit statement that the internal exchange switch timestamp is unknown and was not inferred;
- a machine-verifiable proof that the increments are nested and the admitted set is valid under both states.

Ordinary metadata records before and after the transition retain the existing `EXACT_EFFECTIVE_STATE` authority mode and all fields required by the prior clarification.

## 7. Frozen C6A transition windows

This clarification applies only to the following four already identified official public adjustment windows for the fixed C6A perpetual instruments:

| Instrument | UTC transition window | Frozen rule change |
|---|---|---|
| `ETH-USDT-SWAP` | `[2024-04-18T06:00:00Z, 2024-04-18T08:00:00Z)` | contract lot/minimum step `1` to `0.1` |
| `BTC-USDT-SWAP` | `[2024-04-25T06:00:00Z, 2024-04-25T08:00:00Z)` | contract lot/minimum step `1` to `0.1` |
| `ETH-USDT-SWAP` | `[2025-01-09T06:00:00Z, 2025-01-09T10:00:00Z)` | contract lot/minimum step `0.1` to `0.01` |
| `BTC-USDT-SWAP` | `[2025-01-22T06:00:00Z, 2025-01-22T08:00:00Z)` | contract lot/minimum step `0.1` to `0.01` |

No other transition window may be added after C6A economic data is read. A newly discovered pre-economic contradiction or additional relevant transition must stop implementation and require a new design-only clarification before any economic run.

## 8. Source and completeness boundary

The pre-economic source-authority gate must retain the exact official historical instrument snapshots that establish the baseline states, the exact official announcements that establish the changes and windows, and the exhaustive pre-economic announcement-catalog evidence used to check for additional relevant changes.

Coverage must include all four fixed instruments — `BTC-USDT`, `ETH-USDT`, `BTC-USDT-SWAP`, and `ETH-USDT-SWAP` — from `2023-06-05T00:00:00Z` through the exclusive economic boundary `2025-12-29T00:00:00Z`. Proving only the four perpetual transition windows is insufficient. Spot quantity and tick rules, unchanged swap contract-value and currency fields, and every interval between retained states must also be proven.

Archived bytes are eligible only when they are exact archived responses of a permitted official OKX public endpoint, with the original OKX URL, archive timestamp, raw-byte SHA-256, decoded-byte SHA-256, and decoding method retained. The archive service itself does not become a new economic-data authority; it only preserves an official OKX response.

Absence of an archive capture does not prove a value. Completeness must come from the combination of directly retained official snapshots, official change announcements, overlap checks, and the frozen exhaustive pre-economic catalog scan.

The source-authority gate must run before economic data capture and must produce a machine-verifiable manifest with zero uncovered interval, zero ambiguous state, zero unsupported backward projection, and zero source-hash mismatch. Only a separately reviewed PASS may authorize a later implementation/economic stage.

## 9. Failure conditions

C6A fails before economic evaluation if any of the following occurs:

- old or new state is missing or contradictory;
- the adjustment window is missing, open-ended, or timezone-ambiguous;
- `ctVal`, `ctValCcy`, currency fields, tick size, or instrument identity differ inside a claimed transition-safe window;
- lot increments are not nested exact integer multiples;
- the transition minimum cannot be represented exactly;
- a modeled quantity passes only one of the two states;
- source provenance or any required SHA-256 is absent;
- any spot or perpetual interval in the frozen coverage range remains unproven;
- an additional relevant transition is discovered after the frozen source inventory;
- the implementation claims an exact internal switch timestamp not published by an official source.

Such a failure is an evidence failure, not a zero-trade observation and not an economic rejection.

## 10. Claim and safety boundary

This clarification does not authorize implementation merge, C6A market-data capture, an economic run, C6B, C5B access, account access, paper execution, shadow execution, or live execution.

The merged data-authority closeout remains the historical record of the abandoned PR #57 attempt. No C6A economic result exists. A future source-authority PASS and implementation require separate exact-SHA review and authorization.

`C6A_DESIGN_REOPENED_PRE_ECONOMIC`

`C6A_ECONOMIC_RESULT_NOT_RUN`

`C6B_CLOSED`

`C5B_CLOSED_AND_UNTOUCHED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
