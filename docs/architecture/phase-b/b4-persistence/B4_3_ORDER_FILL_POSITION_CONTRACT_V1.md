# B4.3 Order / Fill / Position Persistence Contract V1

**Baseline main**: `0dbe45bc80b1d85140e1bceaa1962952af07a778`  
**Phase**: B4.3 design freeze  
**Runtime shape**: modular monolith  
**LIVE**: FORBIDDEN

---

## 1. Purpose

B4.3 defines the authoritative persistence contract for the post-dispatch lifecycle:

```text
DispatchAttempt
  -> OrderState
  -> FillState
  -> PositionState
  -> PositionAccountingDetail
```

The contract must satisfy both:

1. **Modularity**: venue adapters, reconciliation, accounting, and persistence can be replaced and tested independently.
2. **Single-process efficiency**: the trading hot path remains direct in-process calls with one SQLite authority, no RPC, no message bus, no ORM, and no repeated JSON serialization between core modules.

B4.3 is schema and contract work only. It does not implement venue networking, paper fills, recovery, reconciliation, or LIVE execution.

---

## 2. Scope

B4.3 migration 0004 will create:

1. `order_states`
2. `fill_states`
3. `position_states`
4. `position_accounting_details`

It may also add a UNIQUE backing index to the already-frozen `dispatch_attempts` table so that an order can reference the exact dispatch attempt together with its venue scope.

### Explicit exclusions

- no OKX network call
- no paper executor behavior
- no order transition service
- no fill polling
- no reconciliation engine
- no risk-state persistence
- no market/account snapshot persistence
- no B5 idempotency implementation
- no B10 lifecycle implementation
- no LIVE enablement

---

## 3. Mandatory design corrections to B1 V3.3

The original B1 V3.3 entity list is directionally correct but insufficient for authoritative multi-venue persistence.

### 3.1 Order identity must be venue scoped

A venue-generated `order_id` is not assumed globally unique across venues or accounts.

Authoritative order identity:

```text
(venue, account_scope, order_id)
```

`order_states` must also bind to the exact dispatch attempt:

```text
(execution_intent_id, attempt_id, venue, account_scope)
```

This prevents an order response from being attached to the wrong retry attempt, venue, or account.

### 3.2 Fill identity must be venue scoped

A venue fill identifier is not assumed globally unique.

Authoritative fill identity:

```text
(venue, account_scope, fill_id)
```

Each fill must reference the exact venue-scoped order:

```text
(venue, account_scope, order_id)
```

### 3.3 Position authority must be account scoped

A net position is scoped by:

```text
(venue, account_scope, symbol, side)
```

V1 permits at most one OPEN net position for that tuple. Historical CLOSED positions remain preserved.

### 3.4 Every accounting event must bind to one fill

`PositionAccountingDetail` must include the source fill identity.

A UNIQUE constraint on the source fill identity guarantees:

```text
one accepted fill -> at most one position accounting mutation
```

Without this link, crash replay can double-apply a fill while still producing syntactically valid rows. That is not acceptable.

---

## 4. Schema contract

### 4.1 Required backing index on dispatch_attempts

Migration 0004 adds a UNIQUE index over:

```text
(execution_intent_id, attempt_id, venue, account_scope)
```

The existing B4.2A columns and migration checksum remain unchanged. Migration 0004 only adds a new index against the existing table.

### 4.2 order_states

Required columns:

| Column | Contract |
|---|---|
| venue | TEXT NOT NULL |
| account_scope | TEXT NOT NULL |
| order_id | TEXT NOT NULL |
| execution_intent_id | TEXT NOT NULL |
| attempt_id | TEXT NOT NULL |
| client_order_id | TEXT NOT NULL |
| symbol | TEXT NOT NULL |
| side | BUY / SELL |
| quantity | Decimal encoded as TEXT |
| price | Decimal encoded as TEXT; market may use `0` |
| order_type | MARKET / LIMIT |
| status | NEW / PENDING_SUBMIT / OPEN / PARTIALLY_FILLED / FILLED / CANCEL_REQUESTED / CANCEL_PENDING / CANCELLED / REJECTED / EXPIRED / UNKNOWN |
| created_at | ISO-8601 UTC TEXT |
| updated_at | ISO-8601 UTC TEXT |

Primary key:

```text
(venue, account_scope, order_id)
```

