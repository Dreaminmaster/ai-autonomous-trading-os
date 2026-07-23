# C6A Common Crawl Probe Attempt 1 Closeout V1

## Decision

The one-shot bounded Common Crawl probe executed once and retained a complete artifact, but its final archive-coverage decision is **not accepted**.

The retained package proves the immutable execution identity, exact frozen query matrix, safety state, and failure mode. It does not prove either that official OKX GLOBAL bytes are available or that Common Crawl coverage is insufficient.

Authoritative classification:

- `COMMON_CRAWL_PROBE_ATTEMPT_1_EVIDENCE_VALID`
- `COMMON_CRAWL_PROBE_EXECUTION_FAILED`
- `FINAL_COMMON_CRAWL_COVERAGE_DECISION_NOT_ACCEPTED`
- `NO_RERUN`
- `THIRD_FULL_CAPTURE_NOT_AUTHORIZED`
- `LIVE_FORBIDDEN`

## Exact execution identity

- workflow: `C6A Common Crawl Probe Once`
- run: `30044489469`
- job: `89332194293`
- run attempt: `1`
- trigger branch: `main`
- trigger commit: `cd325863ea1807bc689515f992c995daf926d0f0`
- implementation SHA: `998d337fef8c01083b7a92693a2cbe570d410416`
- validated implementation merge ref: `refs/pull/80/merge@411b0847797b10e436dd24b47bbdc71e651f243a`
- artifact ID: `8578563095`
- artifact name: `c6a-common-crawl-probe-30044489469`
- artifact size: `5449` bytes
- artifact digest: `sha256:e25bf9d1a0d42ad079d3d02da58be97735d3d9e039972f11c89944820f25f9a6`
- artifact expiry: `2026-10-21T21:01:01Z`

The artifact ZIP digest was independently recomputed and exactly matched the GitHub-recorded digest.

## Workflow outcome

The one-shot and identity controls passed:

- rerun guard passed before checkout or network;
- exact implementation checkout passed;
- immutable identity verification passed;
- probe process completed and retained its result;
- outer bundle manifest was built;
- artifact upload succeeded;
- non-authorizing summary was published.

The final enforcement step failed, as designed, because the independent review did not pass.

No rerun is authorized.

## Artifact integrity

### Outer bundle

The outer manifest covered exactly six non-manifest files. Independent recomputation found:

- no missing file;
- no extra file;
- no size mismatch;
- no SHA-256 mismatch.

Outer manifest result: `6/6 VERIFIED`.

### Inner probe package

The inner manifest covered exactly three non-manifest files:

- `inventory_snapshot.json`
- `probe_result.json`
- `independent_review.json`

Independent recomputation found no missing, extra, size-mismatched, or hash-mismatched file.

Inner manifest result: `3/3 VERIFIED`.

The package therefore remains valid evidence of what happened even though it is not a valid coverage decision.

## Frozen query execution result

The inventory contained:

- seven exact official locale-neutral OKX Help Center targets;
- 23 exact target/crawl-index queries;
- zero guessed URLs;
- zero article expansion;
- zero direct OKX requests.

Observed query execution:

- total queries: `23`
- query rows with `status=PASS`: `0`
- query rows with `status=FAIL`: `23`
- HTTP `404 Not Found`: `22`
- HTTP `502 Bad Gateway`: `1`
- selected WARC records: `0`
- retained WARC records: `0`
- covered targets: `0`

The producer emitted:

- `status=FAIL`
- `result=COMMON_CRAWL_COVERAGE_INSUFFICIENT`

That producer label is not authoritative. Every query row represented an HTTP execution failure, not a successfully observed zero-result response. The independent reviewer therefore correctly rejected all 23 rows and returned:

- independent review status: `FAIL`
- review errors: `23`
- recomputed status: `FAIL`
- recomputed result label: `COMMON_CRAWL_COVERAGE_INSUFFICIENT`

Because the review itself failed, the recomputed coverage label is also non-authoritative. The only accepted conclusion is execution failure with retained evidence.

## Source-service interpretation boundary

This closeout does not reinterpret an HTTP `404` as a verified archive no-hit. Under the frozen evidence contract, a valid no-hit required a successfully completed and parseable index response. Attempt 1 did not produce such evidence.

The single HTTP `502` independently demonstrates that the package contains a service/transport failure and cannot be accepted as a clean coverage inventory even if future research changes the handling of HTTP `404` responses.

Any next internet-first design must use a separately reviewed access path that can produce an unambiguous, retained query result. It must not silently relax the evidence standard or rerun this workflow.

## Third-party safety and credit

No third-party code, package, saved webpage, crawler output, or dataset was committed by this run.

Common Crawl remained an archive carrier only. No Common Crawl response was accepted as source authority, and no official OKX response bytes were retained in this attempt.

Any future Common Crawl URL Index, CDX client, Parquet, DuckDB, Spark, Athena, or other third-party component must be separately reviewed for:

- exact origin and immutable version;
- license and redistribution obligations;
- network and data-access boundary;
- dependency and supply-chain risk;
- deterministic retention and independent verification;
- clear separation between archive carrier and official-source authority.

Unknown-license material remains research-only and must not be copied or executed.

## Safety state

- Common Crawl attempt 1: `CLOSED`
- rerun: `NOT_AUTHORIZED`
- direct OKX access: `NOT_AUTHORIZED`
- guessed URLs or broad crawl: `NOT_AUTHORIZED`
- article discovery/expansion: `NOT_AUTHORIZED`
- third full source-authority capture: `NOT_AUTHORIZED`
- economic implementation: `NOT_AUTHORIZED`
- economic data access: `NOT_AUTHORIZED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

`COMMON_CRAWL_PROBE_ATTEMPT_1_EVIDENCE_VALID` / `FINAL_COMMON_CRAWL_COVERAGE_DECISION_NOT_ACCEPTED` / `NO_RERUN` / `LIVE_FORBIDDEN`
