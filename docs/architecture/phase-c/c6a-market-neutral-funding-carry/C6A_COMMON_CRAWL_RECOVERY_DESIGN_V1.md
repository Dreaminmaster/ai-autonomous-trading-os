# C6A Common Crawl Official-Source Recovery Design V1

## Decision

The GitHub-hosted runner has twice reproduced the same source-scope incompatibility: both tested locale-neutral OKX Help Center entry points resolve to the US regional Help Center. Repeating direct OKX requests from that venue is closed.

The next admissible internet-first step is a bounded Common Crawl coverage probe. It asks whether Common Crawl retained exact official OKX GLOBAL response bytes for:

1. the locale-neutral announcements category;
2. locale-neutral latest-announcements page 1;
3. the five already-known BTC/ETH minimum-order notices required by the frozen transition windows.

This is an archive-coverage inventory only. It does not authorize a third full source-authority capture, article discovery/expansion, economic implementation, economic data access, paper, shadow, private API, or live work.

## Authority and carrier distinction

Common Crawl is only the archive carrier. It is not treated as the source authority.

A record is usable only when the retained WARC contains an official HTTP 200 `text/html` response whose:

- `WARC-Target-URI` is the exact frozen locale-neutral `https://www.okx.com/help/...` URL;
- HTML canonical URL is the same exact official URL;
- `og:url`, when present, does not conflict;
- embedded OKX page state explicitly identifies `siteList: ["OKX_GLOBAL"]`;
- target-specific title/content markers are present;
- no locale-prefixed or regional Help Center is substituted.

CDX metadata, a third-party parser output, a search-engine snippet, or an unverified copied dataset cannot satisfy this proof by itself.

## Frozen query inventory

The committed inventory contains seven exact official URLs and 23 exact URL/crawl-index pairs.

The crawl indexes are deliberately limited to event-adjacent or periodic snapshots:

- April 2024 notices: `CC-MAIN-2024-18`, `CC-MAIN-2024-22`, `CC-MAIN-2024-26`;
- December 2024 / January 2025 notices: `CC-MAIN-2024-51`, `CC-MAIN-2025-05`, `CC-MAIN-2025-08`, `CC-MAIN-2025-13`;
- catalog scope samples: selected 2024 and 2025 crawls.

Each CDX request uses:

- exact URL matching;
- HTTP status `200` filter;
- at most one selected WARC record per query;
- sequential execution with at least one second between requests;
- a descriptive project user agent;
- no proxy, cookie, authorization, account, or OKX session state.

## Network boundary

The implementation can contact only:

- `https://index.commoncrawl.org/<CC-MAIN-YYYY-NN>-index`
- `https://data.commoncrawl.org/crawl-data/CC-MAIN-.../*.warc.gz`

The index response is bounded to 5 MB. A WARC range is bounded to 10 MB and must return HTTP `206` with the exact CDX-declared byte length.

The HTTP client installs an empty proxy handler and also rejects non-empty proxy, cookie, or authorization environment variables before any request.

It never contacts OKX directly.

## Retained evidence

The probe retains:

- canonical inventory snapshot and digest;
- every raw CDX NDJSON response;
- exact query URL, headers, status, and hash;
- selected CDX row;
- exact WARC filename, offset, length, and range;
- compressed WARC member;
- decompressed WARC record;
- extracted official OKX HTTP body;
- all byte sizes and SHA-256 values;
- producer record metadata;
- aggregate result;
- physically separate independent review;
- complete manifest.

A no-hit or incomplete-coverage outcome is a valid reviewed result, not a runtime failure.

## Independent review

The independent reviewer imports no producer, HTTP, WARC, or parser code. It independently:

- reconstructs the exact target/crawl query matrix;
- validates Common Crawl index and data host boundaries;
- verifies raw index, compressed WARC, decompressed WARC, and official body hashes;
- reconciles metadata files with aggregate rows;
- re-parses canonical and `og:url`;
- independently requires the explicit `OKX_GLOBAL` marker;
- independently checks target-specific markers;
- recomputes covered and missing targets;
- recomputes the final coverage verdict;
- verifies all safety flags.

## Result meanings

`COMMON_CRAWL_OFFICIAL_BYTES_AVAILABLE`

All seven frozen targets have at least one independently verified official GLOBAL response in the bounded crawl inventory. This proves only that Common Crawl is a viable carrier for a separately designed source-authority recovery capture.

`COMMON_CRAWL_COVERAGE_INSUFFICIENT`

At least one frozen target lacks independently verified official GLOBAL bytes in this bounded inventory. The retained evidence remains valid, but it does not authorize broad crawling, guessed URLs, or a third full capture.

Neither result equals source-authority Gate PASS.

## External research, safety, licensing, and credit

No third-party executable code, package, crawler output, or saved HTML is vendored by this change. The implementation is written with the Python standard library and consumes only the official Common Crawl service during a separately authorized run.

Research references:

1. **Common Crawl official documentation** — CDX URL Index, WARC storage, HTTP range access, and responsible access guidance. This defines the archive protocol and remains the primary technical authority.
2. **DIYgod/RSSHub**, commit `0fafcbba7a99c9b9b0461f8a5376812e96d46c86`, OKX route, GNU Affero General Public License v3.0 (AGPL-3.0). Used only as a methodological reference confirming that OKX Help Center pages expose announcement metadata through `__app_data_for_ssr__`; no code copied.
3. **lowweihong/crypto_exchange_news_crawler**, commit `eaf437d48e3eb461e9a33d96a73004fd8b43c739`, declared MIT in `setup.py`. Used only as a methodological reference for the same public SSR structure; no code or output copied.
4. **Antoo1/test_task_okx_news_parser**, commit `c4dd6ee2d21bf9ae7ecd346b52db3d11cabb33c3`. A committed historical fixture exposed the research clue `siteList: ["OKX_GLOBAL"]`. Its license was not relied upon and its HTML was not copied, vendored, or used as runtime data. Tests use independently created minimal synthetic HTML.

Any future use of third-party data must separately record origin URL, immutable commit/object identity, license/terms, retrieval time, hash, transformation history, and independent verification. Unclear-license content remains research-only.

## Safety state

- network execution in this implementation PR: `NOT_AUTHORIZED`
- article discovery/expansion: `NOT_AUTHORIZED`
- third full capture: `NOT_AUTHORIZED`
- economic implementation: `NOT_AUTHORIZED`
- economic data access: `NOT_AUTHORIZED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

`COMMON_CRAWL_PROBE_IMPLEMENTED_NOT_AUTHORIZED` / `THIRD_FULL_CAPTURE_NOT_AUTHORIZED` / `LIVE_FORBIDDEN`
