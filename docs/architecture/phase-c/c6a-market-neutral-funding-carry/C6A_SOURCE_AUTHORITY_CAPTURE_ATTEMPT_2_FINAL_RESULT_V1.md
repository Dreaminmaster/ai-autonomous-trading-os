# C6A Source-Authority Capture Attempt 2 Final Result V1

## 1. Scope and final status

This document freezes the second authorized pre-economic C6A source-authority capture and its independently verified final decision.

Unlike attempt 1, attempt 2 used the remediated locale-aware announcement parser and the remediated independent attempt-diagnostic reviewer. The workflow completed successfully, the retained bundle is recursively hash-consistent, the physically separate independent review returned `PASS`, and the recorded and recomputed failure sets match exactly.

The authoritative source-authority result is therefore:

`FAIL_ARCHIVE_DECODING_OR_PROVENANCE`

This is a valid final source-authority failure under the frozen binary gate. It authorizes no C6A economic implementation, no economic data access, and no rerun.

## 2. Immutable execution identity

- GitHub Actions run: `30010713956`
- job: `89217780598`
- workflow conclusion: `success`
- workflow run attempt: `1`
- remediated implementation SHA checked out by the workflow: `bcb126d63436f253aad1aeac695ad325ad316899`
- validated remediation PR merge ref: `refs/pull/65/merge@eda36c041e8528c3f7d728d41d7863c62e9a00d9`
- one-shot authorization/trigger commit: `e8fa04bb0e99c0fd8fa2d86b6f804a34455a2236`
- artifact ID: `8564979748`
- artifact name: `c6a-source-authority-attempt-2-30010713956`
- artifact size: `277266` bytes
- GitHub artifact digest: `sha256:57932ceffa3c4e84d5a46556132650eca5bbe9b2b67e58efff17f7fb25c39c1c`
- artifact expiry recorded by GitHub: `2026-10-21T13:19:34Z`

The independently downloaded ZIP reproduced the same SHA-256 digest.

## 3. Workflow-control review

Every workflow step completed successfully:

- rerun rejection before checkout or network access;
- checkout of the exact validated remediation SHA;
- Python setup;
- immutable execution-identity verification;
- one-shot fail-closed source-authority attempt;
- outer bundle-manifest construction;
- complete artifact upload;
- non-authorizing result summary;
- post-upload execution and bundle-integrity enforcement.

The runner token had read-only repository contents permission. Checkout credentials were not persisted. No user-interface rerun occurred.

## 4. Bundle integrity review

The outer bundle manifest declared 46 files. Independent recursive verification found:

- 46 declared files;
- 46 actual files excluding the manifest itself;
- no missing file;
- no extra file;
- no size mismatch;
- no SHA-256 mismatch.

The inner canonical package manifest declared 43 files. Independent recursive verification found:

- 43 declared files;
- 43 actual files excluding the manifest itself;
- no missing file;
- no extra file;
- no size mismatch;
- no SHA-256 mismatch.

The gate's 41 retained-input/output hash bindings all reproduced exactly. The independent-review hash and frozen query-inventory hash also reproduced exactly.

Therefore the retained workflow evidence and canonical package are complete and internally hash-consistent.

## 5. Remediation verification

### 5.1 Complete announcement catalog

The corrected parser accepted bounded official locale-prefixed Help Center paths while preserving exact official URLs.

Attempt 2 retained and decoded:

- 9 complete official announcement-catalog pages;
- 121 deduplicated catalog items;
- terminal-page proof;
- zero catalog duplicate or scope-escape failure.

The attempt-1 locale-path implementation defect is therefore resolved.

### 5.2 Independent attempt-diagnostic review

The physically separate reviewer independently consumed the retained attempt diagnostics and recomputed the archive failure from request kind, stage, URL class, and error identity rather than trusting the producer's recorded failure code.

Its attempt-diagnostic review returned:

- status: `PASS`;
- event count: `4`;
- recomputed failure: `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`;
- errors: none.

The attempt-1 independent failure-recomputation defect is therefore resolved.

## 6. Retained official evidence

The package retained 14 eligible official-public source objects:

- 9 complete official OKX announcement-catalog pages;
- 5 directly bound official OKX transition notices.

The five notices cover:

