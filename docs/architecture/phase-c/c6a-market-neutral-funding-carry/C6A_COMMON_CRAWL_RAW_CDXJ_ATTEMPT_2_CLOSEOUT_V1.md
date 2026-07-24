# C6A Common Crawl Raw CDXJ Probe Attempt 2 Closeout V1

## Decision

The single authorized execution of the remediated raw Common Crawl ZipNum/CDXJ probe completed successfully and is now closed without rerun.

The retained package proves that the bounded raw CDXJ metadata access path is operational for all 23 frozen exact target/crawl pairs. It also proves that none of those 23 exact locale-neutral OKX Help Center URL queries produced a matching HTTP-200 CDXJ row in the frozen event-adjacent crawl matrix.

This is an accepted access-path result and an accepted zero-hit finding within the frozen matrix. It is not a source-authority PASS, does not prove archive-wide absence, and does not authorize WARC retrieval or a third full source-authority capture.

## Immutable execution identity

- workflow run: `30071405830`
- workflow job: `89412888807`
- run attempt: `1`
- trigger/main SHA: `e6427863121b48f12907d6078de2bb649494cdf2`
- executed implementation SHA: `a673e95145e2ade2589abaf1bb5a559a2f8b7461`
- validated remediation merge ref: `refs/pull/86/merge@4e3403e1dfd112208a36b3ff3cdadb1f75c9b566`
- frozen canonical inventory SHA-256: `d68ba30bf038d9b9d497edcd26c550ac6c749864a2ca76c0e13981fabb0a897a`
- artifact ID: `8588169161`
- artifact name: `c6a-common-crawl-raw-cdxj-probe-attempt-2-30071405830`
- artifact ZIP SHA-256: `733f04ee8e962c8cc9f6ea649b8788f9607bba1b84ff5abc24b7e6c92a671020`
- artifact expiry: `2026-10-22T06:08:39Z`

## Independent package verification

The downloaded artifact ZIP reproduced the GitHub artifact digest exactly.

- outer manifest: `169/169` files verified
- inner manifest: `166/166` files verified
- missing files: `0`
- extra files: `0`
- size mismatches: `0`
- SHA-256 mismatches: `0`
- retained WARC files: `0`
- independent review status: `PASS`
- independent review errors: `[]`

The package retained the frozen inventory, execution identity, all unique range responses, selected compressed/decompressed CDXJ blocks, all 23 per-query records, producer result, physically separate independent review, logs, and complete manifests.

## Accepted producer and reviewer result

Producer:

- status: `PASS`
- result: `RAW_CDXJ_ACCESS_PATH_VERIFIED`
- completed queries: `23`
- failed queries: `0`
- hit queries: `0`
- execution errors: `[]`
- fifth cluster field semantics: `OPAQUE_BLOCK_ORDINAL`
- maximum accepted CDXJ lines per block: `3000`

Independent reviewer:

- review status: `PASS`
- recomputed probe status: `PASS`
- recomputed probe result: `RAW_CDXJ_ACCESS_PATH_VERIFIED`
- recomputed query count: `23`
- recomputed failed-query count: `0`
- recomputed hit-query count: `0`

Producer and reviewer agree exactly.

## Raw-index observations

The 23 exact queries covered seven frozen locale-neutral targets across eight Common Crawl releases:

- `CC-MAIN-2024-18`
- `CC-MAIN-2024-22`
- `CC-MAIN-2024-26`
- `CC-MAIN-2024-51`
- `CC-MAIN-2025-05`
- `CC-MAIN-2025-08`
- `CC-MAIN-2025-13`
- `CC-MAIN-2025-21`

The queries resolved to eight unique selected ZipNum blocks. Every selected block:

- was retrieved by an exact HTTP byte range from `data.commoncrawl.org`;
- decompressed successfully;
- contained exactly `3000` non-empty CDXJ lines;
- matched its secondary-index first-row identity;
- retained a positive opaque block ordinal;
- passed independent compressed/decompressed and range-evidence binding;
- produced zero exact HTTP-200 rows for the requested locale-neutral URL.

Representative opaque block ordinals include `409787`, `393447`, `415258`, `383346`, `438932`, `394668`, `408026`, and `367942`.

## Interpretation boundary

The accepted finding is deliberately narrow:

`EXACT_GLOBAL_ARCHIVE_METADATA_ZERO_HITS_WITHIN_FROZEN_23_QUERY_MATRIX`

It means:

1. the corrected raw-index implementation executed successfully;
2. the selected blocks and their boundaries were independently validated;
3. no exact HTTP-200 CDXJ metadata row was found for any frozen locale-neutral URL/crawl pair;
4. therefore no authorized WARC locator exists for those exact pairs.

It does not mean:

- Common Crawl contains no OKX material;
- every historical crawl release was searched;
- locale-prefixed or regional URLs were searched or accepted as GLOBAL;
- regional pages may be substituted for GLOBAL authority;
- source authority has passed;
- economic implementation may begin.

## Recovery-path decision

The GitHub-hosted direct-OKX path has already been shown to redirect both tested locale-neutral catalog surfaces to `/en-us/help/...`.

The Common Crawl exact-URL recovery path is now also exhausted for the frozen event-adjacent matrix because it produced zero exact locale-neutral CDXJ hits and therefore no WARC locators that could be reviewed for GLOBAL response bytes.

No broader archive crawl, wildcard URL discovery, locale-prefix substitution, guessed URL expansion, regional-source acceptance, or WARC retrieval is authorized by this closeout.

The next admissible execution boundary is the already reviewed `LOCAL_USER_CONTROLLED` GLOBAL category-root venue preflight from PR #78, provided its one invocation has not been consumed. That preflight remains limited to the category-root scope decision and does not authorize article expansion or a third full capture.

## Workflow retirement

`.github/workflows/c6a-common-crawl-raw-cdxj-probe-attempt-2.yml` is deleted in the closeout PR.

The completed run must not be rerun. Any future network execution requires a separately reviewed implementation identity and explicit authorization.

## Frozen classification

- `RAW_CDXJ_ATTEMPT_2_EVIDENCE_VALID`
- `RAW_CDXJ_ACCESS_PATH_VERIFIED`
- `EXACT_GLOBAL_ARCHIVE_METADATA_ZERO_HITS_WITHIN_FROZEN_23_QUERY_MATRIX`
- `NO_AUTHORIZED_WARC_LOCATORS_FOR_FROZEN_EXACT_PAIRS`
- `COMMON_CRAWL_EXACT_GLOBAL_RECOVERY_EXHAUSTED_WITHIN_FROZEN_MATRIX`
- `SOURCE_AUTHORITY_GATE_NOT_PASSED`
- `LOCAL_USER_CONTROLLED_VENUE_PREFLIGHT_NEXT_ADMISSIBLE_EXECUTION`
- `NO_RERUN`

## Safety state

- direct OKX access: `NOT_AUTHORIZED`
- WARC retrieval: `NOT_AUTHORIZED`
- article discovery/expansion: `NOT_AUTHORIZED`
- wildcard or guessed archive discovery: `NOT_AUTHORIZED`
- third full source-authority capture: `NOT_AUTHORIZED`
- economic implementation: `NOT_AUTHORIZED`
- economic data access: `NOT_AUTHORIZED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

`RAW_CDXJ_ACCESS_PATH_VERIFIED` / `FROZEN_EXACT_MATRIX_ZERO_HITS` / `SOURCE_AUTHORITY_GATE_NOT_PASSED` / `LIVE_FORBIDDEN`
