# C6A Execution-Venue Preflight Design V1

## Purpose

Both reviewed GitHub-hosted probes of the official locale-neutral OKX Help Center resolved deterministically to the US regional Help Center. Continuing to vary URLs or headers inside the same execution venue would not produce new authority evidence.

This design prepares the next admissible boundary: one separately authorized, bounded GLOBAL category-root preflight on a local user-controlled or self-hosted execution venue.

It does not authorize that preflight, a third full source-authority capture, article expansion, economic implementation, economic data access, paper, shadow, private API, or live work.

## Required sequence

1. Merge and freeze this implementation after ordinary CI and exact merge-ref review.
2. Select a separately controlled execution venue.
3. Verify that no proxy, cookie, authorization, or proxy-authorization environment state is present.
4. Authorize exactly one invocation of the venue-preflight runner.
5. Run only the official locale-neutral category root:
   `https://www.okx.com/help/category/announcements`
6. Retain the venue attestation, eight frozen A/B candidate results, raw bytes, redirects, headers, producer result, existing physically separate category-probe review, venue-specific independent review, and manifest.
7. Return the package for independent review.
8. Stop after the bounded preflight regardless of PASS or FAIL.

A preflight PASS proves only that the selected venue can observe the locale-neutral GLOBAL category surface. It does not authorize article expansion or the full source-authority capture.

## Execution modes

Only these declared modes are accepted:

- `LOCAL_USER_CONTROLLED`
- `SELF_HOSTED_RUNNER`

The venue label is descriptive evidence, not proof by itself. The retained final URLs and page bytes remain authoritative for the scope verdict.

## Fail-closed environment boundary

Before network access, the implementation rejects non-empty values for:

- `HTTP_PROXY`
- `HTTPS_PROXY`
- `ALL_PROXY`
- lowercase equivalents
- `COOKIE`
- `COOKIES`
- `AUTHORIZATION`
- `PROXY_AUTHORIZATION`

No proxy, cookie, credential, DNS override, undocumented endpoint, or routing circumvention is part of this design.

## Evidence contract

`venue_attestation.json` records:

- full implementation SHA;
- full source commit SHA;
- validated PR merge ref;
- venue label and execution mode;
- privacy-minimal platform and Python identity;
- whether GitHub Actions is present;
- runner-environment declaration when available;
- clean proxy/cookie/auth environment lists;
- exact probe URL;
- all safety states.

The producer then reuses the already-reviewed category-root probe and its independent reviewer. A second physically separate venue reviewer reconciles:

- venue identity and SHA bindings;
- clean environment state;
- exact eight-candidate coverage;
- producer and category-review verdict equality;
- locale-neutral final URLs on PASS;
- all non-authorizing safety flags.

Both a reviewed probe PASS and a reviewed scope-drift FAIL are valid completed preflight outcomes. Unexpected runtime or venue-review failure is not.

## Prepared command surface

The committed runner is:

`implementation/scripts/run_c6a_source_scope_venue_preflight.py`

Its required arguments are:

```text
--output <directory>
--venue-label <descriptive-label>
--execution-mode LOCAL_USER_CONTROLLED|SELF_HOSTED_RUNNER
--implementation-sha <full-40-character-sha>
--source-commit-sha <full-40-character-sha>
--validated-pr-merge-ref <validated-ref>
```

No command is authorized by this document.

## Gate interpretation

- venue review PASS + probe PASS:
  `GLOBAL_SCOPE_AVAILABLE_ON_REVIEWED_VENUE`
- venue review PASS + probe FAIL:
  `GLOBAL_SCOPE_UNAVAILABLE_ON_REVIEWED_VENUE`
- venue review FAIL or runtime failure:
  `VENUE_PREFLIGHT_EVIDENCE_REJECTED`

None of these states alone equals source-authority Gate PASS.

## Safety state

- venue preflight execution: `NOT_AUTHORIZED`
- article expansion: `NOT_AUTHORIZED`
- third full capture: `NOT_AUTHORIZED`
- economic implementation: `NOT_AUTHORIZED`
- economic data access: `NOT_AUTHORIZED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

`VENUE_PREFLIGHT_IMPLEMENTED_NOT_AUTHORIZED` / `THIRD_FULL_CAPTURE_NOT_AUTHORIZED` / `LIVE_FORBIDDEN`
