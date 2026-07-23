# C6A GLOBAL Category Source-Scope Probe Closeout V1

## Decision

The single authorized bounded probe of the official locale-neutral OKX announcements category root completed with valid packaged evidence and a reproduced fail-closed result:

`FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT`

The result is final for this execution. It is not a runtime failure, it must not be rerun, and it does not authorize a third full source-authority capture.

## Immutable execution identity

- workflow run: `30036171380`
- job: `89304578790`
- run attempt: `1`
- trigger/main SHA: `773598ef234f237e900a87c64f1a7a7ccdcab121`
- executed implementation SHA: `9337ad3813c007883fe2017f9c73cf367b35cf8a`
- validated implementation merge ref: `refs/pull/74/merge@0d2010a84a69b699da4c8c2a7cf51e01403440d1`
- requested surface: `https://www.okx.com/help/category/announcements`

## Artifact identity and independent integrity verification

- artifact ID: `8575328946`
- artifact name: `c6a-global-category-scope-probe-30036171380`
- artifact expiry: `2026-10-21T19:00:26Z`
- GitHub-reported ZIP digest: `sha256:be123ccacf03b752017603749a079bf5470e5a4604939951bd48127773b43166`
- independently reproduced ZIP digest: `sha256:be123ccacf03b752017603749a079bf5470e5a4604939951bd48127773b43166`
- outer bundle manifest: `13/13` files verified
- inner probe manifest: `10/10` files verified
- missing files: none
- extra files: none
- size mismatches: none
- SHA-256 mismatches: none

The retained execution identity, producer result, physically separate independent review, raw page bytes, redirects, headers, logs, and both manifests are internally consistent.

## Reproduced result

- workflow conclusion: `success`
- production probe status: `FAIL`
- production result: `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT`
- independent review status: `PASS`
- independently recomputed probe status: `FAIL`
- reproducible passing profiles: none

All eight frozen candidates produced the same outcome across both A/B replicates:

| Profile | Replicates | HTTP result | Final URL | Scope verdict |
| --- | --- | --- | --- | --- |
| `control-atos-minimal` | A, B | `302` then `200` | `https://www.okx.com/en-us/help/category/announcements` | `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT` |
| `browser-neutral-en` | A, B | `302` then `200` | `https://www.okx.com/en-us/help/category/announcements` | `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT` |
| `browser-en-us` | A, B | `302` then `200` | `https://www.okx.com/en-us/help/category/announcements` | `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT` |
| `browser-en-gb` | A, B | `302` then `200` | `https://www.okx.com/en-us/help/category/announcements` | `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT` |

The locale-neutral category root is therefore not a usable GLOBAL authority surface from the current GitHub-hosted runner execution path.

## Combined source-surface conclusion

This result confirms the previous bounded probe of the locale-neutral latest-announcements section. Both independently tested official locale-neutral entry points deterministically resolve to the US regional Help Center from the current GitHub-hosted runner path:

1. `/help/section/announcements-latest-announcements/page/1`
2. `/help/category/announcements`

The failure is an execution-venue/source-scope incompatibility, not a parser defect and not evidence that the US regional catalog is authority-equivalent to the intended GLOBAL catalog.

## Closed approaches

The following are not admissible follow-ups:

- rerunning either completed probe;
- trying additional guessed `Accept-Language` or user-agent combinations;
- adding cookies, authorization headers, proxy state, DNS overrides, undocumented endpoints, or routing circumvention;
- silently accepting `/en-us/` as GLOBAL;
- starting a third full capture before GLOBAL scope is independently proven;
- using the valid artifact package to claim source-authority Gate PASS.

## Next admissible work

The next work item is an offline-reviewed execution-venue handoff design, not another network probe. It must:

1. preserve the existing immutable inventory, parser, independent reviewer, manifests, and safety states;
2. require a separately authorized execution venue capable of obtaining the locale-neutral GLOBAL surface without cookies, proxies, routing tricks, or source substitution;
3. bind the venue identity and network-observed final URLs into the retained evidence package;
4. fail closed if the venue still resolves to any locale-prefixed or regional Help Center;
5. remain pre-economic and non-authorizing until a separately reviewed one-shot execution is approved.

No execution venue is authorized by this closeout.

## Safety state

- source-authority Gate: `NOT_ACCEPTED`
- third full capture: `NOT_AUTHORIZED`
- economic implementation: `NOT_AUTHORIZED`
- economic data access: `NOT_AUTHORIZED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

`PROBE_RESULT_FROZEN` / `EXECUTION_VENUE_REDESIGN_REQUIRED` / `LIVE_FORBIDDEN`
