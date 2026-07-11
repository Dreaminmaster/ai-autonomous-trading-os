# B4.3 Order / Fill / Position Persistence Contract V1.1

**Baseline main**: `0dbe45bc80b1d85140e1bceaa1962952af07a778`  
**Runtime shape**: modular monolith  
**LIVE**: FORBIDDEN

---

## 1. Purpose

B4.3 defines the authoritative persistence boundary for:

```text
DispatchAttempt
  -> OrderState
  -> FillState
  -> PositionState
  -> PositionAccountingDetail
```

The design must provide replaceable modules without turning the trading hot path into a stack of network calls, message queues, repeated serialization, or per-call database connections.

---

## 2. Bounded delivery units

B4.3 is split before implementation so schema work is not mixed with runtime orchestration.

### B4.3A — Lifecycle persistence schema

Creates migration 0004 and exact schema tests only:

1. `order_states`
2. `fill_states`
3. `position_states`
4. `position_accounting_details`
5. required UNIQUE backing index on existing `dispatch_attempts`

### B4.3B — Atomic lifecycle persistence API and performance gate

A later, separately frozen unit will implement:

- typed repository/service interfaces
- atomic order-acknowledgement transaction
- atomic fill/accounting/position transaction
- statement-count instrumentation
- direct-call benchmark and p50/p95 artifact

B4.3B may not start until B4.3A is merged and frozen.

### Exclusions from B4.3A

- no OKX or other venue network calls
- no paper executor behavior
- no order transition service
- no fill polling
- no reconciliation engine
- no risk-state persistence
- no market/account snapshot persistence
- no runtime repository implementation
- no B5 idempotency implementation
- no B10 lifecycle implementation
- no LIVE enablement

---

## 3. Mandatory corrections to B1 V3.3 storage identity

The B1 entity list is conceptually correct, but its original identity fields are insufficient for authoritative multi-venue storage.

### 3.1 Venue-scoped order identity

A venue order identifier is not assumed globally unique.

```text
order identity = (venue, account_scope, order_id)
```

Every order must bind to the exact dispatch attempt that produced or discovered it:

```text
(execution_intent_id, attempt_id, venue, account_scope)
```

### 3.2 Venue-scoped fill identity

```text
fill identity = (venue, account_scope, fill_id)
```

Every fill references the exact venue-scoped order:

```text
(venue, account_scope, order_id)
```

### 3.3 Account-scoped position authority

A net position is scoped by:

```text
(venue, account_scope, symbol, side)
```

V1 permits at most one OPEN position for that tuple. CLOSED historical positions remain preserved.

### 3.4 Fill-linked accounting with deterministic event sequence

Every position accounting event must bind to one fill and a deterministic event number:

```text
(source_fill_venue,
 source_fill_account_scope,
 source_fill_id,
 source_fill_event_no)
```

A fill normally produces event number `1`. A fill that crosses through zero may deterministically produce two events, for example:

```text
1 = CLOSE old position
2 = OPEN opposite position
```

The composite UNIQUE constraint guarantees at-most-once application of each deterministic fill event while still supporting valid multi-event fills.

---

## 4. Migration 0004 schema contract

### 4.1 dispatch_attempts backing identity

Migration 0004 adds a UNIQUE index over existing columns:

```text
(execution_intent_id, attempt_id, venue, account_scope)
```

Migration 0003 remains byte-for-byte unchanged.

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
| price | Decimal encoded as TEXT; market order may use `0` |
| order_type | MARKET / LIMIT |
| status | NEW / PENDING_SUBMIT / OPEN / PARTIALLY_FILLED / FILLED / CANCEL_REQUESTED / CANCEL_PENDING / CANCELLED / REJECTED / EXPIRED / UNKNOWN |
| created_at | ISO-8601 UTC TEXT |
| updated_at | ISO-8601 UTC TEXT |

Primary key:

```text
(venue, account_scope, order_id)
```

Required constraints:

- composite FK to exact dispatch-attempt ownership tuple
- UNIQUE `(venue, account_scope, client_order_id)`
- identity and ownership columns immutable after insert
- lifecycle columns remain mutable for B10
- all FKs use `ON DELETE RESTRICT`

Required named indexes:

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

- composite FK to exact venue-scoped order
- entire row immutable after insert
- `ON DELETE RESTRICT`

Required named index:

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

- partial UNIQUE index for one OPEN position per `(venue, account_scope, symbol, side)`
- OPEN requires `closed_at IS NULL`
- CLOSED requires `closed_at IS NOT NULL`
- identity/scope columns immutable after insert
- accounting/lifecycle columns remain mutable for B4.3B/B10

Required named indexes:

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
| source_fill_event_no | INTEGER NOT NULL, >= 1 |
| event_type | OPEN / INCREASE / REDUCE / CLOSE |
| delta_qty | signed Decimal encoded as TEXT |
| price | Decimal encoded as TEXT |
| fee | Decimal encoded as TEXT |
| realized_pnl | Decimal encoded as TEXT |
| timestamp | ISO-8601 UTC TEXT |

