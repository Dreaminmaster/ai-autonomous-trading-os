# B4.3B Atomic Lifecycle API Contract V1.2 — Final Precision Errata

**Applies to**: B4.3B V1 plus V1.1 semantic errata  
**Precedence**: V1.2 overrides conflicts in earlier B4.3B documents  
**LIVE**: FORBIDDEN

---

## 1. Exact order-acknowledgement writes

A new successful order acknowledgement performs exactly these three authoritative mutations.

### Mutation 1 — dispatch attempt

The exact row selected by the full ownership tuple is updated only when current status is `SUBMITTED`:

```text
status = ACCEPTED
response_received_at = acknowledged_at
```

The following columns remain unchanged:

```text
attempt_id
execution_intent_id
client_order_id
venue
account_scope
attempt_no
created_at
dispatch_started_at
error_class
```

### Mutation 2 — order state

The inserted order row uses:

```text
status = OPEN
created_at = acknowledged_at
updated_at = acknowledged_at
```

All other values come from the normalized typed command.

### Mutation 3 — execution state

The exact execution state is updated only when:

```text
status = DISPATCHED
last_attempt_id = command.attempt_id
```

The update is exactly:

```text
status = ACKNOWLEDGED
state_started_at = acknowledged_at
updated_at = acknowledged_at
```

The following columns remain unchanged:

```text
execution_intent_id
last_attempt_id
retry_count
```

Any row-count mismatch rolls back all three mutations.

---

## 2. Exact fill-side order update

A new fill application changes only:

```text
order_states.status = order_status_after
order_states.updated_at = recorded_at
```

Every immutable order field and `created_at` remains unchanged.

Exact replay never rewrites order status or timestamps.

---

## 3. Operation statistics and exception metadata

`OperationStats` is an immutable slots dataclass containing:

```text
read_statements: int
attempted_mutations: int
committed_mutations: int
transaction_count: int
db_connection_identity: int
```

Successful result objects contain `stats: OperationStats`.

Every `LifecyclePersistenceError` instance also contains `stats: OperationStats`.

Rules:

- `transaction_count` becomes `1` when the public operation enters its adapter-owned transaction;
- `attempted_mutations` increments immediately before each adapter-owned INSERT/UPDATE/DELETE;
- before commit, `committed_mutations` remains `0`;
- after successful commit, `committed_mutations = attempted_mutations`;
- any raised error after rollback exposes `committed_mutations = 0`;
- validation errors raised before transaction entry expose `transaction_count = 0`;
- connection identity is `id(db.connection)` captured once at operation entry and must remain stable.

SQLite trigger internals are not counted as separate adapter-owned mutations.

---

## 4. Identity string validation

Identity and scope strings are rejected when:

```text
value == ""
or
value consists only of Unicode whitespace
```

Accepted strings are preserved byte-for-byte. Persistence code does not trim, normalize case, apply Unicode normalization, or rewrite separators.

---

## 5. Linear accounting scope

`NettingPositionAccountingV1` is explicitly a **linear price-times-quantity accounting policy**.

Its gross PnL formulas are valid only when:

```text
PnL = quantity * price difference
```

This includes the current spot/linear validation path.

It must not be used for:

- inverse contracts;
- quanto contracts;
- instruments requiring contract multipliers not already represented in quantity;
- instruments requiring settlement-currency conversion.

Those models require a separately versioned injected policy with authoritative instrument metadata. B4.3B V1 does not guess contract value or multiplier.

`realized_pnl` therefore represents gross linear PnL in the arithmetic convention of the normalized quantity and price fields. It is not labeled as net PnL and is not combined with fees.

---

## 6. Position mutation exactness

For an existing position changed by INCREASE, REDUCE, or CLOSE, only these columns may change:

```text
quantity
avg_entry_price
realized_pnl
unrealized_pnl
status
closed_at
updated_at
```

Identity/scope, side, and `opened_at` remain unchanged.

Rules by event:

### INCREASE

```text
quantity = old + added
avg_entry_price = weighted average
realized_pnl = old realized_pnl
unrealized_pnl = 0
status = OPEN
closed_at = NULL
```

### REDUCE

```text
quantity = old - reduced
avg_entry_price = old avg_entry_price
realized_pnl = old realized_pnl + gross event realized_pnl
unrealized_pnl = 0
status = OPEN
closed_at = NULL
```

### CLOSE

```text
quantity = 0
avg_entry_price = old avg_entry_price
realized_pnl = old realized_pnl + gross event realized_pnl
unrealized_pnl = 0
status = CLOSED
closed_at = occurred_at
```

### OPEN new position

```text
quantity = opened quantity
avg_entry_price = fill price
realized_pnl = 0
unrealized_pnl = 0
status = OPEN
opened_at = occurred_at
closed_at = NULL
updated_at = recorded_at
```

Fees remain exclusively in accounting-event fee fields and the source fill record.

---

## 7. Final document order

For B4.3B implementation, the authoritative order is:

```text
1. B4_3B_ATOMIC_LIFECYCLE_API_CONTRACT_V1.md
2. B4_3B_ATOMIC_LIFECYCLE_API_CONTRACT_V1_1_ERRATA.md
3. B4_3B_ATOMIC_LIFECYCLE_API_CONTRACT_V1_2_ERRATA.md
```

Later documents override earlier conflicts.

---

## 8. Decision

```text
B4.3B CONTRACT: V1 + V1.1 + V1.2
B4.3B CONTRACT STATUS: READY FOR FINAL DESIGN GATE
B4.3B1 IMPLEMENTATION: NOT STARTED
B4.3B2 IMPLEMENTATION: NOT STARTED
B4.3B3 IMPLEMENTATION: NOT STARTED
B5: NOT STARTED
LIVE: FORBIDDEN
```
