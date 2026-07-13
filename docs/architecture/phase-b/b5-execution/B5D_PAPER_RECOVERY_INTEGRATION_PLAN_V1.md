# B5D Paper Execution and Recovery Integration Plan V1

Status: planning contract only  
Base: `94afa2aa4d9898260100d349c9d7af85654abd5f`  
LIVE: `FORBIDDEN`

## 1. Purpose

B5D completes the paper/shadow side-effect path after the frozen B5C claim and dispatch-commit repository.

B5C durably proves one semantic execution and one pre-dispatch attempt, but it intentionally stops at:

- attempt status `PRE_DISPATCH_PROVEN`;
- execution status `DISPATCH_COMMITTED`.

The frozen B4.3 lifecycle writer requires:

- attempt status `SUBMITTED` and execution status `DISPATCHED` before order acknowledgement;
- attempt status `ACCEPTED` and execution status `ACKNOWLEDGED` before fill persistence;
- a separate final transition to execution status `FILLED` after the deterministic fill is durable.

Therefore B5D needs a narrowly scoped outcome repository in addition to a deterministic paper adapter and pure recovery policy. This document is the separately approved integration surface required by the B5 V1 contract.

## 2. Non-goals

B5D does not:

- add or modify a live/private exchange adapter;
- call OKX private endpoints;
- add API keys, secrets, withdrawal, transfer, or funding capability;
- change B5 identity components or hash encoding;
- change the `a5` client-order projection;
- change deterministic attempt identity;
- change migration V1-V5 SQL or checksums;
- change the one-attempt B5 V1 rule;
- reset any post-dispatch state to `PREPARED`;
- treat timeout as proof of non-execution;
- reuse the legacy `implementation/python/paper_executor.py` as authoritative B5 execution.

## 3. Authorized files

Implementation files:

- `implementation/src/atos/execution_outcome_repository.py`
- `implementation/src/atos/execution_recovery.py`
- `implementation/src/atos/paper_execution_adapter.py`

Tests:

- `implementation/tests/test_execution_outcome_repository.py`
- `implementation/tests/test_execution_recovery.py`
- `implementation/tests/test_paper_execution_adapter.py`

Narrowly permitted compatibility surface:

- immutable typed values may be added only inside the three new implementation files;
- no edit to frozen B5B identity derivation is permitted;
- no edit to B5C `claim_execution` or `commit_dispatch` is permitted;
- no edit to B4.3 lifecycle persistence is permitted;
- minimal runtime wiring outside these files requires a new explicit plan before modification.

## 4. Outcome repository contract

`SqliteExecutionOutcomeRepository` uses one injected `RuntimeDatabase` connection for its lifetime.

Every public mutation uses exactly one `BEGIN IMMEDIATE` transaction, has no helper commit, rolls back on every exception, and performs no network/executor/filesystem I/O.

### 4.1 `mark_dispatched`

Preconditions:

- exact immutable claim exists;
- exact deterministic attempt exists;
- attempt belongs to the claim and has `attempt_no = 1`;
- attempt status is exactly `PRE_DISPATCH_PROVEN`;
- execution status is exactly `DISPATCH_COMMITTED`;
- execution `last_attempt_id` matches the attempt;
- stable client-order identity matches the claim.

Atomic mutations:

- attempt `PRE_DISPATCH_PROVEN -> SUBMITTED`;
- set `dispatch_started_at`;
- execution `DISPATCH_COMMITTED -> DISPATCHED` with compare-and-swap.

The transaction re-reads and verifies both rows before commit.

A replay after either mutation has become visible must fail closed or return a typed verified replay result; it must never create a second attempt.

### 4.2 `mark_ambiguous`

Used only after a timeout, transport uncertainty, corrupt executor response, or an injected crash for which authoritative local reconciliation cannot prove a terminal result.

Atomic mutations:

- attempt becomes `TIMEOUT` or `AMBIGUOUS`;
- execution becomes `AMBIGUOUS`;
- error class and observation timestamp are persisted;
- no transition back to `PREPARED` is allowed.

### 4.3 `mark_terminal_rejection`

For a deterministic negative paper response:

- attempt becomes `REJECTED`;
- execution becomes `TERMINAL`;
- no order or fill is fabricated;
- replay is terminal no-op after exact row verification.

### 4.4 `mark_filled`

Preconditions:

- attempt is exactly `ACCEPTED`;
- execution is exactly `ACKNOWLEDGED`;
- exact deterministic order exists and belongs to the attempt/client identity;
- exact deterministic fill exists and belongs to the order;
- fill is complete for the paper order.

Atomic mutation:

- execution `ACKNOWLEDGED -> FILLED` with compare-and-swap.

Replay of an already verified `FILLED` execution is a typed no-op.

## 5. Pure recovery policy

`execution_recovery.py` imports no database, executor, network, clock, or filesystem module.

It accepts an immutable recovery snapshot and returns exactly one:

- `SAFE_COMMIT_DISPATCH`
- `RECONCILE_REQUIRED`
- `TERMINAL_NOOP`
- `PAUSE_RECOVERY`

Minimum rules:

