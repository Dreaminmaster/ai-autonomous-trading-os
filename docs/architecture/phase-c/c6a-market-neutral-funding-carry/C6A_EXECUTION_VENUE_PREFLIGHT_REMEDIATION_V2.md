# C6A execution-venue preflight remediation V2

## Trigger

Attempt 1 produced eight transport failures without any final URL or response bytes, but the producer and both reviewers labeled the result as source-scope drift. The executor also started the runner more than once because the reviewed implementation retained no durable invocation state.

## Corrected result model

Candidate results now separate execution from scope:

- response retained and evaluated: `execution_status=COMPLETE`, with `scope_status=PASS|FAIL`;
- no response evidence: `execution_status=FAIL`, `scope_status=NOT_EVALUATED`, and `failure_code=FAIL_SOURCE_SCOPE_PROBE_EXECUTION`.

The aggregate result is:

- `PASS / PASS` when at least one frozen A/B profile reproducibly proves the locale-neutral GLOBAL surface and no candidate execution failed;
- `FAIL / FAIL_SOURCE_AUTHORITY_SCOPE_DRIFT` when the complete matrix executes but no profile proves GLOBAL scope;
- `ERROR / FAIL_SOURCE_SCOPE_PROBE_EXECUTION` when any candidate lacks response evidence.

Transport failure is never a scope decision.

## Independent review

The physically separate probe reviewer requires retained response bytes and a final URL before recomputing scope. Missing response evidence must be represented as execution failure; any scope-drift label on such a row is review failure.

A correctly classified execution-failure package may receive independent-review PASS because the reviewer successfully verifies the failure evidence, but the venue decision is `REJECTED_EXECUTION_FAILURE`, never `ACCEPTED_FOR_BOUNDED_PREFLIGHT`.

## Durable one-start boundary

Before output-directory creation or network access, the runner creates an adjacent marker with `O_EXCL`:

`.OUTPUT_NAME.invocation-started.json`

The same canonical record is retained inside the package as `invocation_record.json` and bound into `venue_attestation.json` by invocation ID and SHA-256. Existing output or marker state rejects a later start. Deleting the output directory does not remove the adjacent marker.

The marker is retained after PASS, scope FAIL, execution failure, interruption, or exception. It is never silently removed by the runner.

## Partial evidence

`probe_progress.json` is written before the first candidate and after every completed candidate row. An interruption therefore leaves the invocation record, venue attestation, and latest progress state. The CLI runner also writes `emergency_failure.json` and rebuilds the manifest when an exception occurs after invocation start.

## Exit contract

- independently reviewed completed scope PASS or scope FAIL: exit `0`;
- independently reviewed execution failure or rejected venue evidence: exit `3`;
- emergency exception after evidence retention: exit `2`.

## Validation

Offline tests cover GLOBAL PASS, regional scope FAIL, broken pipe, connection reset, timeout, URL failure, DNS failure, TLS failure, incorrect scope-drift labeling, prohibited proxy state, repeated start rejection, interruption evidence, invocation-record tamper, and venue-attestation tamper.

## Safety state

This remediation authorizes no network execution or retry. Article expansion, third full capture, economic implementation, economic data access, paper, shadow, private API, and live work remain closed or forbidden.

`IMPLEMENTATION_REMEDIATION_ONLY` / `NO_NETWORK_EXECUTION_AUTHORIZED` / `LIVE_FORBIDDEN`
