# C6A GLOBAL Source-Scope Probe Closeout V1

## Status

`PROBE_EVIDENCE_VALID` / `PROBE_RESULT_FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT` / `THIRD_FULL_CAPTURE_NOT_AUTHORIZED` / `LIVE_FORBIDDEN`

This document freezes the result of the single bounded public Help Center source-scope probe authorized by PR #72. It does not authorize a third full capture, economic implementation, economic data access, paper, shadow, private API, or live work.

## Immutable execution identity

- Workflow run: `30023117329`
- Job: `89260671766`
- Trigger/main SHA: `1b9e7abcb294abda271486859cd8d18568c90354`
- Executed probe implementation SHA: `cff1c83b91d10223634b4485360d9311b4640cc6`
- Validated probe merge ref: `refs/pull/71/merge@196eb54a4c48e63e55b1a5900efa7180f7a76efd`
- Run attempt: `1`
- Artifact ID: `8570114295`
- Artifact name: `c6a-global-source-scope-probe-30023117329`
- Artifact ZIP digest: `sha256:6d89d2d7ad970449ce0d176b574aeb4934868c15c8c9d3ca958edf8c879a3c34`
- Artifact expiry: `2026-10-21T16:00:02Z`

The job completed successfully. The rerun guard, exact checkout, execution-identity verification, bounded probe, manifest construction, artifact upload, summary, and post-upload integrity enforcement all passed.

## Independent artifact verification

The downloaded ZIP digest reproduced the GitHub artifact digest exactly.

- Outer bundle: `13/13` files present and covered by `bundle-manifest.json`
- Inner probe package: `10/10` files present and covered by `probe/manifest.json`
- Missing files: `0`
- Extra files: `0`
- Size mismatches: `0`
- SHA-256 mismatches: `0`
- Independent review status: `PASS`
- Independent recomputed probe status: `FAIL`

The retained package is therefore valid evidence of the probe outcome.

## Frozen probe outcome

Production and independent review agree on:

- Probe status: `FAIL`
- Probe result: `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT`
- Reproducible passing profiles: none
- Implementation authorized: `false`
- Economic data access authorized: `false`
- Third full capture authorized: `false`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

All eight predeclared candidates completed with HTTP 200 after the same redirect sequence:

1. locale-neutral GLOBAL request:
   `https://www.okx.com/help/section/announcements-latest-announcements/page/1`
2. HTTP 302 to:
   `https://www.okx.com/en-us/help/section/announcements-latest-announcements/page/1`
3. HTTP 301 to:
   `https://www.okx.com/en-us/help/section/announcements-latest-announcements`

The following A/B profiles all failed identically:

- `control-atos-minimal`
- `browser-neutral-en`
- `browser-en-us`
- `browser-en-gb`

Changing transparent User-Agent or Accept-Language headers did not produce a locale-neutral GLOBAL page. The failure is deterministic across both replicates of every profile.

## Decision

The locale-neutral **latest-announcements section URL is not a usable GLOBAL source from the current GitHub-hosted runner path**. This is a source-jurisdiction result, not an implementation/runtime failure.

The project must not:

- reinterpret the `/en-us/` result as GLOBAL;
- rerun this one-shot workflow;
- add more guessed User-Agent or Accept-Language variants;
- use cookies, undocumented geolocation headers, proxies, or routing circumvention;
- authorize a third full capture from this URL;
- proceed to economic implementation.

The temporary workflow is deleted in the same closeout change.

## Next admissible step

A new separately reviewed bounded probe may evaluate a different **official locale-neutral OKX source surface**, starting with the official GLOBAL announcements category root:

`https://www.okx.com/help/category/announcements`

That probe must remain page/root-only, preserve raw bytes and redirect evidence, independently recompute jurisdiction, and authorize no article expansion, archive access, economic data, or third full capture. A PASS would only validate that source surface; it would not itself authorize a full capture.
