# B5 Idempotent Execution and Recovery Contract V1

Status: DESIGN FREEZE CANDIDATE  
Authority base: `db925b40e28204d70a9dece7847ee9c59a023e8b`  
Mode: PAPER / SHADOW ONLY  
LIVE: FORBIDDEN

## 1. Purpose

B5 establishes deterministic, crash-safe execution idempotency on top of the frozen B4.2/B4.3 persistence graph.

The system may receive the same semantic execution request more than once because of process restart, retry after timeout, duplicate scheduler delivery, concurrent workers, delayed acknowledgement, or recovery replay.

B5 must guarantee that these deliveries cannot create an unbounded or blind duplicate trading side effect.

```text
at-least-once request delivery
  + durable semantic claim
  + deterministic remote identity
  + fail-closed recovery
  = exactly-once observable execution intent ownership
```

B5 does not claim that a database transaction and an exchange network call can be atomic. It closes the gap by persisting authority before the side effect, assigning a stable client order identity, and requiring reconciliation after any uncertain dispatch.

## 2. Existing frozen authority

B5 builds on, and must not weaken:

- immutable `trade_intents`, `risk_decisions`, and `execution_intents`;
- `dispatch_attempts` and `execution_states`;
- authoritative `order_states`, `fill_states`, `position_states`, and `position_accounting_details`;
- explicit SQLite transactions using `BEGIN IMMEDIATE`, foreign keys, WAL, and `synchronous=FULL`.

Existing execution status values remain authoritative:

```text
PREPARED
DISPATCH_COMMITTED
DISPATCHED
ACKNOWLEDGED
AMBIGUOUS
FILLED
TERMINAL
```

## 3. Non-goals

B5 does not:

- enable live trading or call private OKX order endpoints;
- add leverage, derivatives, withdrawals, or transfers;
- let an LLM choose or bypass an idempotency key;
- use timestamps, sessions, cycles, random UUIDs, or attempt numbers as semantic identity;
- treat a transport timeout as proof that no order exists;
- automatically retry an ambiguous remote side effect;
- delete, expire, or recycle an idempotency claim.

## 4. Canonical semantic identity

One semantic execution is identified by exactly:

1. `venue`
2. `account_scope`
3. `symbol`
4. `action`
5. `normalized_intent_hash`

The upstream execution, trade, risk, cycle, and session IDs are provenance, not semantic idempotency components.

Forbidden key inputs include session/cycle IDs, timestamps, attempt IDs/numbers, client order IDs, random values, process IDs, and worker IDs.

The canonical key uses the frozen length-delimited UTF-8 encoding:

```text
idempotency_key = sha256(length_delimited([
  venue,
  account_scope,
  symbol,
  action,
  normalized_intent_hash,
])).hexdigest()
```

Requirements:

- exactly 64 lowercase hexadecimal characters;
- calculated by deterministic Python, never accepted from AI output;
- exact validated component strings, without lossy normalization;
- stored components retained beside the hash so mapping drift fails closed.

## 5. Stable client order identity

Every idempotency claim owns one deterministic `client_order_id`.

It must:

- derive solely from the full idempotency key and a versioned deterministic projection;
- remain unchanged across retries and restarts;
- be unique within `(venue, account_scope)`;
- never use current time or randomness;
- remain queryable during reconciliation;
- satisfy the target adapter's length and character limits.

The full local key remains authority. A shortened remote identity is only a projection and must be locally collision-protected.

## 6. Durable claim schema

B5 schema implementation adds migration V5.

Add the exact parent key:

```sql
CREATE UNIQUE INDEX uq_execution_intents_idempotency_owner
ON execution_intents(
  execution_intent_id,
  symbol,
  action,
  normalized_intent_hash
);
```

Add:

```sql
CREATE TABLE execution_idempotency_claims (
    idempotency_key        TEXT PRIMARY KEY,
    execution_intent_id    TEXT NOT NULL UNIQUE,
    venue                  TEXT NOT NULL,
    account_scope          TEXT NOT NULL,
    symbol                 TEXT NOT NULL,
    action                 TEXT NOT NULL CHECK (action IN ('BUY','SELL')),
    normalized_intent_hash TEXT NOT NULL,
    client_order_id        TEXT NOT NULL,
    created_at             TEXT NOT NULL,

    CHECK (
      length(idempotency_key) = 64
      AND idempotency_key NOT GLOB '*[^0-9a-f]*'
      AND idempotency_key = lower(idempotency_key)
    ),
    CHECK (
      length(normalized_intent_hash) = 64
      AND normalized_intent_hash NOT GLOB '*[^0-9a-f]*'
      AND normalized_intent_hash = lower(normalized_intent_hash)
    ),

    UNIQUE (venue, account_scope, symbol, action, normalized_intent_hash),
    UNIQUE (venue, account_scope, client_order_id),
    UNIQUE (execution_intent_id, venue, account_scope, client_order_id),

    FOREIGN KEY (
      execution_intent_id,
      symbol,
      action,
      normalized_intent_hash
    ) REFERENCES execution_intents(
      execution_intent_id,
      symbol,
      action,
      normalized_intent_hash
    ) ON DELETE RESTRICT
);
```