Required constraints:

- composite FK to exact `dispatch_attempts` ownership tuple
- UNIQUE `(venue, account_scope, client_order_id)`
- identity columns cannot be changed after insertion
- `ON DELETE RESTRICT`

Required indexes:

```text
idx_order_states_execution
idx_order_states_client_order
idx_order_states_status
```

### 4.3 fill_states

Required columns:

| Column | Contract |
|---|---|
| venue | TEXT NOT NULL |
| account_scope | TEXT NOT NULL |
| fill_id | TEXT NOT NULL |
| order_id | TEXT NOT NULL |
| quantity | Decimal encoded as TEXT |
| price | Decimal encoded as TEXT |
| fee | Decimal encoded as TEXT |
| fee_currency | TEXT NOT NULL |
| timestamp | ISO-8601 UTC TEXT |

Primary key:

```text
(venue, account_scope, fill_id)
```

Required constraints:

- composite FK to `(venue, account_scope, order_id)`
- immutable after insertion
- `ON DELETE RESTRICT`

Required index:

```text
idx_fill_states_order_time
```

### 4.4 position_states

Required columns:

| Column | Contract |
|---|---|
| position_id | TEXT PRIMARY KEY |
| venue | TEXT NOT NULL |
| account_scope | TEXT NOT NULL |
| symbol | TEXT NOT NULL |
| side | LONG / SHORT |
| quantity | Decimal encoded as TEXT |
| avg_entry_price | Decimal encoded as TEXT |
| realized_pnl | Decimal encoded as TEXT |
| unrealized_pnl | Decimal encoded as TEXT |
| status | OPEN / CLOSED |
| opened_at | ISO-8601 UTC TEXT |
| closed_at | nullable ISO-8601 UTC TEXT |
| updated_at | ISO-8601 UTC TEXT |

Required constraints:

- one OPEN position per `(venue, account_scope, symbol, side)` using a partial UNIQUE index
- OPEN requires `closed_at IS NULL`
- CLOSED requires `closed_at IS NOT NULL`
- identity/scope columns cannot change after insertion

Required indexes:

```text
idx_position_states_scope_symbol
idx_position_states_status
```

### 4.5 position_accounting_details

Required columns:

| Column | Contract |
|---|---|
| event_id | TEXT PRIMARY KEY |
| position_id | TEXT NOT NULL |
| source_fill_venue | TEXT NOT NULL |
| source_fill_account_scope | TEXT NOT NULL |
| source_fill_id | TEXT NOT NULL |
| event_type | OPEN / INCREASE / REDUCE / CLOSE |
| delta_qty | signed Decimal encoded as TEXT |
| price | Decimal encoded as TEXT |
| fee | Decimal encoded as TEXT |
| realized_pnl | Decimal encoded as TEXT |
| timestamp | ISO-8601 UTC TEXT |

Required constraints:

- FK to `position_states(position_id)`
- composite FK to exact source fill
- UNIQUE source fill identity
- immutable after insertion
- `ON DELETE RESTRICT`

Required indexes:

```text
idx_position_accounting_position_time
idx_position_accounting_fill
```

---

## 5. Transaction boundaries

### 5.1 Order acknowledgement transaction

One DB transaction may:

1. insert or update `order_states`
2. update the aggregate `execution_states`
3. update the authoritative `dispatch_attempts` status

The network call remains outside the transaction.

### 5.2 Fill reconciliation transaction

For one newly accepted fill, one DB transaction must:

1. insert immutable `fill_states`
2. insert immutable `position_accounting_details`
3. insert or update `position_states`
4. update `order_states` if fill progress changes order status
5. update `execution_states` if lifecycle progress changes

If any statement fails, the entire transaction rolls back.

The UNIQUE source-fill constraint makes replay idempotent. Recovery may replay the transaction safely; it may not double-account the fill.

---

## 6. Modular-monolith efficiency contract

B4.3 persistence is modular in code ownership but monolithic in runtime execution.

### Required

- same Python process for core decision, lifecycle, and persistence modules
- direct typed method calls across core module boundaries
- one injected `RuntimeDatabase` authority
- one explicit SQLite transaction per atomic lifecycle mutation
- no ORM
- no HTTP/RPC/message bus between core modules
- no JSON encode/decode between core modules on the hot path
- venue JSON is normalized once in the adapter boundary
- registry/plugin resolution occurs at startup, never per fill or per cycle
- metrics and notifications must not block the transaction path

