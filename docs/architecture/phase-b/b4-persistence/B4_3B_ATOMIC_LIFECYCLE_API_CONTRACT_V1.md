# B4.3B Atomic Lifecycle Persistence API Contract V1

**Baseline main**: `f6e7f3878c14ef74e038b4c0575b996735467586`  
**Depends on**: B4.3A migration 0004 — MERGED / FROZEN  
**Runtime shape**: modular monolith  
**LIVE**: FORBIDDEN

---

## 1. Purpose

B4.3A froze the authoritative database identities and ownership graph for:

```text
DispatchAttempt
  -> OrderState
  -> FillState
  -> PositionState
  -> PositionAccountingDetail
```

B4.3B adds the in-process typed API that mutates those records without weakening durability, ownership, replay safety, or hot-path efficiency.

The target is not a microservice architecture. The target is:

```text
clear replaceable modules
+
one Python process
+
direct typed calls
+
one injected RuntimeDatabase connection
+
one explicit SQLite transaction per public mutation
```

---

## 2. Bounded delivery units

B4.3B is split into three independently auditable units.

### B4.3B1 — Typed lifecycle model and pure accounting policy

Creates immutable commands, results, enums, snapshots, deterministic identifiers, decimal normalization, and the pure default position-accounting policy.

No database writes are allowed in B4.3B1.

### B4.3B2 — Atomic SQLite lifecycle persistence adapter

Creates the concrete in-process adapter that:

- registers an order acknowledgement atomically;
- applies one fill plus its accounting/position effects atomically;
- detects exact replay without mutation;
- rejects conflicting replay;
- records exact read/mutation counts;
- reuses one injected `RuntimeDatabase` connection.

### B4.3B3 — Relative performance gate and evidence artifact

Creates a same-run direct baseline, benchmark runner, p50/p95 report, statement-count report, and fail-closed CI artifact.

B4.3B is frozen only after all three units pass exact-SHA and post-merge gates.

---

## 3. Explicit exclusions

B4.3B must not implement:

- OKX or any venue network call;
- dispatch registration or client-order generation from B5;
- blind retry after ambiguous dispatch;
- fill polling;
- reconciliation from B11;
- crash recovery orchestration from B7/B12;
- risk-state persistence from B6;
- provider HOLD behavior from B8;
- market/account freshness from B9;
- full paper lifecycle engine from B10;
- notification delivery;
- background database writers;
- ORM, SQLAlchemy, HTTP, RPC, message bus, or internal JSON transport;
- LIVE enablement.

Persistence-level exact replay handling in B4.3B is not a substitute for B5 dispatch idempotency.

---

## 4. Module boundaries

### 4.1 `lifecycle_types.py`

Owns immutable, slot-based typed values only:

- enums;
- command dataclasses;
- result dataclasses;
- position snapshots;
- accounting-plan records;
- typed Protocols;
- validation helpers that do not touch the database.

It must not import `sqlite3` or `RuntimeDatabase`.

### 4.2 `position_accounting.py`

Owns pure deterministic accounting policy:

```text
normalized fill
+ authoritative order side
+ current open position snapshots
-> accounting plan
```

It must not read or write the database, perform network I/O, serialize JSON, resolve plugins dynamically, or read global configuration.

### 4.3 `lifecycle_persistence.py`

Owns the concrete SQLite adapter:

```text
SqliteLifecyclePersistence
```

It receives exactly one already-created `RuntimeDatabase` and one already-resolved accounting policy through constructor injection.

It may not create a database connection per method call.

### 4.4 Startup binding

The accounting policy is selected once at construction/startup:

```python
writer = SqliteLifecyclePersistence(db, NettingPositionAccountingV1())
```

No dynamic import, filesystem scan, string registry lookup, or dependency construction is allowed inside `register_order_acknowledgement()` or `apply_fill()`.

---

## 5. Typed values and normalization

### 5.1 Decimal authority

All monetary and quantity inputs use `decimal.Decimal` inside the core API.

Forbidden inputs:

- float;
- NaN;
- positive/negative infinity;
- negative quantity;
- negative price;
- negative fee.

Canonical persistence text is produced exactly once at the SQLite boundary using non-scientific fixed notation with unnecessary trailing zeros removed.

Examples:

```text
Decimal("1.2300") -> "1.23"
Decimal("0E-8")   -> "0"
Decimal("100")    -> "100"
```