Claims are permanent immutable audit records. Triggers reject all updates and deletes. There is no release, expiry, TTL, or recycle operation.

Every new B5 dispatch attempt must match an existing claim on execution intent, venue, account scope, and client order ID. Database-level enforcement is required through a migration-safe trigger or equivalent constraint. Existing historical rows remain readable; migration V5 must not fabricate historical claims.

## 7. Typed model

B5 introduces immutable typed values separated from persistence and network I/O:

```text
ExecutionIdempotencyCommand
ExecutionIdempotencyClaim
ExecutionIdempotencyOutcome
DispatchCommitCommand
DispatchCommitResult
DispatchOutcomeCommand
ExecutionRecoveryDecision
```

Outcomes:

```text
CLAIMED
REPLAY_PREPARED
RECONCILE_REQUIRED
TERMINAL_NOOP
```

Error hierarchy:

```text
ExecutionIdempotencyError
  ExecutionIdempotencyValidationError
  ExecutionIdempotencyPreconditionError
  ExecutionIdempotencyConflictError
  ExecutionIdempotencyInvariantError
  ConcurrentExecutionTransitionError
```

Typed constructors validate exact enum types, non-empty identities, lowercase hashes, UTC timestamps, deterministic key/client-ID recomputation, no HOLD execution, and no floating-point identity/notional values.

## 8. Claim operation

`claim_execution(command)` runs in one `BEGIN IMMEDIATE` transaction.

Before mutation it proves:

1. the exact execution intent exists;
2. symbol, action, and normalized hash match;
3. the parent risk decision is exactly `APPROVED`;
4. action is BUY or SELL;
5. key and client order ID recompute exactly;
6. no inconsistent claim or execution state exists.

For a first claim the same transaction inserts one immutable claim, inserts one `execution_states` row in `PREPARED`, re-reads both, commits, and returns `CLAIMED`. Claim and state must never be partially visible.

Exact replay behavior:

- `PREPARED` with no attempt -> `REPLAY_PREPARED`;
- `DISPATCH_COMMITTED`, `DISPATCHED`, `ACKNOWLEDGED`, or `AMBIGUOUS` -> `RECONCILE_REQUIRED`;
- `FILLED` or `TERMINAL` -> `TERMINAL_NOOP`;
- no duplicate row is written.

Conflicting execution/key ownership, corrupt stored components, a state without a claim, or a non-approved risk decision fails closed with no mutation.

## 9. Dispatch commit operation

The only safe pre-side-effect operation is `commit_dispatch(command)`.

It runs in one `BEGIN IMMEDIATE` transaction and:

1. proves claim/state consistency;
2. requires state exactly `PREPARED`;
3. proves no previous attempt exists;
4. derives deterministic `attempt_id` from key and attempt number;
5. reuses the claim's stable client order ID;
6. inserts one attempt as `PRE_DISPATCH_PROVEN`;
7. compare-and-swap transitions state to `DISPATCH_COMMITTED`;
8. re-reads and verifies;
9. commits before any executor or network call.

After this commit, a crash is not safely retryable without reconciliation.

## 10. Side-effect boundary

Only this sequence is permitted:

```text
claim_execution
  -> CLAIMED or REPLAY_PREPARED
  -> commit_dispatch
  -> durable DISPATCH_COMMITTED
  -> invoke paper/shadow executor
  -> persist outcome
```

Forbidden:

- executor call before claim/dispatch commit;
- executor call after `RECONCILE_REQUIRED`;
- automatic executor call from `AMBIGUOUS`;
- fresh random client order ID on retry;
- reset to `PREPARED` after dispatch commitment.

## 11. Outcome and recovery

Minimum mapping:

| Observation | Attempt | Execution state | Rule |
|---|---|---|---|
| accepted | `ACCEPTED` | `ACKNOWLEDGED` | no blind retry |
| deterministic rejection | `REJECTED` | `TERMINAL` | no retry |
| timeout/no proof | `TIMEOUT` or `AMBIGUOUS` | `AMBIGUOUS` | reconcile first |
| corrupt response | `AMBIGUOUS` | `AMBIGUOUS` | reconcile first |
| simulated fill persisted | accepted + lifecycle fill | `FILLED` | terminal replay noop |

No timeout or exception returns to `PREPARED`.

Recovery table:

| State | Attempt evidence | Decision |
|---|---|---|
| `PREPARED` | none | safe to call `commit_dispatch` |
| `PREPARED` | any | invariant failure; pause recovery |
| `DISPATCH_COMMITTED` | any | query stable client order ID first |
| `DISPATCHED` | any | reconcile; no blind retry |
| `ACKNOWLEDGED` | accepted order | reconcile order/fills |
| `AMBIGUOUS` | timeout/unknown | reconcile; no new dispatch |
| `FILLED` | complete lifecycle | terminal noop |
| `TERMINAL` | final negative outcome | terminal noop |

