# C6A Source-Authority Global Scope Recovery Design V1

## 1. Purpose

Recover a provable, reproducible **GLOBAL** official OKX announcement scope after capture attempt 2 silently followed a locale-neutral global URL to the United States Help Center.

This design covers source-jurisdiction identity, transport final-URL enforcement, page-content scope proof, independent review, and a bounded source-scope probe. It does not authorize a third full source-authority capture, economic implementation, economic data access, paper, shadow, private API, or live work.

## 2. Frozen authority jurisdiction

The intended announcement authority jurisdiction is:

`GLOBAL`

A locale-neutral request such as:

`https://www.okx.com/help/category/announcements`

or its frozen section/pagination equivalent must resolve to and retain the global OKX Help Center source universe. A regional or jurisdiction-specific catalog is not an equivalent substitute.

Examples of non-equivalent scopes include, without limitation:

- `/en-us/help/...`
- `/en-eu/help/...`
- regional hostnames such as `tr.okx.com`
- any other locale or jurisdiction whose category set or article universe differs from GLOBAL.

Locale language and authority jurisdiction are separate concepts. A future design may permit a translated presentation only when positive evidence proves that it exposes the same frozen global source universe; no such equivalence is assumed here.

## 3. Attempt-2 defect

Attempt 2 requested a locale-neutral global Help Center path. The GitHub runner received final URLs under `/en-us/help/...`. The implementation accepted one locale prefix, parsed nine pages and 121 items, and marked pagination complete within that United States catalog.

Official OKX pages show that the global and United States announcement universes differ materially. Complete regional pagination therefore cannot satisfy complete global pagination.

The implementation lacked:

1. a frozen jurisdiction field in the query inventory;
2. a request-specific rule prohibiting regional substitution for GLOBAL;
3. positive page-content evidence of jurisdiction;
4. an independent reviewer check for requested versus observed source scope;
5. a dedicated failure code for scope drift.

## 4. Required failure code

Introduce:

`FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT`

It must be emitted whenever any required source:

- resolves to an unapproved jurisdiction or locale path;
- uses an unapproved regional hostname;
- contains page evidence inconsistent with the frozen jurisdiction;
- lacks sufficient positive scope evidence;
- changes jurisdiction between pages;
- mixes pages or articles from different jurisdictional catalogs;
- cannot prove that a language-localized presentation is authority-equivalent to GLOBAL.

The failure must rank before catalog completeness, required-field, coverage, and transition failures because catalog completeness has no meaning until source scope is established.

## 5. Query-inventory additions

The frozen query inventory must add an explicit source-scope contract for every announcement catalog request:

```json
{
  "authority_jurisdiction": "GLOBAL",
  "requested_scope": {
    "host": "www.okx.com",
    "path_mode": "GLOBAL_LOCALE_NEUTRAL_HELP",
    "regional_substitution_allowed": false
  },
  "required_scope_proof": {
    "final_url": true,
    "page_content": true,
    "cross_page_consistency": true
  }
}
```

Exact schema names may change during implementation, but the semantics above are mandatory.

The inventory must remain pre-network and immutable for a validated execution SHA. No implementation may infer GLOBAL from an absent field.

## 6. Transport requirements

### 6.1 Initial request

The initial catalog request must be an approved HTTPS OKX GLOBAL Help Center URL with no credentials, user account state, private endpoint, or economic data.

### 6.2 Redirect handling

Every redirect must be validated before follow.

For a request frozen as `authority_jurisdiction=GLOBAL`:

- a redirect to `/en-us/help/...`, `/en-eu/help/...`, or another unapproved locale/jurisdiction path must fail before the redirected content is accepted;
- a redirect to a regional OKX hostname must fail;
- a redirect that changes the catalog category/section identity must fail;
- the complete redirect chain must be retained as evidence.

The implementation must not silently normalize a regional final URL back to a global canonical URL.

### 6.3 No guessed bypass

Do not guess or hardcode a force-global cookie, geolocation header, language header, browser fingerprint, query parameter, or undocumented endpoint.

A candidate request profile may be used only after a separately authorized bounded source-scope probe demonstrates that it reproducibly returns the intended global source from a GitHub-hosted runner.

## 7. Positive page-content scope proof

Final URL alone is insufficient. Every retained catalog page must include independently reviewable positive scope evidence.

Required proof should include a structured `scope_proof` record containing at least:

- requested jurisdiction;
- observed final URL and host;
- redirect chain;
- page title or heading evidence;
- visible locale/jurisdiction selector evidence when present;
- category-set fingerprint;
- declared article range, total, and terminal page;
- raw-source byte path and SHA-256;
- parser version;
- verdict `PASS` or `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT`.

The implementation must define a conservative GLOBAL proof predicate from retained official bytes. Absence or ambiguity fails closed.

No fixed article total may be hardcoded because the catalog changes over time. The proof must establish scope identity and internally consistent pagination at capture time, not require a historical constant.