### Forbidden

- one SQLite connection per repository call
- autocommit per statement
- polling the DB between in-process modules to exchange state
- duplicate reads of the same order/fill within one transaction
- cross-module mutation of private state
- background writer that can reorder authoritative lifecycle writes

---

## 7. Performance budgets

These are contract budgets for the implementation and benchmark gate.

| Operation | Budget |
|---|---|
| register one order acknowledgement | no more than 3 authoritative SQL mutations in one transaction |
| apply one new fill through position accounting | no more than 5 authoritative SQL mutations in one transaction |
| adapter-to-core serialization | exactly one normalization at ingress; zero internal JSON round trips |
| DB connection acquisition | existing injected connection; zero reconnects on hot path |
| plugin lookup | zero dynamic imports/scans on hot path |
| modular overhead | p95 no worse than 10% versus an equivalent direct-call baseline in the same CI runner |

Timing gates must use a relative same-run baseline, not an absolute wall-clock threshold, to reduce CI hardware noise.

Correctness remains fail-closed: a performance optimization may not weaken transaction durability, ownership FKs, or idempotency.

---

## 8. Migration and compatibility rules

- migration versions remain contiguous: `[1, 2, 3, 4]`
- migrations 0001, 0002, and 0003 remain byte-for-byte unchanged
- V1/V2/V3 full checksums remain unchanged
- real V3 -> V4 migration preserves every existing row exactly
- fresh V4 and real upgrade V3 -> V4 must produce equivalent schema
- migration 0004 is atomic and retry safe
- failed 0004 leaves schema version at 3 and leaves no partial B4.3 tables/indexes/triggers
- current data is empty for new B4.3 tables; no fabricated backfill is allowed

---

## 9. Required test matrix

### Schema

- fresh V4 creates all four tables
- exact `table_info` tuples for every table
- exact composite PK grouping
- exact FK grouping, target columns, and delete policy
- exact named indexes and index columns
- exact UNIQUE backing for dispatch ownership, client order identity, one-open-position, and source-fill idempotency
- CHECK constraints for enums and OPEN/CLOSED timestamp semantics

### Ownership and collision

- same `order_id` allowed in different venue/account scopes
- same `fill_id` allowed in different venue/account scopes
- wrong attempt ownership rejected
- wrong order scope rejected
- wrong fill scope rejected
- duplicate client order identity in one venue/account rejected
- duplicate source fill accounting rejected

### Immutability and mutability

- fill rows cannot update or delete
- accounting rows cannot update or delete
- order identity cannot change, while legal lifecycle columns remain mutable
- position identity/scope cannot change, while accounting fields remain mutable

### Migration

- V1/V2/V3 checksums unchanged
- real V3 -> V4 exact preservation after close/reopen
- no-op migration at V4
- rollback on injected statement failure
- future-schema and drift rejection remain fail-closed

### Performance

- direct-call modular path and equivalent baseline run in the same process
- p50/p95 and SQL statement counts recorded in artifact
- p95 modular overhead <= 10%
- no reconnect and no internal JSON serialization on hot path

---

## 10. Authorized implementation surface

Preferred exact files for B4.3 implementation:

1. `implementation/src/atos/runtime_migrations.py`
2. `implementation/tests/test_order_fill_position_persistence_schema.py`
3. `implementation/tests/test_b4_3_persistence_performance.py`

A fourth production file is not authorized during schema implementation unless the architect explicitly freezes a separate bounded subunit.

The latent `_utc()` missing `datetime` import in `runtime_state.py` is real but is not silently bundled into migration 0004. It must be repaired as an independently auditable maintenance unit.

---

## 11. Gate ladder

1. scope and exact-SHA audit
2. syntax/import
3. targeted B4.3 schema tests
4. migration regression
5. full pytest
6. ownership/idempotency semantic audit
7. relative performance artifact
8. exact-SHA Simple CI
9. Freqtrade Validation
10. artifact audit
11. merge
12. exact post-merge gate
13. freeze

---

## 12. Decision

```text
B4.3 DESIGN CONTRACT: READY FOR ARCHITECT AUDIT
IMPLEMENTATION: NOT STARTED
B5: NOT STARTED
LIVE: FORBIDDEN
```
