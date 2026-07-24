# C6A execution-venue preflight attempt 1 closeout

## Frozen evidence

The local executor returned `c6a-execution-venue-preflight-1.zip` with independently recomputed SHA-256:

`fb2bfb5d98967475589b51cba01fe7df431ac0a00ef094acfcd3d0467650ad48`

The archive contains five JSON files under one directory. Its manifest covers four evidence files exactly; all recorded sizes and SHA-256 values match independently recomputed values.

The frozen implementation identity is `1005ed8af49acd87576a20068a543e9fc91072a5`, with validated merge ref `refs/pull/77/merge@11f644fce6789fc8cdc399443373b3ab411fd050`.

## Independent findings

The executor report states that the runner was started three times and that the network candidate matrix was executed twice. The first start was interrupted, its output directory was removed, and later starts produced the delivered package. This violates the one-start execution contract. The delivered package therefore cannot establish a valid one-shot venue result.

All eight candidate rows lack a final URL and retained response bytes. Seven rows report `Broken pipe`; one reports `Connection reset by peer`. These are transport failures, not evidence of a locale redirect or regional scope drift.

The producer incorrectly recorded every transport failure as `FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT`. The independent probe reviewer and venue reviewer reproduced that same classification and returned review PASS, exposing a shared semantic defect: missing response bytes were treated as scope failure rather than execution failure.

The archive contains no raw response files because no response was obtained. Its manifest is internally correct for the files that are present, but completeness and hash integrity do not make the scope verdict valid.

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

Before any new execution is considered, the implementation must distinguish transport/runtime failure from a completed scope finding, the independent reviewers must reject missing response evidence as execution failure, and a durable invocation marker must prevent a second start after the first runner invocation. Partial evidence and the marker must survive interruption. Tests must cover broken pipe, connection reset, timeout, DNS/TLS failure, interruption, marker reuse, and reviewer rejection of multiple invocation evidence.

No new network execution is authorized by this closeout.
