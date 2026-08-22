# C10A Cross-Sectional Residual Momentum — Authoritative Result V1

## 1. Final classification

C10A completed one official-public OKX H1–H5 capture and immutable artifact
upload, but the frozen evaluator stopped before the first historical replay.
The retained classification is therefore a valid program failure, not an
economic result.

- Stage: `C10A_H1_H5_AUTHORITY`
- Classification: `PROGRAM_FAILURE`
- Status: `FAIL`
- Official-public data custody: `PASS`
- Historical replay: `NOT_STARTED`
- Independent economic recomputation: `NOT_STARTED`
- Economic PASS/FAIL: `NOT_PRODUCED`
- Best-window selection: `NOT_PERFORMED`
- Retuning: `NOT_AUTHORIZED`
- Authoritative rerun: `NOT_AUTHORIZED`
- Execution feasibility: `NOT_ESTABLISHED`
- Paper: `PAPER_CLOSED`
- Shadow: `SHADOW_CLOSED`
- Live: `LIVE_FORBIDDEN`

No return, Sharpe, PSR, drawdown, turnover, comparator, attribution, or gate
value exists for C10A. A program failure must not be converted into an
economic loss, an economic pass, or evidence of trading edge.

## 2. Exact implementation and one-shot run

- Repository: `Dreaminmaster/ai-autonomous-trading-os`
- Design PR: `#115`
- Implementation PR: `#116`
- Implementation PR head: `108a6321c14ec67bd5cd903642d17faa58c7381e`
- Exact merged implementation commit: `367ec6669733feeb826e48896a4cdfb4ab0d4068`
- Authoritative workflow run: `32549795317`
- C10A authority job: `96974548109`
- ATOS test job: `96974547815` (`success`)
- Workflow URL: <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32549795317>
- Authority job URL: <https://github.com/Dreaminmaster/ai-autonomous-trading-os/actions/runs/32549795317/job/96974548109>

The checkout binding records the requested implementation SHA and observed
repository head as the same exact commit and records a clean tracked
worktree. The authority job started at `2026-08-22T03:44:25Z`. Official data
capture completed successfully at `04:03:35Z`; evaluation failed closed at
`04:03:38Z`; the outer manifest and immutable artifact upload then completed
successfully. The job finished at `04:03:46Z`.

This was the only C10A authority dispatch. It is not retried, repaired in
place, or repeated after inspecting the retained source package.

## 3. Immutable custody and post-download audit

The retained artifact is:

- Artifact ID: `9469933777`
- Name: `c10a-h1-h5-authoritative-32549795317`
- GitHub ZIP digest: `sha256:ba154471c2603fce4cfe23f79a42aac3768262f26b182f16cb17b7bc72e045d7`
- ZIP size: `19,350,549` bytes
- Created: `2026-08-22T04:03:43Z`
- Scheduled expiry: `2026-09-21T04:03:39Z`

An independent download outside the repository established:

- outer manifest: `2,991 / 2,991` files matched exact path, size, and
  SHA-256, with zero missing, extra, duplicate, escaping, or symlink entries;
- capture manifest: `2,987 / 2,987` files matched exact path, size, and
  SHA-256 under the same checks;
- outer sealed bytes: `92,081,428`;
- capture sealed bytes: `91,567,408`;
- outer manifest SHA-256:
  `0f5638e179ec9c84eebebea8bda60641cfe83efa677c351e64bdd7de350da175`;
- capture manifest SHA-256:
  `ca8c71c6a35ce47ba0c3df7c2ce00e43f7fd1e6415f34e6813877805899160cd`;
- capture index SHA-256:
  `8eab10d8b6151b49a2a99422a1d20870a8d594a297b46948771a63db2695f34e`;
- checkout binding SHA-256:
  `b4f875d4819dd3bbb489384e0cdf35122390ae801a3a33052c3706a76f9c5fc7`;
- formation universe SHA-256:
  `cd87f0ce8355a1919343880f186cbf05ebf34c4cb31f7930504fc0b1bef3d83f`;
- capture log SHA-256:
  `d8b6404710599916882cc7f25886d86ff279b7dc0ec2bbae8ef1b37364574554`;
- evaluator log SHA-256:
  `bdc83e3fcbf988ee991bb07bf8e24d7c6e915684751c79f05a81bd481a568029`.

The capture index contains `2,948` unique request IDs and `2,948` unique raw
paths: `764` trade-candle API responses, `1,912` mark-price API responses,
`32` historical-data manifest responses, and `240` official funding archive
downloads. All retained record digests and sizes matched the raw files. Every
requested and final URL used HTTPS, remained on `openapi.okx.com` or
`static.okx.com`, retained identical host/path/query semantics, and matched
the reviewed public endpoint allowlist. There were zero retries and zero
account, private API, order, credential, Paper, Shadow, or Live surfaces.