Accounting arithmetic uses an explicit local Decimal context:

```text
precision = 34
rounding = ROUND_HALF_EVEN
```

It may not depend on the process-global Decimal context.

### 5.2 Time authority

Public commands use timezone-aware UTC `datetime` values.

Naive datetimes and non-UTC offsets are rejected.

Persistence serialization is exactly once at the database boundary to canonical ISO-8601 text ending in `Z`.

### 5.3 String identity

Identity/scope fields must be non-empty after validation and are never silently stripped, lowercased, remapped, or guessed by persistence code.

Venue adapter normalization happens before this API.

### 5.4 No internal JSON

Commands, plans, and results are typed Python objects. No JSON encode/decode is allowed between the accounting policy and persistence adapter.

---

## 6. Public API

Two narrow Protocols are required.

```python
class OrderAcknowledgementWriter(Protocol):
    def register_order_acknowledgement(
        self,
        command: OrderAcknowledgementCommand,
    ) -> OrderAcknowledgementResult: ...

class FillSequenceWriter(Protocol):
    def apply_fill(
        self,
        command: FillApplicationCommand,
    ) -> FillApplicationResult: ...
```

The concrete `SqliteLifecyclePersistence` implements both Protocols directly. No service-to-repository-to-DAO call chain is introduced on the hot path.

### 6.1 Result outcomes

```text
APPLIED
REPLAY_NOOP
```

Conflicts and failed preconditions raise typed exceptions; they are never encoded as a success result.

### 6.2 Required exception hierarchy

```text
LifecyclePersistenceError
├── LifecycleValidationError
├── LifecyclePreconditionError
├── LifecycleConflictError
└── LifecycleInvariantError
```

Original SQLite or arithmetic exceptions remain available through exception chaining.

No bare `except` and no swallowed exception are allowed.

---

## 7. Order acknowledgement transaction

### 7.1 Command

`OrderAcknowledgementCommand` contains:

```text
venue
account_scope
order_id
execution_intent_id
attempt_id
client_order_id
symbol
side                  BUY / SELL
quantity              Decimal > 0
price                 Decimal >= 0
order_type             MARKET / LIMIT
acknowledged_at        UTC datetime
```

The persisted initial order status is exactly `OPEN`.

The command does not contain raw venue JSON.

### 7.2 Exact new-application transaction

One `BEGIN IMMEDIATE` transaction performs:

1. one exact replay lookup by authoritative order identity;
2. update the exact `dispatch_attempts` row from `SUBMITTED` to `ACCEPTED`;
3. insert the `order_states` row;
4. update the exact `execution_states` row from `DISPATCHED` to `ACKNOWLEDGED`.

The two parent updates must each affect exactly one row.

Required dispatch precondition:

```text
execution_intent_id
attempt_id
venue
account_scope
client_order_id
status = SUBMITTED
```

Required execution-state precondition:

```text
execution_intent_id
last_attempt_id = attempt_id
status = DISPATCHED
```

Any zero-row or multi-row parent mutation raises `LifecyclePreconditionError` and rolls back the whole transaction.

### 7.3 Exact replay

If the authoritative order row already exists and all immutable order payload fields exactly match the normalized command:

```text
outcome = REPLAY_NOOP
committed_mutations = 0
```

Parent lifecycle rows may already have advanced beyond ACCEPTED/ACKNOWLEDGED; exact replay must not move them backwards.

### 7.4 Conflicting replay

If the same authoritative order identity exists but any immutable payload field differs, raise `LifecycleConflictError` with zero committed mutations.

`INSERT OR IGNORE` and `INSERT OR REPLACE` are forbidden.

### 7.5 Statement budget

New order acknowledgement:

```text
reads <= 1
committed authoritative SQL mutations = 3
DB reconnects = 0
```

Exact replay:

```text
reads = 1
committed authoritative SQL mutations = 0
```

---

## 8. Fill application transaction

### 8.1 Command

`FillApplicationCommand` contains:

```text
venue
account_scope
fill_id
order_id
symbol
quantity              Decimal > 0
price                 Decimal >= 0
fee                    Decimal >= 0
fee_currency
occurred_at            UTC datetime
recorded_at            UTC datetime
order_status_after     PARTIALLY_FILLED / FILLED
```

Order side is never accepted from the caller. It is read once from the authoritative `order_states` row.

### 8.2 Transaction snapshot

