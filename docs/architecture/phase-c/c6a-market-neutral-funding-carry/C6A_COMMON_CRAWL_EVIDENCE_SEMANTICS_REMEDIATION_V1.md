# C6A Common Crawl Evidence-Semantics Remediation V1

## Purpose

This document tightens the bounded Common Crawl design merged in PR #79 before any network execution is authorized.

The original implementation correctly bounded hosts, exact URLs, response sizes, pacing, retained files, source-scope proof, and safety states. Independent review found one semantic ambiguity that must be removed first: a network or selected-record retrieval failure must never be reported as valid `COMMON_CRAWL_COVERAGE_INSUFFICIENT`.

## Correct result separation

A valid archive no-hit requires all of the following:

- the exact CDX request completed;
- the response was HTTP 200;
- the NDJSON parsed successfully;
- the exact query returned zero matching records.

Only that condition may contribute to a reviewed insufficient-coverage result.

The execution evidence is rejected when any of the following occurs:

- CDX transport failure or non-200 response;
- malformed or out-of-scope CDX response;
- selected WARC range retrieval failure;
- selected WARC decompression or parse failure;
- missing retained files;
- size or SHA-256 mismatch;
- query-matrix or selected-record mismatch;
- producer/reviewer verdict mismatch.

A successfully retrieved and retained record that proves to be regional, non-HTML, missing GLOBAL markers, or otherwise source-ineligible is different: it is a valid coverage finding and may lead to reviewed insufficient coverage without invalidating the execution package.

## Payload provenance reconciliation

A retained official body is usable only when these three values exist and match case-insensitively:

1. the Common Crawl CDX `digest`;
2. the WARC `WARC-Payload-Digest`;
3. an independently computed SHA-1/Base32 digest of the extracted official HTTP body.

The producer records all three values and a reconciliation verdict. The physically separate reviewer recomputes the body digest and independently reconciles them.

## Implementation boundary

The public runner now uses:

- `atos.c6a_common_crawl_probe_v2` for remediated execution semantics;
- `atos.c6a_common_crawl_probe_independent_v2` for remediated independent review.

The original modules remain available as the frozen protocol/helper layer. The v2 producer reuses only the bounded inventory, URL validators, HTTP/WARC primitives, retention helpers, and GLOBAL proof parser. The v2 reviewer imports only the original physically separate reviewer helpers and does not import producer, HTTP, WARC-parser, or execution code.

## Validation cases

Deterministic offline tests cover:

- complete official GLOBAL coverage PASS;
- successful exact CDX no-hit as reviewed coverage FAIL;
- CDX network failure as rejected evidence;
- selected WARC retrieval failure as rejected evidence;
- successfully retained regional page as valid coverage finding;
- payload-digest tampering as rejected evidence;
- proxy rejection before any network call.

## Third-party safety and credit

This remediation adds no third-party package, code, crawler output, dataset, or saved webpage. It continues to use only Python standard-library code and the provenance/licensing rules frozen in `C6A_COMMON_CRAWL_RECOVERY_DESIGN_V1.md`.

Unknown-license material remains research-only and is not copied. Common Crawl remains only an archive carrier; authority remains the independently verified official OKX response bytes embedded in a retained WARC record.

## Safety state

- Common Crawl network execution: `NOT_AUTHORIZED`
- retry: `NOT_AUTHORIZED`
- broad crawl or guessed URL expansion: `NOT_AUTHORIZED`
- article discovery/expansion: `NOT_AUTHORIZED`
- third full capture: `NOT_AUTHORIZED`
- economic implementation: `NOT_AUTHORIZED`
- economic data access: `NOT_AUTHORIZED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

`COMMON_CRAWL_EVIDENCE_SEMANTICS_REMEDIATED_NOT_AUTHORIZED` / `THIRD_FULL_CAPTURE_NOT_AUTHORIZED` / `LIVE_FORBIDDEN`
