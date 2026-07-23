# C6A Source-Authority Capture Attempt 2 Closeout V1

## Corrected decision

Capture attempt 2 is accepted as an evidence-valid package whose retained-package independent review passed, but its final source-authority Gate decision is **not accepted**.

The workflow requested the global OKX Help Center path, but the GitHub runner was redirected to the United States Help Center under `/en-us/help/...`. The implementation accepted that regional substitution and then treated the resulting nine-page, 121-item United States catalog as the complete catalog for the intended authority scope.

Official OKX pages observed after the run establish that these are materially different source universes:

- global announcements: `https://www.okx.com/help/category/announcements`, currently thousands of articles and more than 200 pages;
- United States announcements: `https://www.okx.com/en-us/help/category/announcements`, a much smaller jurisdiction-specific catalog;
- attempt 2 retained the United States scope: 9 pages and 121 items.

Therefore the package is internally consistent but externally scoped to the wrong jurisdiction. The package-level result `FAIL_ARCHIVE_DECODING_OR_PROVENANCE` cannot be promoted to the final authoritative C6A source-authority decision because the independently reviewed package did not contain the intended global announcement universe.

- Packaged Gate status: `FAIL`
- Packaged primary result: `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`
- Retained-package independent review: `PASS`
- Artifact integrity: `FINAL_PACKAGE_AND_INDEPENDENT_REVIEW_VERIFIED`
- Corrected final decision: `FINAL_SOURCE_AUTHORITY_GATE_DECISION_NOT_ACCEPTED`
- Corrected defect: `SOURCE_AUTHORITY_SCOPE_DRIFT`
- Economic implementation authorized: `false`
- Economic data access authorized: `false`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This closeout does not authorize a third full capture attempt, economic implementation, market-data acquisition, private API access, paper trading, shadow trading, or live trading.

## Immutable execution identity

- Workflow run: `30010713956`
- Job: `89217780598`
- Job name: `exact remediated public metadata source capture`
- Run attempt: `1`
- Trigger branch: `main`
- Trigger SHA: `e8fa04bb0e99c0fd8fa2d86b6f804a34455a2236`
- Executed implementation SHA: `bcb126d63436f253aad1aeac695ad325ad316899`
- Validated remediation merge ref: `refs/pull/65/merge@eda36c041e8528c3f7d728d41d7863c62e9a00d9`

The workflow completed successfully. Its success means the bounded capture, packaging, upload, and post-upload integrity enforcement completed; it does not establish correct jurisdictional scope or a source-authority Gate PASS/FAIL.

## Artifact identity

- Artifact ID: `8564979748`
- Artifact name: `c6a-source-authority-attempt-2-30010713956`
- Artifact size: `277266` bytes
- Artifact expiry: `2026-10-21T13:19:34Z`
- GitHub artifact digest: `sha256:57932ceffa3c4e84d5a46556132650eca5bbe9b2b67e58efff17f7fb25c39c1c`

Independent local verification reproduced the same ZIP SHA-256 digest.

## Package integrity verification

The retained artifact was downloaded and checked independently.

- Outer bundle manifest: `46/46` files present
- Outer file sizes and SHA-256 values: exact match
- Outer missing files: none
- Outer extra files: none
- Inner package manifest: `43/43` files present
- Inner file sizes and SHA-256 values: exact match
- Inner missing files: none
- Inner extra files: none

The outer manifest retained:

- implementation SHA `bcb126d63436f253aad1aeac695ad325ad316899`;
- validated merge ref `refs/pull/65/merge@eda36c041e8528c3f7d728d41d7863c62e9a00d9`;
- trigger SHA `e8fa04bb0e99c0fd8fa2d86b6f804a34455a2236`;
- run ID `30010713956`;
- run attempt `1`;
- `implementation_authorized=false`;
- `economic_data_access_authorized=false`;
- `live_state=LIVE_FORBIDDEN`.

Artifact integrity remains accepted. The correction concerns source scope, not artifact authenticity.

## Remediation evidence that remains valid

Attempt 2 proves that the two attempt-1 implementation defects were corrected within the retained package.

### Locale-prefixed parsing

The parser no longer failed merely because the server returned `/en-us/help/...` article links.

- Catalog pages retained: `9`
- Catalog items retained: `121`
- Duplicate catalog URLs: none
- Terminal-page proof within the retained United States catalog: `PASS`
- Declared terminal page within that catalog: `9`

