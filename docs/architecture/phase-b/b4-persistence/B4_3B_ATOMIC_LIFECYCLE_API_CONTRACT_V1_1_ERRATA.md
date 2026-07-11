# B4.3B Atomic Lifecycle API Contract V1.1 — Semantic Errata

**Applies to**: `B4_3B_ATOMIC_LIFECYCLE_API_CONTRACT_V1.md`  
**Baseline design commit**: `9bc963b5c2f513476d01954f2b6b7eceb5d8b571`  
**Precedence**: this errata overrides conflicting V1 text  
**LIVE**: FORBIDDEN

---

## 1. Reason

Architect self-review found four details that require exact semantics before implementation:

1. a fill fee may be denominated in a non-quote currency, so it cannot be subtracted from position realized PnL without an authoritative conversion rate;
2. `order_status_after` and local `recorded_at` are application metadata, not immutable fill identity;
3. deterministic IDs need exact canonical component definitions, not only a hash-prefix rule;
4. SQLite concurrent-writer tests need two persistent connections to the same file, not unsafe cross-thread sharing of one connection.

---

## 2. Fill replay identity

For replay/conflict comparison, the immutable authoritative fill payload is exactly:

```text
venue
account_scope
fill_id
order_id
symbol
quantity
price
fee
fee_currency
occurred_at
```

The following command fields are not part of immutable fill identity:

```text
recorded_at
order_status_after
```

Reason:

- `recorded_at` is local processing metadata and can differ on a later exact replay;
- `order_status_after` may already have advanced through a later fill and must never be moved backwards.

If the persisted fill payload and complete deterministic accounting sequence already exist, a replay returns `REPLAY_NOOP` regardless of a later `recorded_at` value or a stale `order_status_after` request.

A replay must not update order, event, or position timestamps.

---

## 3. Accounting-event timestamp

For every new accounting event:

```text
timestamp = FillApplicationCommand.occurred_at
```

Position lifecycle timestamps remain:

```text
opened_at = occurred_at
closed_at = occurred_at when closed
updated_at = recorded_at
```

---

## 4. Fee and realized PnL semantics

The V1 statement that event and position realized PnL are net of fee is superseded.

A fee can be denominated in:

- quote currency;
- base currency;
- exchange token;
- another venue-supported currency.

B4.3B has no authoritative FX conversion input. Therefore:

```text
position_accounting_details.fee
    = authoritative fill fee in fill_states.fee_currency

position_accounting_details.realized_pnl
    = gross realized PnL in the symbol quote-PnL convention

position_states.realized_pnl
    = cumulative gross realized PnL
```

Fees and realized PnL are intentionally separate. No subtraction or currency conversion is performed in B4.3B.

A later versioned accounting/reporting layer may compute net PnL only when it has an authoritative conversion rate and timestamp.

### Deterministic fee attribution remains

Across one fill sequence:

```text
event 1 fee = full authoritative fill fee
event 2 fee = 0
```

The sum of event fees must equal the fill fee exactly.

For OPEN/INCREASE events with no closing quantity:

```text
realized_pnl = 0
```

For REDUCE/CLOSE events:

```text
realized_pnl = gross closing PnL
```

---

## 5. Exact deterministic ID inputs

All components are UTF-8 encoded using a length-delimited canonical form:

```text
<decimal byte length>:<raw component bytes>
```

Components are concatenated in the listed order. No separator-only encoding, Python tuple repr, JSON, locale formatting, or Python `hash()` is allowed.

### Accounting event ID

```text
prefix: pae_
SHA-256 components:
1. "B4.3B:PAE:V1"
2. source_fill_venue
3. source_fill_account_scope
4. source_fill_id
5. decimal source_fill_event_no
```

Result:

```text
pae_<64 lowercase hex>
```

### Newly opened position ID

```text
prefix: pos_
SHA-256 components:
1. "B4.3B:POSITION:NETTING_V1"
2. venue
3. account_scope
4. symbol
5. target side (LONG / SHORT)
6. source_fill_id
7. decimal source_fill_event_no
```

Result:

```text
pos_<64 lowercase hex>
```

`source_fill_event_no` is the event that opens the new position.

Increasing an existing same-side position preserves its existing `position_id`.

---

## 6. Weighted-average arithmetic

The explicit local context remains:

```text
precision = 34
rounding = ROUND_HALF_EVEN
```

Canonical persistence formatting occurs after arithmetic. No currency-precision quantization is invented by B4.3B.

This preserves deterministic high-precision state while leaving venue-specific display or settlement quantization to a versioned boundary with authoritative instrument metadata.

---

## 7. Concurrent writer test topology

One `SqliteLifecyclePersistence` instance owns one injected persistent `RuntimeDatabase` connection.

A connection is never shared across threads.

Concurrency tests use:

```text
adapter A -> RuntimeDatabase connection A
adapter B -> RuntimeDatabase connection B
both connections -> same temporary SQLite file
```

Both connections retain:

```text
foreign_keys = ON
journal_mode = WAL
synchronous = FULL
busy_timeout = 5000
```

Expected outcomes:

### Exact duplicate

```text
one APPLIED
one REPLAY_NOOP
```

### Conflicting duplicate

```text
one APPLIED
one LifecycleConflictError
```

No connection is opened per operation and no connection object is used from a different thread than the one that created it.

---

## 8. Additional required tests

B4.3B1 must additionally prove:

1. opening/increasing does not subtract fee from realized PnL;
2. reducing/closing stores gross realized PnL separately from fee;
3. event-fee sum equals authoritative fill fee;
4. deterministic IDs match fixed known vectors;
5. length-delimited encoding distinguishes ambiguous component sequences;
6. event timestamp equals `occurred_at`.

B4.3B2 must additionally prove:

1. replay with a different `recorded_at` is `REPLAY_NOOP`;
2. replay with a stale `order_status_after` is `REPLAY_NOOP` and does not regress order state;
3. immutable fill payload mismatch still raises `LifecycleConflictError`;
4. two-connection concurrent tests follow Section 7 exactly.

---

## 9. Decision

```text
B4.3B BASE CONTRACT: V1
SEMANTIC OVERRIDE: V1.1 ERRATA
B4.3B1 IMPLEMENTATION: NOT STARTED
B4.3B2 IMPLEMENTATION: NOT STARTED
B4.3B3 IMPLEMENTATION: NOT STARTED
B5: NOT STARTED
LIVE: FORBIDDEN
```
