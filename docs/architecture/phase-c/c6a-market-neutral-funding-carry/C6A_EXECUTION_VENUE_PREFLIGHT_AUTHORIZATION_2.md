# C6A Execution-Venue Preflight Authorization 2

## Authorization

Exactly one new bounded execution-venue preflight is authorized against the official locale-neutral OKX announcements category root:

`https://www.okx.com/help/category/announcements`

This is a new invocation against the remediated implementation. It is not a rerun of attempt 1. It must stop after the frozen eight-candidate category-root matrix regardless of GLOBAL PASS, completed scope FAIL, transport failure, emergency failure, interruption, or any other outcome.

This authorization does not permit article expansion or a full source-authority capture.

## Why a new invocation is admissible

Attempt 1 was closed with package integrity verified but its scope decision rejected because transport failures were mislabeled as scope drift and the executor started the old runner more than once.

The remediated implementation now:

- distinguishes transport/runtime failure from completed scope evaluation;
- records transport failure as `ERROR / FAIL_SOURCE_SCOPE_PROBE_EXECUTION`;
- independently rejects missing response evidence mislabeled as scope drift;
- creates an adjacent exclusive invocation marker before output or network access;
- retains the same invocation record inside the evidence package;
- preserves progress and emergency evidence across interruption;
- rejects later starts even if the output directory is deleted.

## Frozen implementation identity

- implementation/source commit SHA: `ead9251a97d077beea5a647370f5a38e97906d49`
- validated remediation PR merge ref: `refs/pull/90/merge@68594e4eb24f5dca27d7116b85f2d5b7cae24720`
- applicable CI: `#1753`
- applicable CI run: `30085931241`
- exact remediation head reviewed: `d8159590cdd171da924fd6cb2ae0d690bd14b1bf`
- allowed runner: `implementation/scripts/run_c6a_source_scope_venue_preflight.py`
- execution mode: `LOCAL_USER_CONTROLLED`
- venue label: `openminis-local-user-controlled-direct-attempt-2`
- output directory name: `c6a-execution-venue-preflight-2`
- adjacent invocation marker: `.c6a-execution-venue-preflight-2.invocation-started.json`
- maximum authorized runner starts: `1`

The repository must be checked out at the exact implementation/source SHA with a clean working tree. No old or later commit is authorized by this document.

## Required pre-network checks

Before invoking the runner:

1. locate and enter the `Dreaminmaster/ai-autonomous-trading-os` repository;
2. verify the `origin` URL identifies that repository;
3. fetch and detach at the frozen implementation/source SHA;
4. verify `git rev-parse HEAD` equals the frozen SHA;
5. verify `git status --porcelain` is empty;
6. verify the output directory, ZIP, and adjacent invocation marker do not exist;
7. verify all upper- and lower-case HTTP/HTTPS/ALL proxy environment variables are absent or empty;
8. verify cookie, authorization, and proxy-authorization environment variables are absent or empty;
9. verify `GITHUB_ACTIONS` is not `true` for `LOCAL_USER_CONTROLLED` mode.

Do not silently remove prohibited environment state. A failed precheck stops before invoking the runner and must be reported. It does not authorize an automatic retry.

## Exact command contract

Run once from the repository's `implementation` directory:

```bash
PYTHONPATH=src python scripts/run_c6a_source_scope_venue_preflight.py \
  --output ../c6a-execution-venue-preflight-2 \
  --venue-label "openminis-local-user-controlled-direct-attempt-2" \
  --execution-mode LOCAL_USER_CONTROLLED \
  --implementation-sha ead9251a97d077beea5a647370f5a38e97906d49 \
  --source-commit-sha ead9251a97d077beea5a647370f5a38e97906d49 \
  --validated-pr-merge-ref refs/pull/90/merge@68594e4eb24f5dca27d7116b85f2d5b7cae24720
```

Once this runner command starts, the authorization is consumed. Do not run it a second time for logging, packaging, repair, confirmation, or any other reason.

Do not alter the URL, candidate matrix, headers, internal HTTP-attempt policy, producer, reviewers, invocation marker, venue identity, or safety flags.

## Required retained evidence

Preserve without modification:

- adjacent invocation marker;
- `invocation_record.json`;
- `venue_attestation.json`;
- `probe_progress.json`;
- `probe_result.json`, when produced;
- `independent_review.json`, when produced;
- `venue_independent_review.json`, when produced;
- `emergency_failure.json`, when produced;
- `manifest.json`;
- all retained raw candidate responses, when any response was obtained.

Package both the complete output directory and adjacent invocation marker into one ZIP archive:

```bash
zip -r c6a-execution-venue-preflight-2.zip \
  c6a-execution-venue-preflight-2 \
  .c6a-execution-venue-preflight-2.invocation-started.json
```

Compute the ZIP SHA-256 and preserve the unmodified directory, marker, and ZIP until independent review is complete.

## Completion interpretation

- exit `0`, venue review PASS, probe PASS:
  `GLOBAL_SCOPE_AVAILABLE_ON_REVIEWED_VENUE`
- exit `0`, venue review PASS, probe completed scope FAIL:
  `GLOBAL_SCOPE_UNAVAILABLE_ON_REVIEWED_VENUE`
- exit `3`, venue review PASS, probe `ERROR / FAIL_SOURCE_SCOPE_PROBE_EXECUTION`:
  `VENUE_PREFLIGHT_EXECUTION_FAILURE_REVIEWED_NO_SCOPE_DECISION`
- exit `2`, emergency evidence, missing evidence, reviewer FAIL, marker mismatch, or unexpected runtime:
  `VENUE_PREFLIGHT_EVIDENCE_REJECTED`

A nonzero exit must not be repaired by another runner start. No outcome automatically authorizes article expansion or a third full source-authority capture.

## Prohibited actions

- any second runner start or retry;
- deleting or replacing the invocation marker;
- deleting the output directory and starting again;
- using the old attempt-1 implementation or authorization;
- GitHub-hosted execution under local mode;
- proxy, cookie, credential, DNS override, undocumented endpoint, or routing circumvention;
- accepting locale-prefixed or regional Help Center content as GLOBAL;
- article expansion;
- Wayback or instrument-history capture;
- economic implementation or economic data access;
- paper, shadow, private API, or live work;
- commit, push, or repository modification by the executor.

## Safety state

- authorized action: `ONE_NEW_REMEDIATED_LOCAL_VENUE_PREFLIGHT_ONLY`
- attempt 1: `CLOSED_NO_RERUN`
- article expansion: `NOT_AUTHORIZED`
- third full capture: `NOT_AUTHORIZED`
- economic implementation: `NOT_AUTHORIZED`
- economic data access: `NOT_AUTHORIZED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

`ONE_NEW_REMEDIATED_LOCAL_VENUE_PREFLIGHT_ONLY` / `ONE_RUNNER_START` / `NO_RETRY` / `LIVE_FORBIDDEN`