This demonstrates parser functionality, but it does not prove that a locale-prefixed regional catalog is interchangeable with the intended global source.

### Independent diagnostic recomputation

The independent review consumed the retained attempt diagnostics and independently recomputed the archive failure.

- Attempt diagnostic events: `4`
- Diagnostic review: `PASS`
- Independently recomputed diagnostic failure: `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`
- Complete recorded failure set equals complete recomputed failure set
- Recomputed primary result equals recorded primary result
- Independent review errors: none

This establishes internal package agreement. The reviewer did not independently validate global-versus-regional source scope, so its PASS does not cure the scope defect.

## Scope-drift finding

The frozen request inventory used a global, locale-neutral catalog URL. During execution, the final URLs and article URLs were under `/en-us/help/...`. The transport and parser allowed one locale prefix but did not require proof that the returned source represented the frozen global authority jurisdiction.

The distinction is material:

- the global catalog exposes many additional categories and thousands of announcements;
- the United States catalog exposes a restricted jurisdiction-specific category set and a much smaller item universe;
- complete pagination of the United States catalog is not complete pagination of the global catalog;
- a fail-closed source-authority result must be based on the frozen intended source universe, not a silently substituted regional universe.

The correct defect classification is `SOURCE_AUTHORITY_SCOPE_DRIFT`. A future implementation must reject an unapproved regional final URL for a global request and must retain positive page-content evidence of the intended jurisdiction before catalog completeness can pass.

## Packaged failure retained as non-final evidence

Within the incorrectly scoped package, the recorded and independently recomputed failure set was:

1. `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`
2. `FAIL_REQUIRED_FIELD_MISSING`
3. `FAIL_UNCOVERED_INTERVAL`
4. `FAIL_TRANSITION_WINDOW_UNPROVEN`

Four frozen Wayback CDX archive-index requests failed closed:

- BTC-USDT spot: empty CDX response;
- ETH-USDT spot: empty CDX response;
- BTC-USDT-SWAP: empty CDX response;
- ETH-USDT-SWAP: connection refused after three bounded attempts.

No archived official instrument-response index was accepted. No unsupported backward projection, continuity projection, inferred switch time, union state, current-only projection, third-party source, credentialed endpoint, private account endpoint, or economic endpoint was used.

These findings remain valid observations about this package, but they are not the accepted final C6A source-authority Gate decision.

## Retained positive evidence

The package retains `14` eligible official OKX source objects:

- nine complete United States announcement catalog pages;
- five known official transition notices:
  - ETH-USDT-SWAP, 2024-04-18;
  - BTC-USDT-SWAP, 2024-04-25;
  - ETH-USDT-SWAP original notice, 2024-12-18;
  - ETH-USDT-SWAP postponed notice, 2025-01-09;
  - BTC-USDT-SWAP, 2025-01-22.

Retained-source integrity review: `PASS`.

These notices prove that relevant announced changes existed, but they do not independently establish complete inclusive/exclusive effective metadata intervals for all four instruments across the full frozen authority period.

## Missing authority and fail-closed consequence

- Emitted metadata states: `0`
- Emitted transition proofs: `0`
- Emitted coverage rows: `0`
- Required frozen transition windows: `4`
- Required transition windows proven: `0`

No economic work can proceed. The source-authority stage remains unresolved rather than authoritatively failed on the basis of attempt 2.

## Corrected final classification

- `CAPTURE_ATTEMPT_2_EVIDENCE_VALID`
- `CAPTURE_ATTEMPT_2_INDEPENDENT_REVIEW_PASS_WITHIN_RETAINED_PACKAGE`
- `SOURCE_AUTHORITY_SCOPE_DRIFT`
- `FINAL_SOURCE_AUTHORITY_GATE_DECISION_NOT_ACCEPTED`
- `C6A_FINAL_GATE_PASS_NOT_ESTABLISHED`
- `C6A_ECONOMIC_IMPLEMENTATION_NOT_AUTHORIZED`
- `C6A_ECONOMIC_DATA_ACCESS_NOT_AUTHORIZED`
- `THIRD_FULL_CAPTURE_NOT_AUTHORIZED`
- `PAPER_CLOSED`
- `SHADOW_CLOSED`
- `LIVE_FORBIDDEN`

## Workflow lifecycle

The temporary attempt-2 workflow has been deleted from `main` and cannot trigger again from future edits.

Any future source-authority work requires the separately reviewed global-scope recovery design. A third full capture attempt is not authorized by this document.