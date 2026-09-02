# Shadow Operator Status V1

## Outcome

ATOS now exposes a read-only `shadow-status` operator command. It cross-checks
the atomic supervisor health snapshot, the kernel-held single-process lock, and
the canonical runtime session before reporting `RUNNING`, `STOPPED`,
`RECOVERY_REQUIRED`, or fail-closed `HOLD`.

## Safety boundary

- The status path never constructs a market, account, private API, execution,
  or AI provider client.
- The canonical SQLite database is opened with `mode=ro` and
  `PRAGMA query_only=ON`.
- Lock inspection uses a non-blocking shared probe and never steals or releases
  the supervisor's exclusive lock.
- Symbol scope, session identity, timestamps, heartbeat sequence, runtime
  lifecycle, and every Shadow safety flag must agree.
- A missing source, stale heartbeat, schema drift, symlink, state mismatch,
  circuit breaker, or process-lock mismatch becomes `HOLD`.
- Every result fixes trade action to `HOLD`, account/private/external access to
  false, `authorizes_live=false`, and Live to `FORBIDDEN`.

## Operator interpretation

- `RUNNING / HEALTHY`: the exact session owns the kernel lock, its heartbeat is
  fresh, and its canonical runtime row is `RUNNING`.
- `STOPPED`: only an operator stop or bounded completion with a released lock
  and matching durable terminal state.
- `RECOVERY_REQUIRED`: an explicit durable pause that requires the existing
  token-bound operator recovery review.
- `HOLD`: do not infer liveness or restart automatically; inspect the reason.

No workflow is added and this status command cannot create trading side
effects. Validation evidence is recorded on the implementation PR.

## Local validation

Base commit: `7dba0340df39be30745db2b4521f5280a73f52e1`.

- Python 3.11 full pytest: `1668 passed, 7 skipped`;
- focused Shadow operator/supervisor/evidence/recovery tests: `44 passed`;
- changed-file Ruff check and format check: passed;
- all 27 implementation configuration JSON files parsed successfully;
- all 6 workflow YAML files parsed successfully;
- repository secret scan: no secret leakage detected;
- CLI no-runtime preflight returned `HOLD / HEALTH_UNAVAILABLE`, with account,
  private API, external execution, and Live authorization all false.