If authoritative reconciliation is unavailable, runtime enters or remains `PAUSED_RECOVERY_REQUIRED`.

## 12. Concurrency

Two SQLite connections racing on one semantic execution must yield one `CLAIMED`, one deterministic replay result, one claim, one PREPARED state, and zero attempts before `commit_dispatch`.

Required failures:

- same key, different execution intent -> conflict;
- same execution intent, different key -> conflict;
- same client order ID, different claim -> conflict;
- two concurrent dispatch commits -> exactly one attempt;
- CAS row count other than one -> concurrency error;
- database busy/timeout -> no executor call.

## 13. Transaction boundaries

All mutations use one injected `RuntimeDatabase` connection for repository lifetime:

- no ORM;
- no hidden reconnect;
- one `BEGIN IMMEDIATE` per public mutation;
- no helper commits;
- rollback on every exception;
- exact mutation counts tested;
- no network/executor import in persistence;
- no database import in pure key/type policy.

## 14. Migration compatibility

V5 must append without editing V1-V4 SQL/checksums, preserve existing rows, apply atomically, fail closed on partial creation, be idempotent after success, reject drift, preserve foreign keys, keep historical attempts readable, and create no fake historical claims.

V1-V4 checksums are frozen and asserted by regression tests.

## 15. Paper integration

B5 initially integrates only with paper/shadow execution.

The current random-order paper path is not authoritative for B5. The new typed paper adapter accepts the stable client order identity, is deterministic for identical envelopes, never creates a second simulated fill for one claim, keeps fees/slippage deterministic, persists through frozen B4.3 lifecycle writers, and imports no live private endpoint.

## 16. Safety invariants

- `LIVE = FORBIDDEN` in design, tests, examples, and evidence;
- no API keys/secrets in SQLite, code, logs, fixtures, reports, or artifacts;
- no withdrawal/transfer capability;
- no LLM-generated key or client order ID;
- missing risk approval means no claim/dispatch;
- unknown state means no dispatch;
- ambiguous state means reconciliation, not retry;
- audit rows are immutable and non-deletable.

## 17. Implementation decomposition

### B5A — contract freeze

Authorized file:

- `docs/architecture/phase-b/b5-execution/B5_IDEMPOTENT_EXECUTION_CONTRACT_V1.md`

No implementation or migration changes.

### B5B — schema and pure typed identity

Authorized files:

- `implementation/src/atos/runtime_migrations.py`
- `implementation/src/atos/execution_idempotency_types.py`
- `implementation/tests/test_execution_idempotency_schema.py`
- `implementation/tests/test_execution_idempotency_types.py`
- only necessary existing migration checksum/compatibility tests

No executor call or mutation repository.

### B5C — atomic claim and dispatch repository

Authorized files:

- `implementation/src/atos/execution_idempotency_repository.py`
- `implementation/tests/test_execution_idempotency_repository.py`
- narrowly required frozen type extensions

No network adapter and no live executor.

### B5D — paper adapter and recovery policy

Authorized files:

- new typed B5 paper adapter under `implementation/src/atos/`;
- pure recovery decision module under `implementation/src/atos/`;
- targeted replay/crash/ambiguity/reconciliation tests;
- minimal integration wiring approved separately.

No live adapter.

### B5E — exact evidence and closeout

Required evidence:

- targeted B5 and full pytest;
- two-connection concurrency;
- injected crash windows;
- V1-V4 checksum and V4-to-V5 row preservation;
- secret scan;
- existing CI and Freqtrade Validation;
- exact-SHA post-merge freeze gate;
- `LIVE = FORBIDDEN`.

## 18. Minimum acceptance matrix

Identity: stable across restart/session/cycle changes; changes for venue/account/symbol/action/hash; random/time inputs cannot affect it; stored components reproduce it; client projection is deterministic and collision-protected.

Claim: first claim `CLAIMED`; PREPARED replay `REPLAY_PREPARED`; post-dispatch replay `RECONCILE_REQUIRED`; terminal replay `TERMINAL_NOOP`; unapproved risk/HOLD/parent mismatch writes nothing; injected failure rolls back.

Dispatch: only PREPARED commits; evidence commits before executor call; concurrent commits create one attempt; stable client identity reused; no return to PREPARED; timeout becomes AMBIGUOUS.

Recovery: PREPARED/no attempt retryable; PREPARED/attempt corrupt; DISPATCH_COMMITTED and AMBIGUOUS require query; FILLED/TERMINAL no-op; unavailable reconciliation pauses recovery.

Regression: all B4.1-B4.3 tests pass; V1-V4 checksums unchanged; no lifecycle or Freqtrade regression; no secret leakage; LIVE forbidden.

## 19. Freeze rule

After B5A merges, this V1 contract is authoritative. Any change to identity components, encoding, client order identity, schema ownership, replay outcomes, PREPARED retry rule, ambiguity behavior, or authorized file surfaces requires a design erratum before implementation.

No implementation may claim that timeout proves non-execution or generate a fresh remote identity for retry.
