# Public-Data Shadow Supervisor V1

## Outcome

ATOS now has a process-owned, long-running supervisor for the durable Shadow
runtime. It repeatedly acquires only official OKX public market data, drives
schema-validated decisions through deterministic risk, records atomic health
heartbeats, and stops cleanly on SIGINT/SIGTERM, a bounded run limit, a durable
recovery lock, or a consecutive-failure circuit breaker.

## Safety boundary

- Shadow is the only accepted mode; Paper and Live are rejected.
- `live_enabled=false`, `public_data_only=true`, durable persistence, and an
  allowlisted symbol set are mandatory before runtime construction.
- The production builder always constructs the strict official
  `PublicMarketAdapter`; there is no account or private API dependency.
- Health and audit records explicitly bind account access, private API,
  external execution, and automatic restart to false; Live is `FORBIDDEN`.
- A pre-existing or newly latched recovery condition immediately pauses the
  durable session and requires explicit operator recovery. The supervisor does
  not reconcile, retry, resolve recovery, or restart itself.
- Data/program failures are classified without persisting exception text or
  secret-bearing input. Three consecutive failures stop the process by
  default.
- A non-blocking OS lock is bound to the canonical runtime database for the
  full supervisor lifetime, preventing concurrent local supervisors. A crash
  releases the kernel lock; the supervisor never guesses or auto-restarts.

## Operational evidence

- `runtime/shadow_health.json` is atomically replaced after startup, every
  cycle heartbeat, and final stop.
- `runtime/shadow_events.sqlite` stores supervisor lifecycle and failure audit
  events independently from the canonical durable execution database.
- completed durable sessions transition to `STOPPED`; recovery-locked sessions
  transition to `PAUSED_RECOVERY_REQUIRED` when a session row exists.
- `--max-loops 0` runs continuously; a positive value provides a bounded smoke
  run.

## Local validation

Base commit: `debc453e70f0857b399a85ba7e0005ee41b3b4c7`.

- full pytest: `1647 passed, 7 skipped`;
- focused supervisor/runtime/recovery tests: `39 passed`;
- Ruff check and format check: passed for every changed Python source/test;
- policy JSON and all 6 workflow YAML files: parsed successfully;
- repository secret scan: no secret leakage detected;
- official OKX public-data bounded smoke: one BTC-USDT cycle completed with
  `NOOP_HOLD`, the durable session reached `STOPPED / BOUNDED_COMPLETE`, and
  execution-intent, order, and fill table counts were all zero;
- smoke health SHA-256:
  `5bc1c5dd4d9b76dad14e841b9acd571b8c2b50cf219aeb5c28b01b0f308ab79b`.

GitHub run evidence will be bound to the exact implementation head by the
existing CI and Freqtrade Validation workflows. No one-shot authority workflow
was added or triggered.