Required constraints:

- FK to `position_states(position_id)`
- composite FK to exact source fill
- UNIQUE source fill identity plus deterministic event number
- entire row immutable after insert
- all FKs use `ON DELETE RESTRICT`

Required named indexes:

```text
idx_position_accounting_position_time
idx_position_accounting_fill
```

---

## 5. Modular-monolith runtime contract

These rules apply to B4.3B and later lifecycle work, but B4.3A must not introduce schema choices that make them impossible.

### Required

- one Python process for core lifecycle modules
- direct typed calls between core modules
- one injected `RuntimeDatabase` authority
- one explicit SQLite transaction per atomic lifecycle mutation
- venue JSON normalized once at the adapter boundary
- plugin resolution at startup, never per order/fill/cycle
- metrics and notifications outside the blocking transaction path

### Forbidden

- ORM introduction
- HTTP/RPC/message bus between core modules
- JSON encode/decode between core modules on the hot path
- one DB connection per repository call
- autocommit per statement
- DB polling used as in-process module communication
- duplicate reads of the same order/fill inside one atomic operation
- background writer that can reorder authoritative lifecycle writes

---

## 6. B4.3B transaction and performance budgets

These are frozen now but enforced only when B4.3B has a real runtime path.

| Operation | Budget |
|---|---|
| register one order acknowledgement | <= 3 authoritative SQL mutations in one transaction |
| apply one fill event sequence | <= 5 base mutations plus one extra accounting/position mutation for a valid zero-crossing second event |
| adapter-to-core normalization | exactly once at ingress; zero internal JSON round trips |
| DB connection acquisition | existing injected connection; zero reconnects on hot path |
| plugin lookup | zero dynamic imports/scans on hot path |
| modular overhead | p95 <= 10% slower than equivalent direct-call baseline in the same CI runner |

Timing uses a same-run relative baseline, never an absolute hosted-runner wall-clock threshold.

Performance optimization may not weaken FULL durability, ownership FKs, deterministic replay, or fail-closed behavior.

---

## 7. Migration and compatibility rules

- migration plan becomes `[1, 2, 3, 4]`
- migrations 0001/0002/0003 remain byte-for-byte unchanged
- V1/V2/V3 full checksums remain unchanged
- real V3 -> V4 migration preserves all existing rows exactly after close/reopen
- fresh V4 and real V3 -> V4 produce equivalent schema
- migration 0004 is atomic and retry safe
- failed 0004 leaves schema version at 3 with no partial B4.3 objects
- new tables receive no fabricated backfill

---

## 8. B4.3A required test matrix

### Exact schema proof

- fresh V4 creates all four tables
- exact `table_info` tuples
- exact composite PK grouping/order
- exact FK grouping, target columns, and delete policy
- exact named indexes and `index_info` columns
- exact UNIQUE backing for dispatch ownership, client-order identity, one-open-position, and deterministic source-fill event identity

### Ownership and collision

- same order ID allowed across different venue/account scopes
- same fill ID allowed across different venue/account scopes
- wrong dispatch-attempt ownership rejected
- wrong order scope rejected
- wrong fill scope rejected
- duplicate client-order identity in one venue/account rejected
- duplicate source fill plus event number rejected
- same fill with event numbers 1 and 2 accepted

### Immutability and allowed mutability

- fills cannot update or delete
- accounting events cannot update or delete
- order identity/ownership cannot change
- order lifecycle columns can change
- position identity/scope cannot change
- position accounting/lifecycle columns can change subject to CHECK constraints

### Migration

- V1/V2/V3 checksums unchanged
- real V3 -> V4 exact preservation
- no-op at V4
- injected migration failure rolls back every 0004 object
- future-schema, gaps, and drift remain fail-closed

B4.3A does not contain a timing benchmark because no runtime persistence API exists yet. Structural efficiency is protected by scope; measurable p50/p95 and statement-count gates belong to B4.3B.

---

## 9. Authorized B4.3A implementation surface

Preferred exact files:

1. `implementation/src/atos/runtime_migrations.py`
2. `implementation/tests/test_order_fill_position_persistence_schema.py`

No repository/service production file and no performance test file are authorized in B4.3A.

The latent `_utc()` missing `datetime` import in `runtime_state.py` is real but remains a separate maintenance unit. It must not be silently bundled into migration 0004.

---

## 10. Gate ladder

1. exact branch/base/scope audit
2. syntax/import
3. targeted B4.3A tests
4. migration regression
5. full pytest
6. ownership/idempotency semantic audit
7. exact-SHA Simple CI
8. Freqtrade Validation
9. artifact audit
10. merge
11. exact post-merge gate
12. freeze B4.3A
13. freeze B4.3B contract before runtime implementation

---

## 11. Decision

```text
B4.3A DESIGN CONTRACT: READY FOR ARCHITECT AUDIT
B4.3A IMPLEMENTATION: NOT STARTED
B4.3B IMPLEMENTATION: NOT STARTED
B5: NOT STARTED
LIVE: FORBIDDEN
```