One `BEGIN IMMEDIATE` transaction performs at most:

1. one existing-fill lookup;
2. one authoritative order lookup;
3. one open-position lookup returning both LONG and SHORT for the exact venue/account/symbol;
4. one pure accounting-policy call;
5. all fill, order, accounting, and position mutations;
6. one commit.

No duplicate read of the same fill, order, or position set is allowed in one new application.

### 8.3 Order preconditions

Authoritative order identity and symbol must match the command.

Allowed transitions inside B4.3B:

```text
OPEN -> PARTIALLY_FILLED
OPEN -> FILLED
PARTIALLY_FILLED -> PARTIALLY_FILLED
PARTIALLY_FILLED -> FILLED
```

All other current/target combinations raise `LifecyclePreconditionError`.

B4.3B does not implement cancellation, rejection, expiry, or reconciliation transitions.

### 8.4 New fill mutations

For one accounting event:

1. insert `fill_states`;
2. update `order_states.status` and `updated_at`;
3. insert one `position_accounting_details` event;
4. insert or update one `position_states` row.

For a valid two-event zero crossing:

1. insert `fill_states`;
2. update `order_states`;
3. insert event 1;
4. update the old position;
5. insert event 2;
6. insert or update the new/same-side position.

No `execution_states` mutation is included in B4.3B fill application. Full execution/order lifecycle coordination belongs to B10.

### 8.5 Exact fill replay

If the authoritative fill row already exists:

- immutable fill payload must exactly match the normalized command;
- accounting events for that fill must be present with contiguous deterministic event numbers `1` or `1,2`;
- event count must be one or two;
- no mutation is permitted.

Successful exact replay returns:

```text
outcome = REPLAY_NOOP
committed_mutations = 0
```

If the fill row matches but its accounting sequence is absent, non-contiguous, duplicated, or longer than two events, raise `LifecycleInvariantError`.

If the same fill identity has different immutable payload, raise `LifecycleConflictError`.

### 8.6 Statement budget

New one-event fill:

```text
reads <= 3
committed authoritative SQL mutations <= 4
```

New two-event zero crossing:

```text
reads <= 3
committed authoritative SQL mutations <= 6
```

Exact replay:

```text
reads <= 2
committed authoritative SQL mutations = 0
```

All paths:

```text
DB reconnects = 0
one explicit transaction
```

---

## 9. Default accounting policy — `NettingPositionAccountingV1`

The default policy is pure and replaceable. It implements an opposite-first netting model.

### 9.1 Signed quantity convention

```text
LONG exposure  = positive
SHORT exposure = negative
```

Accounting `delta_qty` follows signed net-exposure change.

### 9.2 Direction mapping

For a BUY fill:

1. reduce/close an existing SHORT first;
2. apply any residual to an existing LONG;
3. otherwise open a new LONG.

For a SELL fill:

1. reduce/close an existing LONG first;
2. apply any residual to an existing SHORT;
3. otherwise open a new SHORT.

The schema permits one open LONG and one open SHORT in the same scope. The V1 policy still uses opposite-first netting. A later hedge-mode policy may be injected without changing the persistence adapter or schema.

### 9.3 Event sequence

One fill produces one or two events only.

Single-event cases:

```text
OPEN
INCREASE
REDUCE
CLOSE
```

Zero-crossing case:

```text
1 = REDUCE or CLOSE old opposite position
2 = OPEN or INCREASE same-direction position
```

A true crossing through zero requires event 1 to be `CLOSE`.

### 9.4 Deterministic IDs

Accounting event IDs and newly opened position IDs are deterministic lowercase SHA-256 identifiers derived from canonical length-delimited identity components.

Required prefixes:

```text
pae_<64 lowercase hex>
pos_<64 lowercase hex>
```

No UUID, wall-clock entropy, random source, Python `hash()`, or process-dependent representation is allowed.

### 9.5 Average entry price

Opening:

```text
avg_entry_price = fill price
```

Increasing an existing same-side position:

```text
new_avg =
(old_quantity * old_avg + added_quantity * fill_price)
/
(old_quantity + added_quantity)
```

Reducing or closing preserves the historical average entry price on the existing position row.

### 9.6 Realized PnL

Gross closing PnL:

```text
LONG:  close_qty * (fill_price - avg_entry_price)
SHORT: close_qty * (avg_entry_price - fill_price)
```

Event realized PnL is net of the fee allocated to that event.

