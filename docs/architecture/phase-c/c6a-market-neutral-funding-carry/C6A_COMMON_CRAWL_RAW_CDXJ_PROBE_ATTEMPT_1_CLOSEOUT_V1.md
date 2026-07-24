# C6A Common Crawl Raw CDXJ Probe Attempt 1 Closeout V1

## Final decision

The first authorized raw Common Crawl CDXJ execution is closed as valid retained failure evidence.

The run does **not** verify the raw CDXJ access path, does **not** establish archive coverage, and does **not** authorize WARC retrieval or any later C6A gate.

A deterministic implementation defect was exposed: the fifth tab-separated field in `cluster.idx` was treated as the number of CDXJ rows in the selected gzip block. Retained real Common Crawl blocks each decompressed to 3,000 CDXJ rows, while that fifth field contained large monotonically increasing values such as `409787`, `383346`, and `438932`. Common Crawl's primary CDXJ documentation states that the index is gzip-compressed in blocks of 3,000 lines. The fifth field must therefore remain an opaque secondary-index identifier/ordinal and must not be compared with decompressed line count.

## Immutable execution identity

- run: `30070023393`
- job: `89408763728`
- implementation SHA: `d4991d33cf5e425cc84f7981128e02e261927d20`
- validated implementation merge ref: `refs/pull/83/merge@fc999455b9c8400aaf8958717c8909a40cd42c80`
- authorization/trigger SHA: `627dc450befad3fddb6d4c450a5494a9abf83f05`
- run attempt: `1`
- frozen inventory SHA-256: `d68ba30bf038d9b9d497edcd26c550ac6c749864a2ca76c0e13981fabb0a897a`
- artifact ID: `8587665587`
- artifact name: `c6a-common-crawl-raw-cdxj-probe-30070023393`
- artifact size: `4,485,350` bytes
- artifact digest: `sha256:5d29c2055943d6a4197be04e19ed66a9fb89cf8ab602a93d8d909bafa86899e0`
- artifact expiry: `2026-10-22T05:39:29Z`

## Independent package verification

The downloaded ZIP digest matched GitHub's artifact digest exactly.

- outer manifest: `123/123` files present, with exact size and SHA-256 agreement;
- inner manifest: `120/120` files present, with exact size and SHA-256 agreement;
- no missing, extra, or mismatched file;
- no WARC file was retained;
- execution identity, implementation SHA, merge ref, trigger SHA, run ID, and attempt matched;
- producer result: `FAIL / RAW_CDXJ_ACCESS_PATH_EXECUTION_FAILED`;
- independent review: `PASS`;
- independently recomputed probe status: `FAIL`;
- review errors: `[]`.

This means the failure package is internally complete and correctly classified. It does not convert the failed execution into a verified access path.

## Observed result

- frozen targets: `7`;
- expected target/crawl queries: `23`;
- completed queries: `0`;
- failed queries: `23`;
- exact-hit queries: `0`;
- retained unique range responses: `116`;
- unique selected CDX gzip blocks: `8`, because identical crawl/block ranges were cached across target queries;
- every failed query reported: `CDX block line count does not match cluster record count`.

The eight retained selected blocks all decompressed successfully and each contained exactly 3,000 CDXJ rows:

| Crawl/block example | Compressed bytes | Decompressed bytes | Decompressed rows | Fifth `cluster.idx` field |
|---|---:|---:|---:|---:|
| `CC-MAIN-2024-18 / cdx-00109.gz` | 203,177 | 1,321,241 | 3,000 | 409,787 |
| `CC-MAIN-2024-51 / cdx-00110.gz` | 213,404 | 1,319,802 | 3,000 | 383,346 |
| `CC-MAIN-2025-05 / cdx-00111.gz` | 209,580 | 1,303,079 | 3,000 | 438,932 |
| `CC-MAIN-2025-21 / cdx-00111.gz` | 217,246 | 1,332,641 | 3,000 | 367,942 |
| `CC-MAIN-2024-22 / cdx-00107.gz` | 215,315 | 1,344,539 | 3,000 | 393,447 |
| `CC-MAIN-2024-26 / cdx-00110.gz` | 213,569 | 1,323,334 | 3,000 | 415,258 |
| `CC-MAIN-2025-08 / cdx-00111.gz` | 204,390 | 1,309,008 | 3,000 | 394,668 |
| `CC-MAIN-2025-13 / cdx-00112.gz` | 222,672 | 1,346,220 | 3,000 | 408,026 |

The HTTP range path, gzip decoding, object-size/ETag binding, and evidence retention operated far enough to expose the semantic defect. No exact URL-hit decision is admissible because query execution stopped before parsing each selected block.

## Required remediation

The next implementation may:

1. rename the fifth parsed cluster field from `record_count` to an opaque `block_ordinal` or equivalent;
2. require that value to be a non-negative integer but never use it as CDXJ row count;
3. validate decompressed blocks independently with a bounded non-empty line count, a maximum of 3,000 rows, first-row identity binding, compressed/decompressed hash binding, and retained exact line count;
4. update the physically separate reviewer to recompute the same semantics without importing producer selection or decode logic;
5. add regression tests using realistic fifth-field values such as `409787` with a 3,000-row block and prove that inventory, boundary, compressed-range, and first-row tampering still fail closed.

The old workflow/run must not be rerun. A future execution requires a separately reviewed remediation SHA, exact merge-ref CI, a new one-shot workflow, and separate authorization.

## Classification

- `RAW_CDXJ_ATTEMPT_1_EXECUTION_EVIDENCE_VALID`
- `RAW_CDXJ_ATTEMPT_1_INDEPENDENT_REVIEW_PASS`
- `RAW_CDXJ_CLUSTER_FIELD_SEMANTIC_DEFECT_CONFIRMED`
- `RAW_CDXJ_ACCESS_PATH_NOT_VERIFIED`
- `IMPLEMENTATION_REMEDIATION_REQUIRED`
- `ATTEMPT_1_RERUN_NOT_AUTHORIZED`

## Safety state

- direct OKX access: `NOT_AUTHORIZED`
- WARC retrieval: `NOT_AUTHORIZED`
- article expansion: `NOT_AUTHORIZED`
- third full source-authority capture: `NOT_AUTHORIZED`
- economic implementation: `NOT_AUTHORIZED`
- economic data access: `NOT_AUTHORIZED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`