Both manifests state `authenticated=false`, `contains_account_data=false`,
`contains_order_data=false`, `paper_side_effect=false`,
`shadow_side_effect=false`, `live_state=LIVE_FORBIDDEN`, and
`execution_feasibility_established=false`.

## 4. Captured source coverage

The six-month formation interval retained `4,368` confirmed hourly trade rows
for each of the twelve frozen candidates. The fixed median quote-volume rank
selected, in order:

1. `BTC-USDT-SWAP`
2. `ETH-USDT-SWAP`
3. `SOL-USDT-SWAP`
4. `BCH-USDT-SWAP`
5. `DOGE-USDT-SWAP`
6. `XRP-USDT-SWAP`
7. `LTC-USDT-SWAP`
8. `LINK-USDT-SWAP`

For each selected instrument the capture retained:

- `21,841` hourly trade rows from `2024-01-01T00:00:00Z` through the
  terminal open at `2026-06-29T00:00:00Z`;
- `23,858` hourly mark rows from `2023-10-08T22:00:00Z` through
  `2026-06-28T23:00:00Z`;
- `2,730` actual realized funding settlements through
  `2026-06-28T16:00:00Z`.

The source package records `real_public_data=true`,
`source_kind=OFFICIAL_PUBLIC_OKX`, and `economic_result=false`.

## 5. Program failure and root cause

The exact evaluator output was:

```json
{"classification":"PROGRAM_FAILURE","error":"funding timestamp is off-grid","live_state":"LIVE_FORBIDDEN","status":"FAIL"}
```

The official funding archives contain actual settlement timestamps with
small delivery-time offsets. Across the eight selected instruments, `349` of
`21,840` normalized settlements are one to eight seconds after an exact hour.
BTC has zero off-grid settlements; the other seven instruments have `49` or
`50` each. Examples at the inclusive H1 boundary include:

- `ETH-USDT-SWAP`: `2024-01-01T00:00:01Z`;
- `SOL-USDT-SWAP`: `2024-01-01T00:00:05Z`;
- `DOGE-USDT-SWAP`: `2024-01-01T00:00:04Z`.

The capture correctly preserved these official timestamps and had already
validated uniqueness, strict order, and a maximum settlement gap of eight
hours plus one minute. The C10A contract also requires actual `fundingTime`
and the last completed preceding mark. The replay and independent-review
loaders nevertheless applied the hourly-candle grid rule to funding rows and
rejected the first such official value. That inconsistent program assumption
is the root cause.

Because failure occurred while loading funding and before the first replay,
the artifact contains no evidence directory, pooled summary, independent
economic review, or final economic classification. This is not a data
failure: the retained official values are valid source facts that the program
failed to model.

## 6. Closeout remediation boundary

The closeout change removes the one-time workflow input and authority job. It
also adds a synthetic regression repair to the reusable replay
infrastructure:

- funding retains its actual timestamp and is never rewritten to an
  idealized hour;
- exact-hour funding precedes a trade at the same timestamp;
- exact-hour funding on a weekly rebalance boundary is attributed to the
  position and week that carried it;
- delayed funding after an hourly trade applies to the position then carried;
- valuation uses the last completed preceding mark, not an incomplete candle
  or current trade open;
- duplicate, unordered, missing-predecessor, and unaccounted settlements fail
  closed;
- the physically separate recomputation implements and tests the same source
  semantics without importing the production replay.

Only synthetic fixtures are used to verify this repair. The downloaded C10A
H1–H5 package is not replayed after the repair, so the closeout produces no
post-failure economic observation and does not retroactively change run
`32549795317`.

## 7. Closed actions and final state

The following actions are closed:

1. triggering another C10A H1–H5 authority run;
2. evaluating the retained H1–H5 package after repairing the program;
3. tuning C10A's formation rank, regression, residual horizon, assets,
   rebalance schedule, sizing, costs, comparators, or gates;
4. describing C10A as profitable, unprofitable, selected, validated edge,
   execution-feasible, Paper-ready, Shadow-ready, or Live-ready;
5. enabling account access, private APIs, orders, Paper, Shadow, or Live for
   C10A.

Future economic research must be separately preregistered and structurally
distinct, must disclose C10A as a program-failed prior attempt, and must use
the corrected funding-event semantics before any one-shot authority run.

`C10A_H1_H5_COMPLETE`

`C10A_PROGRAM_FAILURE`

`HISTORICAL_ECONOMIC_RESULT_NOT_PRODUCED`

`RETUNING_NOT_AUTHORIZED`

`AUTHORITATIVE_RERUN_NOT_AUTHORIZED`

`PAPER_CLOSED`

`SHADOW_CLOSED`

`LIVE_FORBIDDEN`
