# C6A execution-venue preflight attempt 1 closeout

## Frozen evidence

The local executor returned `c6a-execution-venue-preflight-1.zip` with independently recomputed SHA-256:

`fb2bfb5d98967475589b51cba01fe7df431ac0a00ef094acfcd3d0467650ad48`

The archive contains five JSON files under one directory. Its manifest covers the four non-manifest evidence files exactly; every recorded size and SHA-256 matches independent recomputation.

Frozen implementation identity:

- implementation/source SHA: `1005ed8af49acd87576a20068a543e9fc91072a5`
- validated merge ref: `refs/pull/77/merge@11f644fce6789fc8cdc399443373b3ab411fd050`
- execution mode: `LOCAL_USER_CONTROLLED`
- venue label: `openminis-local-user-controlled-direct`

## Independent findings

The executor report states that the runner started three times and that the network candidate matrix executed twice. The first start was interrupted, its output directory was removed, and later starts produced the delivered package. The package cannot independently count starts because the reviewed implementation retained no durable invocation ledger. The operator-supplied report is therefore the evidence for the execution-contract violation.

All eight delivered candidate rows lack a final URL and retained response bytes. Seven rows report `Broken pipe`; one reports `Connection reset by peer`. These are transport failures, not evidence of a locale redirect or regional source-scope drift.

The producer incorrectly recorded each transport failure as `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT`. The independent probe reviewer and venue reviewer reproduced that classification and returned review PASS. This confirms a shared semantic defect: missing response evidence was treated as a completed scope finding rather than an execution failure.

The archive contains no raw response files because no response was obtained. Its manifest is internally correct for the files present, but package integrity does not make the scope verdict valid.

## Accepted classification

- `VENUE_PREFLIGHT_ATTEMPT_1_PACKAGE_INTEGRITY_VERIFIED`
- `VENUE_PREFLIGHT_ATTEMPT_1_EXECUTION_CONTRACT_VIOLATED`
- `VENUE_PREFLIGHT_ATTEMPT_1_TRANSPORT_FAILURE_CONFIRMED`
- `VENUE_PREFLIGHT_ATTEMPT_1_SCOPE_DECISION_REJECTED`
- `PRODUCER_REVIEWER_SHARED_SEMANTIC_DEFECT_CONFIRMED`
- `GLOBAL_SCOPE_AVAILABLE_NOT_PROVEN`
- `GLOBAL_SCOPE_UNAVAILABLE_NOT_PROVEN`
- `SOURCE_AUTHORITY_GATE_NOT_PASSED`
- `NO_RERUN`
- `THIRD_FULL_CAPTURE_NOT_AUTHORIZED`
- `LIVE_FORBIDDEN`

## Required remediation boundary

Before any new execution is considered:

1. transport/runtime failures must be separated from completed scope findings;
2. reviewers must reject missing final URL or response bytes as execution failure;
3. a durable invocation marker must make the first runner start observable and reject all later starts;
4. partial evidence and invocation state must survive interruption;
5. tests must cover broken pipe, connection reset, timeout, DNS/TLS failure, interruption, marker reuse/tamper, repeated-start rejection, and reviewer rejection of transport failure mislabeled as scope drift.

Next admissible work is implementation-only remediation and ordinary CI validation. This closeout authorizes no network execution, venue retry, article expansion, third full capture, economic implementation, paper, shadow, private API, or live work.
