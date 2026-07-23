# C6A Execution-Venue Preflight Authorization 1

## Authorization

Exactly one bounded execution-venue preflight is authorized against the official locale-neutral OKX announcements category root:

`https://www.okx.com/help/category/announcements`

The execution must use the reviewed local/self-hosted venue-preflight implementation and must stop after the eight-candidate category-root probe regardless of PASS or FAIL.

This authorization does not permit the full source-authority capture.

## Frozen implementation identity

- implementation/source commit SHA: `1005ed8af49acd87576a20068a543e9fc91072a5`
- validated PR merge ref: `refs/pull/77/merge@11f644fce6789fc8cdc399443373b3ab411fd050`
- exact-head CI: `#1616`
- exact-head CI run: `30037506550`
- allowed runner: `implementation/scripts/run_c6a_source_scope_venue_preflight.py`
- execution mode for the first attempt: `LOCAL_USER_CONTROLLED`
- maximum authorized invocations: `1`

The repository must be checked out at the exact implementation SHA with a clean working tree. Old or later commits are not authorized by this document.

## Required pre-network checks

Before invoking the runner:

1. verify `git rev-parse HEAD` equals the frozen implementation SHA;
2. verify `git status --porcelain` is empty;
3. verify the output directory does not already exist;
4. verify all supported proxy environment variables are absent or empty;
5. verify cookie, authorization, and proxy-authorization environment variables are absent or empty;
6. verify the execution is not inside GitHub Actions when using `LOCAL_USER_CONTROLLED`.

Any failed check terminates the attempt before network access. It does not authorize a retry.

## Exact command contract

Run from the repository's `implementation` directory with a new output directory:

```bash
PYTHONPATH=src python scripts/run_c6a_source_scope_venue_preflight.py \
  --output ../c6a-execution-venue-preflight-1 \
  --venue-label "openminis-local-user-controlled-direct" \
  --execution-mode LOCAL_USER_CONTROLLED \
  --implementation-sha 1005ed8af49acd87576a20068a543e9fc91072a5 \
  --source-commit-sha 1005ed8af49acd87576a20068a543e9fc91072a5 \
  --validated-pr-merge-ref refs/pull/77/merge@11f644fce6789fc8cdc399443373b3ab411fd050
```

Do not alter the URL, candidate matrix, headers, retry policy, reviewer, or safety flags.

## Required retained evidence

The completed output directory must contain at least:

- `venue_attestation.json`
- `probe_result.json`
- `independent_review.json`
- `venue_independent_review.json`
- `manifest.json`
- all eight retained raw candidate responses

Package the complete output directory into one ZIP archive and compute its SHA-256 digest. Preserve the unmodified directory until independent review is complete.

## Completion interpretation

A runner exit code of zero means the package and venue review completed; it does not mean the GLOBAL probe passed.

- venue review `PASS`, probe `PASS`:
  `GLOBAL_SCOPE_AVAILABLE_ON_REVIEWED_VENUE`
- venue review `PASS`, probe `FAIL`:
  `GLOBAL_SCOPE_UNAVAILABLE_ON_REVIEWED_VENUE`
- venue review `FAIL`, emergency file, missing evidence, or nonzero unexpected runtime:
  `VENUE_PREFLIGHT_EVIDENCE_REJECTED`

No outcome automatically authorizes article expansion or a third full source-authority capture.

## Prohibited actions

- any second invocation or retry;
- GitHub-hosted execution under the local mode;
- proxy, cookie, credential, DNS override, undocumented endpoint, or routing circumvention;
- accepting a locale-prefixed or regional Help Center as GLOBAL;
- article expansion;
- Wayback or instrument-history capture;
- economic implementation or economic data access;
- paper, shadow, private API, or live work.

## Safety state

- authorized action: `ONE_BOUNDED_LOCAL_VENUE_PREFLIGHT_ONLY`
- article expansion: `NOT_AUTHORIZED`
- third full capture: `NOT_AUTHORIZED`
- economic implementation: `NOT_AUTHORIZED`
- economic data access: `NOT_AUTHORIZED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

`ONE_BOUNDED_LOCAL_VENUE_PREFLIGHT_ONLY` / `NO_RETRY` / `LIVE_FORBIDDEN`
