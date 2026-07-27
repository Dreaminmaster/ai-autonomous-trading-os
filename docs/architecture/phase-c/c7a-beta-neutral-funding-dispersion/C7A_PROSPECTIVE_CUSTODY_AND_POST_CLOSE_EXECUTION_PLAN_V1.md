# C7A prospective custody and post-close execution plan V1

## 1. Status and authority

- stage: `C7A`
- current state: `SYNTHETIC_IMPLEMENTATION_COMPLETE`
- implementation merge SHA: `aaa8f231fdb523f68743dbe6a0d0f6a87deb7a8a`
- real C7A data: `NOT_AUTHORIZED`
- network collection: `NOT_AUTHORIZED`
- partial prospective performance: `FORBIDDEN`
- economic run: `NOT_AUTHORIZED`
- C7B: `CLOSED`
- paper: `PAPER_CLOSED`
- shadow: `SHADOW_CLOSED`
- live: `LIVE_FORBIDDEN`

This document is planning-only. It does not authorize a workflow, downloader, real market row, economic calculation, account access, order, paper execution, shadow execution, or live execution.

## 2. Why no real-data custody occurs during the scored interval

The C7A contract froze a prospective economic interval before any result existed. To preserve that boundary, the repository, CI, artifacts, prompts, reviewers, and local project work must not retain or inspect real C7A rows or partial performance before the scored interval closes.

Therefore:

- no continuous collector is created now;
- no scheduled GitHub Actions workflow is created now;
- no local background collector is created now;
- no dashboard, interim report, alert, preview, or partial metric is created now;
- no real C7A data is committed, uploaded as an artifact, or copied into project discussions.

The authoritative dataset will be retrieved after the interval closes from the already frozen official public surfaces. Because the dates, instruments, transformations, candidate, costs, comparators, and gates are preregistered, post-close retrieval does not reopen parameter selection.

## 3. Frozen time boundary

The future authorization must fail closed unless the trusted UTC clock is at or after:

`2027-02-22T00:00:00Z`

The retained C7A interval is exactly:

- mark-price seed close: `2026-07-26T23:00:00Z`;
- funding and trade-candle start: `2026-07-27T00:00:00Z`;
- first scored decision: `2026-08-24T00:00:00Z`;
- scored end exclusive and C7B start: `2027-02-22T00:00:00Z`.

No timestamp at or after `2027-02-22T00:00:00Z` may be retained, summarized, hashed into C7A economic evidence, or used to repair C7A. Overshoot rows must be deleted before any research read and their count recorded.

## 4. Future exact-SHA authorization sequence

After the scored interval has closed, work must proceed through separate reviewed changes rather than an open-ended workflow.

### 4.1 Implementation freeze

A future implementation PR may add only the missing real-data acquisition, normalization, full-period simulation orchestration, final evidence packaging, and independent recomputation wiring.

It must:

- reuse the merged frozen C7A contract and synthetic calculation semantics unchanged;
- contain no threshold, lookback, estimator, asset, cost, gate, comparator, or accounting alteration;
- fail closed on missing, duplicate, ambiguous, contradictory, non-finite, unordered, or out-of-bound data;
- expose no paper, shadow, private API, account, order, or live path;
- pass ordinary CI and every directly applicable validation before merge.

The merged implementation SHA must then be recorded exactly. A later authorization must identify that exact SHA and its validated PR merge ref.

### 4.2 One temporary authoritative workflow

Only after the implementation is merged and independently reviewed may a separate authorization PR add one temporary workflow for one authoritative capture and one economic run.

The workflow must:

- refuse to start before `2027-02-22T00:00:00Z`;
- checkout the exact authorized implementation SHA;
- verify a clean tree and frozen configuration hash;
- download only the permitted public C7A inputs;
- reject authenticated endpoints and all private/account surfaces;
- remove and record all C7B overshoot before research read;
- execute the candidate once at the three frozen cost levels;
- execute the three non-selectable comparators once;
- run the physically separate independent recomputation;
- create one complete immutable evidence package and SHA-256 manifest;
- upload the final package as the workflow artifact.