## 8. Cross-page consistency

All catalog pages in one package must prove the same jurisdiction and catalog identity.

The reviewer must reject:

- jurisdiction changes between page 1 and later pages;
- total or terminal-page drift that cannot be explained by a bounded capture-time consistency contract;
- duplicate or missing page ranges;
- category-set changes indicating a regional or product-scope substitution;
- article URLs that leave the approved scope;
- mixtures of global and regional article URLs without explicit authority-equivalence proof.

The capture design must define how to handle a live catalog changing during pagination. At minimum, all pages must be captured within a bounded window and the declared range/total relationship must remain self-consistent. Otherwise fail closed and retain all evidence.

## 9. Independent review requirements

Independent review must not import or trust the production scope verdict.

It must recompute from retained bytes and records:

1. requested jurisdiction from the frozen inventory;
2. observed final URL/host and redirect chain;
3. positive page-content scope evidence;
4. cross-page jurisdiction consistency;
5. article URL scope;
6. complete failure set and primary failure.

It must compare its recomputed scope verdict with the production result. Any mismatch adds `FAIL_INDEPENDENT_REVIEW_MISMATCH` and prevents a final authoritative decision.

A package can be artifact-valid while its source-scope decision fails. These states must remain distinct.

## 10. Required tests before network work

Add deterministic fixtures and tests for:

- global request with global final URL and positive GLOBAL page evidence: PASS;
- global request redirected to `/en-us/help/...`: `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT`;
- global request redirected to `/en-eu/help/...`: failure;
- global request redirected to a regional hostname: failure;
- global final URL with page content identifying a regional catalog: failure;
- mixed-jurisdiction pages: failure;
- absent/ambiguous scope proof: failure;
- article URL outside approved scope: failure;
- production/reviewer scope mismatch: independent review failure;
- unchanged artifact-integrity and safety closures.

Tests must use retained/synthetic fixtures only and ordinary CI. Freqtrade Validation is not applicable.

## 11. Bounded source-scope probe

Before any third full source-authority capture, a separate one-page source-scope probe is required.

### 11.1 Probe purpose

Determine whether a GitHub-hosted runner can reproducibly retrieve the intended global official Help Center source and which documented/request-transparent profile produces it.

### 11.2 Probe limits

- public OKX Help Center pages only;
- page 1 only;
- no article expansion;
- no Wayback queries;
- no instruments endpoint;
- no candles, funding, order books, account, credentials, private API, trading, paper, shadow, or live access;
- a small, frozen candidate request-profile matrix;
- one request per candidate plus only bounded transport retries;
- complete raw bytes, headers, redirect chain, timing, status, final URL, hashes, and scope proofs retained;
- artifact uploaded even when every candidate fails;
- workflow success remains separate from probe verdict;
- one-shot workflow deleted after evidence freeze.

### 11.3 Candidate profiles

Candidate profiles must be defined and reviewed before execution. They may vary only transparent HTTP request metadata such as documented `Accept-Language` or a standard browser User-Agent. They must not include guessed cookies, geolocation spoofing, credentials, hidden browser automation, proxies, residential routing, or undocumented bypasses.

The matrix must include the current minimal ATOS profile as a control.

### 11.4 Probe PASS

The probe passes only when at least one predeclared candidate:

- receives the intended GLOBAL scope;
- passes final-URL and positive page-content proof;
- is reproducible within the same bounded probe contract;
- does not rely on credentials, private state, prohibited routing, or undocumented circumvention;
- is independently recomputed as PASS from retained evidence.

If no candidate passes, the probe result is an authoritative probe FAIL. That does not authorize adding more candidates or running a full capture.

## 12. Authorization sequence

The required sequence is:

1. merge this recovery design and corrected attempt-2 closeout;
2. implement scope schema, transport enforcement, parser proof, independent review, and fixture tests;
3. validate exact head and merge ref in ordinary CI;
4. perform independent code review;
5. separately authorize one bounded source-scope probe;
6. freeze and independently review its artifact;
7. only after probe PASS, design and separately authorize a third full source-authority capture.

No step authorizes the next automatically.

## 13. Exit criteria

Global-scope recovery implementation is ready for a probe authorization only when:

- explicit GLOBAL jurisdiction is frozen in the inventory;
- regional substitutions are rejected for global requests;
- page-content scope proof is retained and independently recomputable;
- `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT` is integrated into production and independent failure priority;
- deterministic scope fixtures pass;
- exact-head CI and merge-ref review pass;
- no one-shot workflow or network execution is included in the implementation PR;
- all economic and trading closures remain false/closed/forbidden.

## 14. Safety state

- Economic implementation: `NOT_AUTHORIZED`
- Economic data access: `NOT_AUTHORIZED`
- Third full capture: `NOT_AUTHORIZED`
- Source-scope probe: `NOT_AUTHORIZED_UNTIL_SEPARATE_PR`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Private API: `FORBIDDEN`
- Live: `LIVE_FORBIDDEN`