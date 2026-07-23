# C6A Source-Authority Capture Attempt 2 Closeout V1

## Decision

Capture attempt 2 is accepted as an evidence-valid, independently reviewed, authoritative **Gate FAIL**.

- Gate status: `FAIL`
- Primary result: `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`
- Independent package review: `PASS`
- Integrity state: `FINAL_PACKAGE_AND_INDEPENDENT_REVIEW_VERIFIED`
- Economic implementation authorized: `false`
- Economic data access authorized: `false`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

This closeout does not authorize a third capture attempt, economic implementation, market-data acquisition, private API access, paper trading, shadow trading, or live trading.

## Immutable execution identity

- Workflow run: `30010713956`
- Job: `89217780598`
- Job name: `exact remediated public metadata source capture`
- Run attempt: `1`
- Trigger branch: `main`
- Trigger SHA: `e8fa04bb0e99c0fd8fa2d86b6f804a34455a2236`
- Executed implementation SHA: `bcb126d63436f253aad1aeac695ad325ad316899`
- Validated remediation merge ref: `refs/pull/65/merge@eda36c041e8528c3f7d728d41d7863c62e9a00d9`

The workflow completed successfully. Its success means the bounded capture, packaging, upload, and post-upload integrity enforcement completed; it does not mean the source-authority Gate passed.

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

## Successful remediation evidence

Attempt 2 proves that the attempt-1 implementation defects were corrected.

### Locale-prefixed official Help Center paths

The official announcement catalog was parsed completely instead of failing on `/en-us/help/...` links.

- Catalog pages retained: `9`
- Catalog items retained: `121`
- Duplicate catalog URLs: none
- Terminal-page proof: `PASS`
- Declared terminal page: `9`
- Frozen unused page capacity: `241`

The retained package contains raw and decoded catalog pages 1 through 9 and exact official locale-prefixed article URLs.

### Independent diagnostic recomputation

The independent review consumed the retained attempt diagnostics and independently recomputed the archive failure.

- Attempt diagnostic events: `4`
- Diagnostic review: `PASS`
- Independently recomputed diagnostic failure: `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`
- Complete recorded failure set equals complete recomputed failure set
- Recomputed primary result equals recorded primary result
- Independent review errors: none

Therefore attempt 2 has no unresolved implementation/reviewer mismatch of the kind that invalidated attempt 1.

## Accepted authoritative failure

The complete recorded and independently recomputed failure set is:

1. `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`
2. `FAIL_REQUIRED_FIELD_MISSING`
3. `FAIL_UNCOVERED_INTERVAL`
4. `FAIL_TRANSITION_WINDOW_UNPROVEN`

The primary failure is `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`.

Four frozen Wayback CDX archive-index requests failed closed:

- BTC-USDT spot: empty CDX response;
- ETH-USDT spot: empty CDX response;
- BTC-USDT-SWAP: empty CDX response;
- ETH-USDT-SWAP: connection refused after three bounded attempts.

No archived official instrument-response index was accepted. No unsupported backward projection, continuity projection, inferred switch time, union state, current-only projection, third-party source, credentialed endpoint, private account endpoint, or economic endpoint was used.

## Retained positive evidence

The package retains `14` eligible official OKX source objects:

- nine complete official announcement catalog pages;
- five known official transition notices:
  - ETH-USDT-SWAP, 2024-04-18;
  - BTC-USDT-SWAP, 2024-04-25;
  - ETH-USDT-SWAP original notice, 2024-12-18;
  - ETH-USDT-SWAP postponed notice, 2025-01-09;
  - BTC-USDT-SWAP, 2025-01-22.

Retained-source independent review: `PASS`.

These notices prove that relevant announced changes existed, but they do not independently establish complete inclusive/exclusive effective metadata intervals for all four instruments across the full frozen authority period.

## Missing authority and fail-closed consequence

- Emitted metadata states: `0`
- Emitted transition proofs: `0`
- Emitted coverage rows: `0`
- Required frozen transition windows: `4`
- Required transition windows proven: `0`

The package correctly refused to turn point-in-time or announcement evidence into complete interval authority. Consequently, the C6A source-authority Gate remains closed.

## Final classification

- `CAPTURE_ATTEMPT_2_EVIDENCE_VALID`
- `CAPTURE_ATTEMPT_2_INDEPENDENT_REVIEW_PASS`
- `SOURCE_AUTHORITY_GATE_AUTHORITATIVE_FAIL`
- `FAIL_ARCHIVE_DECODING_OR_PROVENANCE`
- `C6A_FINAL_GATE_PASS_NOT_ESTABLISHED`
- `C6A_ECONOMIC_IMPLEMENTATION_NOT_AUTHORIZED`
- `C6A_ECONOMIC_DATA_ACCESS_NOT_AUTHORIZED`
- `PAPER_CLOSED`
- `SHADOW_CLOSED`
- `LIVE_FORBIDDEN`

## Workflow lifecycle

The temporary attempt-2 workflow served its single authorized purpose. It must be deleted in the same closeout change so it cannot trigger again from future edits.

Any future source-authority work requires a new planning and design decision based on allowed official evidence. A third capture attempt is not authorized by this document.