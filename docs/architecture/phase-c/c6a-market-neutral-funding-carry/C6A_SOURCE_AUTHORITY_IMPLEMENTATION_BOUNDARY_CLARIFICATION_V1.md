# C6A Source-Authority Implementation Boundary Clarification V1

## 1. Normative purpose

This clarification resolves the distinction between:

1. implementation of the pre-economic C6A historical-metadata source-authority gate; and
2. implementation of the C6A strategy, accounting, simulation, comparators, gates, or economic screen.

For this distinction, it supersedes less-specific uses of the word `implementation` in `C6A_HISTORICAL_METADATA_SOURCE_AUTHORITY_GATE_V1.md`. It changes no metadata field, source class, transition rule, time boundary, economic candidate, cost, gate, or safety state.

## 2. Source-authority gate implementation

After the source-authority gate design is merged, a separate PR may implement only the machinery required to test that gate, including:

- the frozen query inventory and network allowlist;
- official-public metadata and announcement capture;
- eligible archive-response capture and deterministic decoding;
- immutable raw-byte retention and SHA-256 binding;
- exact-decimal metadata parsing;
- announcement-catalog completeness checks;
- metadata-state construction;
- transition-safe intersection proofs;
- interval coverage and contradiction checks;
- canonical gate outputs and complete manifest generation;
- physically separate read-only independent recomputation.

This is `SOURCE_AUTHORITY_GATE_IMPLEMENTATION`. It is not C6A economic implementation and must not import, execute, or inspect C6A signal, portfolio, ledger, comparator, statistic, selection, candle, mark-price, funding-rate, return, or strategy-result logic.

## 3. Ordinary validation and one-time execution

`SOURCE_AUTHORITY_GATE_IMPLEMENTATION` must first pass ordinary exact-head validation through the existing `CI` and `Freqtrade Validation` workflows wherever their path filters apply.

Only after that implementation PR has passed ordinary validation and exact-head independent code review may one temporary dedicated source-authority workflow be added for the single controlled public-source capture. Therefore, the phrase “after implementation code and ordinary validation pass” in Section 10 of the gate document means:

> after source-authority gate implementation code and its ordinary validation pass

It does not mean after C6A strategy or economic implementation.

The temporary workflow remains subject to every hygiene rule in the gate document: one authorized run, no economic endpoint, no private credential, complete artifact upload on PASS or FAIL, durable provenance, and deletion after result freeze.

## 4. Economic implementation remains closed

Neither this clarification, the gate design, the source-authority gate implementation, nor a gate PASS authorizes:

- C6A strategy implementation;
- C6A accounting or simulation implementation;
- candle, mark-price, or funding-history capture;
- an economic screen;
- strategy selection;
- C6B, C5B, holdout, paper, shadow, private API, or live access.

In the gate document, `C6A implementation: NOT_AUTHORIZED`, `implementation_authorized = false`, and statements that C6A implementation is not authorized refer specifically to strategy/economic implementation. A later economic implementation PR requires an exact merged source-authority PASS artifact and a separate prospective authorization.

## 5. Final state

`C6A_SOURCE_AUTHORITY_GATE_DESIGN_ONLY`

`SOURCE_AUTHORITY_GATE_IMPLEMENTATION_SEPARATE_FUTURE_WORK`

`C6A_ECONOMIC_IMPLEMENTATION_NOT_AUTHORIZED`

`C6A_ECONOMIC_RESULT_NOT_RUN`

`C6B_CLOSED`

`C5B_CLOSED_AND_UNTOUCHED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
