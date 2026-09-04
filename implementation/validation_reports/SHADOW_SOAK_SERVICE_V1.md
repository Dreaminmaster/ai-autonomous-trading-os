# Shadow Soak Service V1

## Outcome

ATOS can launch its public-data Shadow supervisor as one detached,
non-restarting process so a multi-day soak does not depend on an interactive
terminal. Every launch is bound to an exact clean Git commit and the SHA-256 of
the reviewed policy, and writes an exclusive local receipt before being
treated as an operator-controlled run.

## Safety boundary

- Start requires an exact 40-character commit equal to checkout `HEAD` and a
  completely clean worktree.
- The policy, runtime database, health, ledger, service receipt, stop request,
  and log must remain inside this repository's `implementation/runtime` tree.
- Each run receives an isolated database, health file, ledger, log, control
  files, and canonical deployed-policy copy in its mode-`0700` run directory;
  stale or unrelated runtime state cannot be silently reused.
- Only explicit Shadow, `live_enabled=false`, `public_data_only=true`, durable
  persistence, and allowlisted symbols are accepted.
- The child receives a minimal environment; API-key variables and unrelated
  parent environment values are not inherited.
- The process is detached once and has no restart monitor or automatic restart
  path.
- Logs, launch receipts, run directories, and stop requests are mode `0600` or
  `0700` and excluded from Git.
- Stop writes an idempotent request into the unique run directory. It never
  sends a PID signal, avoiding termination of an unrelated recycled PID.
- A malformed/tampered request file fails safe by stopping the supervisor.
- Every command reports trade action `HOLD`, `authorizes_live=false`, and Live
  `FORBIDDEN`.

## Operating sequence

1. Check out the reviewed main commit with a clean worktree.
2. Run `shadow-start --implementation-sha <exact-main-sha>`.
3. Use `shadow-status --service-receipt <path>` to prove the exact isolated
   health, process lock, and runtime state agree.
4. Let the supervisor accumulate the frozen seven-day soak without automatic
   restart.
5. Use `shadow-stop --service-receipt <path>` if an operator stop is required.
6. After a safe stop, build the immutable `shadow-evidence` package.

No GitHub workflow or one-shot authority input is added. Exact validation
evidence is recorded on the implementation PR.

## Local validation

- Base: `f7bf53c365df4c1032f78955b64c4125d29d0201`
- Python: 3.11
- Full suite: `1680 passed, 7 skipped`
- Service/supervisor/operator/evidence/recovery focus: `56 passed`
- Ruff on all changed Python: PASS
- Configuration JSON: 27 files parsed
- GitHub Actions YAML: 6 files parsed
- Repository secret leakage scan: PASS