Position `realized_pnl` is cumulative net realized PnL, including fees attributed to that position.

### 9.7 Deterministic fee attribution

A fill fee is represented exactly once across its accounting sequence:

```text
event 1 fee = full fill fee
event 2 fee = 0
```

This avoids rounding-dependent fee splitting and guarantees the event-fee sum equals the authoritative fill fee exactly.

For a zero crossing, the full fee is attributed to the old-position close event. This is an explicit V1 policy and may be replaced only through a versioned policy change.

### 9.8 Position mutation rules

- OPEN/INCREASE positions have quantity greater than zero and status `OPEN`;
- CLOSE produces quantity `0`, status `CLOSED`, and `closed_at = fill occurred_at`;
- REDUCE keeps status `OPEN`;
- changed positions set `unrealized_pnl = 0` because no authoritative mark price is part of this transaction;
- opening/increasing/reducing/closing sets `updated_at = recorded_at`;
- new position `opened_at = fill occurred_at`.

### 9.9 Invariant failures

The policy raises `LifecycleInvariantError` for impossible snapshots, including:

- duplicate open LONG or SHORT inputs;
- non-positive open-position quantity;
- CLOSED row supplied as open snapshot;
- more than two generated events;
- residual quantity not fully consumed;
- event numbers other than contiguous `1` or `1,2`;
- event fee sum not equal to authoritative fill fee;
- final open position with non-positive quantity.

---

## 10. Transaction and concurrency behavior

### 10.1 One writer transaction

Every public mutation owns exactly one `BEGIN IMMEDIATE` transaction through `RuntimeDatabase.transaction(immediate=True)`.

Nested lifecycle transactions are forbidden.

### 10.2 Concurrent duplicate application

With one SQLite database and `BEGIN IMMEDIATE`:

- one concurrent writer applies first;
- the second writer observes the committed authoritative row;
- an exact duplicate returns `REPLAY_NOOP`;
- a conflicting duplicate raises `LifecycleConflictError`.

No blind retry loop is added.

### 10.3 Rollback

Any validation, precondition, policy, FK, CHECK, UNIQUE, row-count, or injected failure rolls back the entire public operation.

Tests must prove no partial order, fill, event, or position state survives.

---

## 11. Statement-count instrumentation

Instrumentation is implemented inside the concrete persistence adapter, not by enabling a permanent global SQLite trace callback.

Each operation reports immutable statistics:

```text
read_statements
attempted_mutations
committed_mutations
transaction_count
db_connection_identity
```

Rules:

- each adapter-owned SELECT increments `read_statements` exactly once;
- each adapter-owned INSERT/UPDATE/DELETE increments `attempted_mutations` exactly once;
- `committed_mutations = attempted_mutations` only after successful commit;
- rollback exposes zero committed mutations in the raised typed error metadata or test observer;
- BEGIN/COMMIT/ROLLBACK and PRAGMA are not authoritative mutations;
- no trigger-internal statement is double-counted as an adapter mutation.

The same injected connection object identity must remain unchanged before and after each hot-path operation.

---

## 12. Performance contract

### 12.1 Fair baseline

The direct baseline must perform the same:

- input validation;
- Decimal normalization;
- UTC serialization;
- transaction mode;
- SQL statements;
- durability pragmas;
- database schema;
- unique data generation;
- replay/conflict checks required by that measured path.

The baseline may bypass Protocol dispatch and injected accounting-policy indirection, but may not omit required correctness work.

### 12.2 Benchmark topology

- Python 3.11;
- two fresh temporary SQLite database files, one baseline and one modular;
- one persistent `RuntimeDatabase` connection per database;
- WAL and synchronous FULL remain enabled;
- warm-up operations excluded;
- baseline and modular samples interleaved or round order alternated;
- no network calls;
- no sleep-based timing;
- `time.perf_counter_ns()`;
- same process and same CI job.

### 12.3 Required measured operations

At minimum:

1. new order acknowledgement;
2. new one-event fill;
3. new two-event zero crossing;
4. exact order replay;
5. exact fill replay.

### 12.4 Required evidence

JSON artifact contains:

```text
schema_version
head_sha
run_id
python_version
platform
sample_count
warmup_count
operation
baseline_p50_ns
baseline_p95_ns
modular_p50_ns
modular_p95_ns
p50_ratio
p95_ratio
baseline_statement_counts
modular_statement_counts
connection_reuse
live = FORBIDDEN
```

