# C6A Source-Authority Capture Attempt 1 Closeout V1

## 1. Scope and status

This document freezes the evidence from the first authorized pre-economic C6A source-authority capture attempt.

The workflow itself completed successfully and retained a complete artifact bundle. The resulting source-authority gate decision is **not accepted as the final C6A source-authority determination**, because the retained evidence exposes two implementation defects and the physically separate independent review returned `FAIL`.

This closeout authorizes no economic implementation, no economic data access, and no second capture attempt.

## 2. Immutable execution identity

- GitHub Actions run: `29995661081`
- job: `89168616696`
- workflow conclusion: `success`
- implementation SHA checked out by the workflow: `9ccda298e1acdfb3422173e5990d978d4a9e07c3`
- validated implementation PR merge ref: `refs/pull/62/merge@f2812d54408f5e80cac664d4159d361f94982f5a`
- one-shot authorization/trigger commit: `a992691959e6a66e1d1c867650976560affc8654`
- artifact ID: `8558907003`
- artifact name: `c6a-source-authority-capture-29995661081`
- artifact size: `120947` bytes
- GitHub artifact digest: `sha256:7b2522d82235546da36fc00b20e32e503c437c64d2dab8889be1e7f57580e282`
- artifact expiry recorded by GitHub: `2026-10-21T09:31:20Z`

The downloaded ZIP independently reproduced the same SHA-256 digest.

## 3. Bundle integrity review

The outer bundle manifest declared 29 files. Independent recursive verification found:

- 29 declared files;
- 29 actual files excluding the manifest itself;
- no missing file;
- no extra file;
- no size mismatch;
- no SHA-256 mismatch.

The inner canonical package manifest declared 26 files. Independent recursive verification found:

- 26 declared files;
- 26 actual files excluding the manifest itself;
- no missing file;
- no extra file;
- no size mismatch;
- no SHA-256 mismatch.

Therefore the retained execution evidence is complete and internally hash-consistent.

## 4. Captured evidence

The attempt retained five official OKX transition notices and their deterministic decoded records:

- ETH-USDT-SWAP minimum-order transition notice for 2024-04-18;
- BTC-USDT-SWAP minimum-order transition notice for 2024-04-25;
- original ETH-USDT perpetual/expiry adjustment notice published in December 2024;
- postponed ETH-USDT transition notice leading to the 2025-01-09 window;
- BTC-USDT spot/futures adjustment notice leading to the 2025-01-22 window.

It also retained:

- raw bytes for announcement-catalog page 1;
- raw responses for three empty Wayback CDX queries;
- the complete attempt log for all catalog/archive failures;
- the canonical gate, independent-review, source-inventory, diagnostics, and manifest objects.

No candle, mark-price, funding-history, account, trade-history, order, paper, shadow, private API, or live endpoint was accessed. The bundle records `economic_data_access_authorized = false`, `implementation_authorized = false`, and `LIVE_FORBIDDEN`.

## 5. Defect A — locale-prefixed official article paths

The retained catalog page reported 15 articles and 121 total articles. All 15 article links were official HTTPS links under:

`https://www.okx.com/en-us/help/...`

The production catalog parser incorrectly required the path to start exactly with `/help/`. It therefore rejected valid locale-prefixed official article paths such as `/en-us/help/...` and stopped after page 1 with:

`catalog article URL escaped the frozen OKX help scope`

This is an implementation defect, not evidence that the official catalog was incomplete.

Required remediation:

- accept only exact official OKX help paths matching either `/help/<slug>` or `/<locale>/help/<slug>`;
- continue to reject other OKX paths, non-OKX hosts, HTTP, credentials, fragments, and redirect escapes;
- add tests using retained page-1 structure and locale-prefixed links.

## 6. Defect B — independent failure recomputation mismatch

The production gate recorded `FAIL_ARCHIVE_DECODING_OR_PROVENANCE` from the retained archive-attempt errors:

- three Wayback CDX responses were valid JSON but empty;
- the fourth archive query exhausted retries after a TLS handshake timeout.

The physically separate independent reviewer recomputed failures only from the source inventory, catalog, states, proofs, and coverage objects. It did not independently consume the retained attempt log or archive-index diagnostics. It therefore omitted the archive failure code, selected a different primary failure, and returned `FAIL` because the recorded and recomputed failure sets differed.

Required remediation:

- independently validate and consume retained attempt diagnostics when recomputing transport/decoding/provenance failures;
- bind each diagnostic to a frozen request ID, request kind, URL class, stage, and deterministic failure-code mapping;
- reject unknown or unbound diagnostic entries;
- require exact equality between recorded and independently recomputed failure sets before any authoritative result is accepted.

## 7. Result classification

The workflow-level execution and artifact-retention controls passed.

The package-level result was:

- gate status: `FAIL`;
- recorded primary result: `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`;
- independent review status: `FAIL`;
- integrity state: `FINAL_PACKAGE_VERIFIED_INDEPENDENT_REVIEW_FAILED`.

Because the independent review failed and the catalog parser demonstrably rejected valid official links, this attempt is classified as:

`CAPTURE_ATTEMPT_EVIDENCE_VALID`

`FINAL_SOURCE_AUTHORITY_GATE_DECISION_NOT_ACCEPTED`

`IMPLEMENTATION_REMEDIATION_REQUIRED`

It must not be cited as either a source-authority PASS or an authoritative source-authority FAIL.

## 8. Lifecycle closure

The temporary one-shot workflow must be deleted after this evidence is frozen. Deleting it does not authorize a rerun. A future capture requires:

1. a separate remediation PR;
2. exact-head ordinary CI;
3. independent code review of the corrected parser and reviewer;
4. a new explicit one-shot authorization;
5. a new immutable artifact and result closeout.

## 9. Safety state

`C6A_SOURCE_AUTHORITY_CAPTURE_ATTEMPT_1_CLOSED`

`C6A_SOURCE_AUTHORITY_FINAL_RESULT_NOT_ESTABLISHED`

`C6A_ECONOMIC_IMPLEMENTATION_NOT_AUTHORIZED`

`C6A_ECONOMIC_DATA_ACCESS_NOT_AUTHORIZED`

`C6B_CLOSED`

`C5B_CLOSED_AND_UNTOUCHED`

`HOLDOUT_CLOSED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