The authorization is consumed when the authoritative runner begins. No automatic retry, matrix rerun, alternate source, or second economic attempt is allowed.

### 4.3 Evidence freeze and workflow removal

A final closeout PR must independently verify the artifact, record exact provenance and hashes, state `SELECTED` or `REJECTED`, and immediately delete the temporary workflow.

No result is authoritative merely because a workflow completed. Authority requires:

- exact authorized SHA;
- complete raw and normalized source evidence;
- exact retained interval;
- complete manifest verification;
- producer and independent reviewer agreement;
- unchanged frozen gate evaluation;
- durable closeout merged to `main`.

## 5. Permitted future public sources

Future acquisition remains limited to the already frozen official surfaces:

- OKX downloadable historical-data files;
- `GET /api/v5/market/history-candles`;
- `GET /api/v5/market/history-mark-price-candles`;
- `GET /api/v5/public/funding-rate-history`.

`GET /api/v5/public/instruments` remains excluded from C7A historical economic selection. Current instrument metadata may be considered only after an economic PASS and only in a separately preregistered execution-readiness gate.

No undocumented endpoint, proxy, credential, cookie, routing workaround, external exchange, backward metadata projection, interpolation, or weaker substitute is permitted.

## 6. Failure taxonomy

A future attempt must distinguish process failure from an economic result.

### 6.1 Pre-start failure

Examples:

- clock is before the scored close;
- implementation SHA or configuration hash does not match;
- authorization identity is incomplete;
- workspace or workflow state is not clean.

Result: `NOT_STARTED`. Authorization is not consumed unless the authoritative runner began.

### 6.2 Capture or data-authority failure

Examples:

- permitted public source cannot be reached;
- full interval cannot be retrieved;
- funding settlements are incomplete or ambiguous;
- candles are missing or contradictory;
- C7B overshoot cannot be safely removed.

Result: `PRE_ECONOMIC_FAIL`. No economic conclusion and no selected policy.

### 6.3 Execution or evidence failure

Examples:

- producer crashes after reading valid data;
- independent recomputation cannot complete;
- manifest or retained evidence is incomplete;
- producer and reviewer disagree.

Result: `EXECUTION_OR_INTEGRITY_FAIL`. No economic conclusion and no selected policy.

### 6.4 Completed economic result

Only a complete, independently verified package may produce:

- `SELECTED`, when every unchanged gate passes; or
- `REJECTED`, when one or more unchanged gates fail.

A failed gate cannot authorize retuning and rerunning C7A.

## 7. Custody and disclosure rules

Until the final closeout is merged:

- raw source bytes, normalized rows, decisions, aggregates, and reviewer outputs remain inside the single authoritative artifact;
- no partial chart, metric, summary, ranking, or result is copied into a PR description or discussion;
- logs must avoid printing economic values beyond what is necessary to diagnose a process failure;
- the artifact manifest must cover every retained file recursively;
- any downloaded overshoot must be excluded from research inputs and separately counted;
- no C7B data may survive in the retained C7A package.

## 8. Current project consequence

The synthetic C7A calculation, gate evaluation, independent review, and evidence-package framework are complete. There is no useful real-data action before the scored interval closes.

The repository should now remain in a waiting state for C7A economic execution while unrelated maintenance may continue only if it does not expose real C7A rows, alter the frozen thesis, or open paper, shadow, private API, or live behavior.

`C7A_POST_CLOSE_PLAN_ONLY` / `NO_REAL_DATA_BEFORE_2027_02_22` / `NO_PARTIAL_PERFORMANCE` / `ONE_FUTURE_AUTHORITATIVE_RUN` / `C7B_CLOSED` / `PAPER_CLOSED` / `SHADOW_CLOSED` / `LIVE_FORBIDDEN`