### 12.5 Gate

For every required measured operation:

```text
modular p95 / equivalent direct baseline p95 <= 1.10
```

Statement counts must meet Section 7/8 exactly or more strictly.

No absolute hosted-runner wall-clock threshold is used.

A benchmark that omits durability, uses different SQL, reconnects only one path, or excludes validation from only one path is invalid even if its ratio passes.

Performance optimization may not weaken FULL durability, FK/CHECK/UNIQUE constraints, deterministic replay, typed validation, or fail-closed behavior.

---

## 13. Required test matrix

### B4.3B1 pure accounting tests

- Decimal and UTC validation;
- canonical decimal/time serialization;
- deterministic ID stability and domain separation;
- BUY open LONG;
- BUY increase LONG;
- SELL reduce LONG;
- SELL close LONG;
- SELL cross LONG to SHORT;
- SELL increase existing SHORT after crossing;
- mirrored BUY/SHORT cases;
- weighted average with explicit Decimal context;
- realized PnL for LONG and SHORT;
- full fee exactly once;
- event numbers contiguous;
- no database imports or I/O in policy module;
- policy input immutability.

### B4.3B2 atomic persistence tests

- exact order acknowledgement three-mutation transaction;
- wrong dispatch/execution precondition rollback;
- exact order replay zero mutations;
- conflicting order replay rejected;
- one-event fill transaction and statement count;
- zero-crossing six-mutation transaction;
- exact fill replay zero mutations;
- conflicting fill replay rejected;
- incomplete replay accounting sequence rejected;
- wrong order scope/symbol rejected;
- invalid order status transition rejected;
- FK/CHECK/UNIQUE failure full rollback;
- injected failure after each mutation boundary full rollback;
- same connection reused;
- one transaction per public mutation;
- concurrent exact duplicate converges to APPLIED + REPLAY_NOOP;
- concurrent conflicting duplicate yields one APPLIED + one conflict;
- no reconnect, no JSON, no ORM, no network.

### B4.3B3 performance tests

- benchmark baseline equivalence proof;
- minimum sample/warm-up enforcement;
- all required operation records present;
- p95 ratio <= 1.10;
- statement-count budgets;
- exact SHA/run binding;
- artifact schema validation;
- LIVE FORBIDDEN.

### Regression

Every unit also runs:

- B4.3A targeted schema tests;
- B4.2A frozen tests;
- migration regression;
- full pytest;
- Simple CI;
- Freqtrade Validation;
- exact artifact audit.

---

## 14. Authorized implementation surfaces

### B4.3B1

Preferred exact files:

1. `implementation/src/atos/lifecycle_types.py`
2. `implementation/src/atos/position_accounting.py`
3. `implementation/tests/test_position_accounting.py`

### B4.3B2

Preferred exact files:

1. `implementation/src/atos/lifecycle_persistence.py`
2. `implementation/tests/test_lifecycle_persistence.py`

`runtime_db.py` and migration 0001–0004 are frozen and must not change.

### B4.3B3

Preferred exact files:

1. `implementation/scripts/benchmark_b4_3b_lifecycle.py`
2. `implementation/tests/test_b4_3b_performance_contract.py`

Temporary GitHub-only validation workflows are permitted on non-product CI branches and must never merge into `main`.

Any additional product file requires a documented scope amendment before implementation.

---

## 15. Gate ladder

For each B4.3B subunit:

1. exact base/head/scope audit;
2. syntax and import;
3. targeted tests;
4. prior frozen B4.3 regression;
5. migration regression;
6. full pytest;
7. semantic whole-surface audit;
8. exact-SHA Simple CI;
9. exact-SHA Freqtrade Validation;
10. artifact audit;
11. merge with expected head SHA;
12. exact post-merge gate;
13. freeze subunit.

B4.3B3 additionally requires the performance artifact and p95 gate.

B4.3B is frozen only after B4.3B1, B4.3B2, and B4.3B3 are each merged/frozen.

---

## 16. Decision

```text
B4.3A: MERGED / FROZEN
B4.3B CONTRACT: READY FOR ARCHITECT AUDIT
B4.3B1 IMPLEMENTATION: NOT STARTED
B4.3B2 IMPLEMENTATION: NOT STARTED
B4.3B3 IMPLEMENTATION: NOT STARTED
B5: NOT STARTED
LIVE: FORBIDDEN
```