- ETH-USDT-SWAP lot/minimum transition on 2024-04-18;
- BTC-USDT-SWAP lot/minimum transition on 2024-04-25;
- original ETH-USDT adjustment notice published in December 2024;
- postponed ETH-USDT transition leading to the 2025-01-09 window;
- BTC-USDT adjustment leading to the 2025-01-22 window.

The retained-source review returned `PASS` with 14 source objects and zero provenance error.

No candle, mark-price, funding-history, account, trade-history, order, paper, shadow, private API, or live endpoint was accessed.

## 7. Authoritative failure evidence

The four frozen Wayback CDX archive requests did not yield eligible archived official metadata states:

1. BTC-USDT spot archive index: valid response retained, but the CDX result was empty;
2. ETH-USDT spot archive index: valid response retained, but the CDX result was empty;
3. BTC-USDT-SWAP archive index: valid response retained, but the CDX result was empty;
4. ETH-USDT-SWAP archive index: three attempts exhausted with connection refused.

The frozen gate forbids projecting today's public-instruments response backward and forbids replacing a failed official/archive source with a weaker authority class after source content has been inspected.

Consequently the package contains:

- metadata states: `0`;
- transition proofs: `0`;
- coverage rows: `0`;
- all four frozen transition states missing;
- complete authority interval unproven for all four instruments.

Missing archive captures do not prove that historical metadata never existed. They prove that the exact frozen official-public evidence plan did not establish the complete timestamp-effective authority required by the C6A contract.

## 8. Independent final decision

The production gate recorded:

- gate status: `FAIL`;
- primary result: `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`;
- secondary failures:
  - `FAIL_REQUIRED_FIELD_MISSING`;
  - `FAIL_UNCOVERED_INTERVAL`;
  - `FAIL_TRANSITION_WINDOW_UNPROVEN`;
- source objects: `14`;
- eligible source objects: `14`;
- catalog pages: `9`;
- catalog items: `121`;
- metadata states: `0`;
- transition proofs: `0`;
- forbidden access count: `0`;
- independent review status: `PASS`;
- integrity state: `FINAL_PACKAGE_AND_INDEPENDENT_REVIEW_VERIFIED`;
- authoritative: `true`.

The physically separate independent review recomputed exactly the same four failure codes, selected the same primary result, reported no error, and returned `PASS`.

The transition-partition review also returned `PASS` because it independently confirmed that all four required transition states were absent and that the fail-closed transition failure was correctly recorded.

## 9. Final classification

Attempt 2 is classified as:

`CAPTURE_ATTEMPT_2_EVIDENCE_VALID`

`C6A_SOURCE_AUTHORITY_FINAL_FAIL`

`C6A_DATA_AUTHORITY_FAILURE_CONFIRMED`

`C6A_ECONOMIC_SCREEN_NOT_RUN`

`SELECTED_POLICY_NULL`

The earlier attempt-1 state `C6A_SOURCE_AUTHORITY_FINAL_RESULT_NOT_ESTABLISHED` is superseded by this independently verified final FAIL result.

The result does not authorize a third capture. Repeating the same public-source plan in hope of a different archive response would not be an efficient or independently justified next step. Any future reopening would require a materially new official authority class or source plan, a new design-only contract, exact-head review, and separate explicit authorization.

## 10. Lifecycle closure

The temporary workflow `.github/workflows/c6a-source-authority-capture-attempt-2.yml` must be deleted immediately after this result is frozen.

The C6A market-neutral funding-carry thesis remains closed before economic evaluation. No candle, funding, comparator, strategy, or policy result exists for C6A.

A future Phase C research direction must be structurally distinct and preregistered separately. It may not reuse C6A as if the source-authority gate had passed, weaken the historical metadata contract, infer past metadata from current state, or open C6B/C5B/holdout/paper/shadow/live.

## 11. Safety state

`C6A_SOURCE_AUTHORITY_CAPTURE_ATTEMPT_2_CLOSED`

`C6A_SOURCE_AUTHORITY_FINAL_FAIL`

`C6A_DATA_AUTHORITY_FAILURE_CONFIRMED`

`C6A_ECONOMIC_RESULT_NOT_RUN`

`C6A_ECONOMIC_IMPLEMENTATION_NOT_AUTHORIZED`

`C6A_ECONOMIC_DATA_ACCESS_NOT_AUTHORIZED`

`C6B_CLOSED`

`C5B_CLOSED_AND_UNTOUCHED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
