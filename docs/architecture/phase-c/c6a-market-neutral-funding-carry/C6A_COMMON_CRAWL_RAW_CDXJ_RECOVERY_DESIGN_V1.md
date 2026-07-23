# C6A Common Crawl Raw CDXJ Recovery Design V1

## Decision

Common Crawl probe attempt 1 is closed without rerun. Its retained evidence showed that all 23 requests to the public CDX query service failed at the HTTP layer, including one `502`, so neither a positive archive hit nor verified insufficient coverage was established.

The next admissible internet-first implementation is a bounded raw-index access path against `data.commoncrawl.org`. It reads the same Common Crawl CDXJ index from its published ZipNum files instead of calling the rate-limited query service.

This change implements and tests that path only. It does not authorize network execution.

## Scope

The inventory remains frozen to:

- seven exact locale-neutral official OKX Help Center URLs;
- 23 exact target/crawl pairs;
- the same event-adjacent Common Crawl releases used by the prior probe.

The probe performs only two kinds of byte-range read:

1. small windows from each crawl's plaintext `cluster.idx` secondary index;
2. exact compressed blocks from the selected `cdx-*.gz` shard.

It does not retrieve WARC records, page bodies, article lists, market data, account data, or any OKX endpoint.

## Raw ZipNum access method

Common Crawl documents that the CDXJ index is a sorted text index compressed into independently addressable gzip blocks, with `cluster.idx` acting as a secondary index. Each cluster line records the first CDXJ key in a block and the block's shard, byte offset, and byte length.

For each exact frozen URL, the implementation:

1. applies a deliberately narrow internal SURT transform valid only for the frozen ASCII `https://www.okx.com/help/...` URLs;
2. byte-range binary-searches `cluster.idx` for the predecessor of the URL's lowest possible timestamp;
3. retains enough adjacent cluster lines to prove the upper boundary;
4. retrieves no more than four exact gzip blocks;
5. requires each decompressed block's first CDXJ row to equal its cluster-index identity;
6. retains only exact URL-key, exact official URL, HTTP `200` rows with valid WARC locators in the same frozen crawl;
7. stops before fetching any WARC bytes.

A successfully executed no-hit is a valid raw-index finding. A transport, range, gzip, boundary, parse, or integrity failure is an execution failure and cannot be reported as a no-hit.

## Network and resource boundary

The implementation allows only HTTPS URLs on `data.commoncrawl.org` under:

- `/cc-index/collections/<crawl>/indexes/cluster.idx`
- `/cc-index/collections/<crawl>/indexes/cdx-<number>.gz`

It uses Python's standard library with an empty proxy handler and rejects proxy, cookie, and authorization environment state before network access.

Frozen limits include:

- 64 KiB cluster search windows;
- at most 32 cluster range requests per target/crawl query;
- at most four CDX gzip blocks per query;
- at most 2 MiB per CDX block;
- at most 32 exact rows per query;
- at least 0.5 seconds between uncached requests.

All unique responses are retained with URL, range, `Content-Range`, size, and SHA-256. Identical ranges are cached within the run.

## Independent review

The reviewer imports no producer, HTTP, binary-search, block-selection, or gzip execution code. From retained files it independently recomputes:

- the seven-target and 23-query matrix;
- the narrow SURT key for every target;
- all range-file hashes and protocol metadata;
- cluster-line identities and ordering;
- selected block hashes, line counts, and first-row binding;
- every exact CDXJ hit and WARC locator;
- producer counts, hit inventory, status, and result;
- all safety flags.

A failed execution may still have an independent-review PASS when the retained failure package is internally complete and correctly classified. That does not turn the failed execution into a valid access-path result.

## Third-party safety, licensing, and credit

No third-party executable package, crawler, saved webpage, or dataset is added.

Research and format references:

1. **Common Crawl CDXJ Index documentation and data bucket** — primary authority for the published index, ZipNum block organization, CDXJ fields, and HTTP byte-range retrieval.
2. **Ilya Kreymer / pywb ZipNum work** — acknowledged by Common Crawl as the origin of the index/query approach. Used as a format reference only; no pywb code is copied or executed.
3. **Common Crawl `whirlwind-python`**, Apache-2.0 — methodological reference showing the distinction between single-page CDXJ lookup and bulk URL Index analysis. No code copied.
4. **Internet Archive `surt` Python package**, AGPL-3.0 — explicitly not imported or copied. The project implements only a narrow, independently written transform for seven frozen ASCII OKX URLs and does not claim to be a general SURT implementation.
5. **Common Crawl Terms of Use** — any eventual execution remains subject to the current service and crawled-content terms.

Future adoption of any external component requires exact origin, immutable version, license, package hash or attestation, network boundary, and independent verification before authorization.

## Result meanings

`RAW_CDXJ_ACCESS_PATH_VERIFIED`

All 23 exact raw-index queries executed under the frozen protocol and the independent reviewer accepted the retained package. This proves only that the raw CDXJ access route is operational and records which exact URLs have matching CDX metadata. It does not prove GLOBAL page content or source authority and does not authorize WARC retrieval.

`RAW_CDXJ_ACCESS_PATH_EXECUTION_FAILED`

At least one frozen query did not complete under the protocol. The retained package may still be valid failure evidence, but no access-path viability decision is accepted and no retry is implied.

## Safety state

- network execution in this implementation PR: `NOT_AUTHORIZED`
- rerun of Common Crawl attempt 1: `NOT_AUTHORIZED`
- direct OKX access: `NOT_AUTHORIZED`
- WARC retrieval: `NOT_AUTHORIZED`
- article discovery/expansion: `NOT_AUTHORIZED`
- third full source-authority capture: `NOT_AUTHORIZED`
- economic implementation: `NOT_AUTHORIZED`
- economic data access: `NOT_AUTHORIZED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

`RAW_CDXJ_RECOVERY_IMPLEMENTED_NOT_AUTHORIZED` / `WARC_RETRIEVAL_NOT_AUTHORIZED` / `LIVE_FORBIDDEN`