| Execution state | Attempt evidence | Reconciliation available | Decision |
|---|---|---|---|
| `PREPARED` | none | irrelevant | `SAFE_COMMIT_DISPATCH` |
| `PREPARED` | any | irrelevant | `PAUSE_RECOVERY` |
| `DISPATCH_COMMITTED` | exact attempt | yes | `RECONCILE_REQUIRED` |
| `DISPATCHED` | exact attempt | yes | `RECONCILE_REQUIRED` |
| `ACKNOWLEDGED` | accepted attempt/order | yes | `RECONCILE_REQUIRED` |
| `AMBIGUOUS` | timeout/unknown | yes | `RECONCILE_REQUIRED` |
| any reconciliation-required state | missing/corrupt authority | no | `PAUSE_RECOVERY` |
| `FILLED` | complete lifecycle | irrelevant | `TERMINAL_NOOP` |
| `TERMINAL` | final negative result | irrelevant | `TERMINAL_NOOP` |

Unknown enums, impossible state/attempt combinations, more than one attempt, or mismatched stable identity return `PAUSE_RECOVERY` or raise a typed invariant error; they never authorize dispatch.

## 6. Deterministic paper adapter

The new B5 adapter is independent of the legacy random paper executor.

### 6.1 Input envelope

The immutable input includes:

- execution intent ID;
- full idempotency key;
- deterministic attempt ID;
- stable client order ID;
- venue and account scope;
- symbol and `OrderSide`;
- `Decimal` quantity and mark price;
- fee currency;
- explicit UTC observation timestamp.

The adapter recomputes and verifies attempt/client identities. It accepts no random ID, current clock, float notional, session ID, cycle ID, or timestamp bucket as identity authority.

### 6.2 Deterministic values

For one envelope:

- order ID is a versioned SHA-256 projection of venue, account scope, and stable client order ID;
- fill ID is a different versioned SHA-256 projection of the same authority;
- execution price is deterministic from mark price, side, and configured `Decimal` slippage bps;
- fee is deterministic from quantity, execution price, and configured `Decimal` fee bps;
- order type is `MARKET`;
- the fill is complete and uses `OrderStatus.FILLED`;
- the same envelope always generates byte-equivalent lifecycle commands.

No hidden wall clock or randomness is permitted.

### 6.3 Allowed orchestration sequence

The adapter/coordinator may only execute:

```text
B5C commit_dispatch already durable
  -> reconcile stable paper IDs
  -> mark_dispatched
  -> register_order_acknowledgement through B4.3 writer
  -> apply_fill through B4.3 writer
  -> mark_filled
```

If reconciliation finds an existing order or fill, it resumes from durable authority and uses deterministic replay-safe commands. It does not create a new client order ID, attempt, order ID, or fill ID.

If authoritative reconciliation is unavailable or contradictory, it returns/enters `PAUSE_RECOVERY`; it does not call the paper side-effect path.

## 7. Crash and replay matrix

Required injected windows:

- before `mark_dispatched`;
- after attempt status mutation but before execution CAS;
- after `mark_dispatched` commit but before order acknowledgement;
- after order acknowledgement but before fill;
- after fill commit but before `mark_filled`;
- after `mark_filled` commit before return.

For every window, restart plus reconciliation must yield one of:

- safe deterministic resume with the same stable identities;
- `RECONCILE_REQUIRED`;
- `TERMINAL_NOOP`;
- `PAUSE_RECOVERY`.

It must never produce a second attempt, order, fill, or accounting event.

## 8. Concurrency

Two workers racing the same paper execution must produce:

- one B5 attempt total;
- one deterministic order identity total;
- one deterministic fill identity total;
- one lifecycle accounting sequence total;
- verified replay/no-op or recovery decision for the loser;
- no live/network call.

## 9. Test and Gate requirements

Targeted tests must cover:

- deterministic vectors for order/fill IDs, price, fee, and commands;
- invalid/mismatched derived identity rejection;
- all recovery table rows;
- exact SQLite transition preconditions and CAS;
- two-connection outcome races;
- all crash windows;
- deterministic lifecycle replay;
- one fill and one accounting sequence under concurrency;
- source import boundaries;
- `LIVE = FORBIDDEN`.

Formal Gate:

- targeted B5D tests;
- full pytest;
- secret scan;
- existing CI;
- existing Freqtrade Validation;
- `Verify Simple CI` and evidence summary;
- exact final SHA provenance;
- post-merge blob/tree identity proof;
- no modification to migrations V1-V5 or frozen B5 identity algorithms.

## 10. Failure handling

Any database busy/timeout, CAS miss, missing parent, corrupt identity, impossible state, contradictory reconciliation, unexpected exception, or unavailable authority must fail closed.

No error handler may:

- issue a fresh client order ID;
- create attempt number two;
- reset execution to `PREPARED`;
- infer non-execution from timeout;
- call a live/private endpoint;
- suppress a failed Gate.

## 11. Freeze rule

After this plan is merged, the authorized files and transition rules above are the B5D implementation boundary.

Any schema change, B5 identity change, second-attempt policy, live adapter, private exchange call, or modification to frozen B4.3/B5B/B5C methods requires a new design erratum before implementation.
