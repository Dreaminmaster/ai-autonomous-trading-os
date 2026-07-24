# C6A terminal data-authority decision V1

## 1. Decision

C6A is terminally closed with no selected policy.

- strategy stage: `C6A_CLOSED`
- source-authority gate: `NOT_PASSED`
- economic implementation: `NOT_AUTHORIZED`
- economic result: `NOT_RUN`
- selected policy: `null`
- C6B confirmation: `CLOSED_NOT_OPENED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

This is a data-authority rejection, not an economic finding about whether market-neutral funding carry would have earned money. The strategy was never permitted to read the frozen economic dataset or run its economic screen.

## 2. Why C6A is no longer recoverable inside the same thesis

The project tested several materially different, bounded source-authority routes without weakening the frozen point-in-time requirements:

1. the original official-catalog plus archive capture retained the official announcement catalog but could not establish the required historical metadata transitions;
2. direct GitHub-hosted locale-neutral Help Center probes resolved to a regional US surface rather than proving GLOBAL authority;
3. the bounded Common Crawl query-service route produced execution failures and no acceptable coverage decision;
4. the corrected raw Common Crawl CDXJ route completed all 23 frozen target/crawl queries but produced zero exact HTTP-200 hits in that matrix;
5. execution-venue preflight attempt 1 produced transport failures and was rejected because the old implementation mislabeled them as scope drift and did not enforce one durable start;
6. the remediated execution-venue preflight attempt 2 produced valid, independently reviewed `ERROR / FAIL_SOURCE_SCOPE_PROBE_EXECUTION` evidence for all eight candidates, with no final URL or response bytes and therefore no GLOBAL scope decision.

The latest retained package proves that the attempt-1 semantic defect was repaired. It does not create source authority. Repeating the same implementation or venue would only reproduce a known access failure and would be process repetition rather than new evidence.

## 3. Frozen interpretation

The following conclusions are authoritative:

- C6A has no valid historical point-in-time instrument-metadata authority;
- no backward projection of current contract metadata is permitted;
- regional Help Center content cannot substitute for locale-neutral GLOBAL authority;
- archive zero hits cannot be expanded into an archive-wide absence claim;
- transport failure cannot be interpreted as GLOBAL availability or unavailability;
- no weaker source, guessed URL, undocumented endpoint, proxy, credential, DNS override, or routing circumvention is admissible;
- the C6A economic screen remains unexecuted;
- no C6A implementation or policy may be promoted to paper, shadow, or live.

## 4. Program-level consequence

C6B was reserved only as a prospective confirmation stage if C6A passed every unchanged gate. C6A did not pass, so C6B is permanently closed and must not be repurposed as a new thesis.

The next research thesis, if separately preregistered, must use a new stage identity and must remove the decisive C6A dependency rather than relax it. In particular, it should not require reconstructed historical lot size, minimum size, contract value, or listing-state transitions for its research PnL.

## 5. Boundary

This document authorizes only the terminal C6A decision and the possibility of a separate design-only next-stage proposal. It authorizes no implementation, real-data download, economic run, authenticated API, account access, order, paper, shadow, or live behavior.

`C6A_DATA_AUTHORITY_REJECTED` / `C6A_ECONOMIC_RESULT_NOT_RUN` / `SELECTED_POLICY_NULL` / `C6B_CLOSED_NOT_OPENED` / `PAPER_CLOSED` / `SHADOW_CLOSED` / `LIVE_FORBIDDEN`
