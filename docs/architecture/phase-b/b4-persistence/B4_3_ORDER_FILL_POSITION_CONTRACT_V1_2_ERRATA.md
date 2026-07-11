# B4.3 Order / Fill / Position Contract V1.2 — Authority Consistency Errata

**Applies to**: `B4_3_ORDER_FILL_POSITION_CONTRACT_V1.md` V1.1  
**Baseline main**: `119cf159c2c92b34d057f29858c008affaa0ad0a`  
**Status**: REQUIRED OVERRIDE before B4.3A implementation  
**LIVE**: FORBIDDEN

---

## 1. Reason for this errata

The first B4.3A implementation candidate passed its automated tests, but exact architect review found three authority gaps that the V1.1 schema contract did not prevent:

1. an `order_states` row could store a `client_order_id` different from the referenced `DispatchAttempt`;
2. a position-accounting event could attach an account-A fill to an account-B position;
3. a position-accounting event could attach a BTC fill to an ETH position.

Those states would remain syntactically valid while corrupting recovery and reconciliation authority. V1.2 therefore strengthens database-level semantic ownership before implementation resumes.

Closed rejected implementation candidate:

```text
PR #7
head 2e08add58e51b74ed8ca9afce27414c9be8bf66a
NOT MERGED
```

---

## 2. Precedence

Where this document conflicts with V1.1, this V1.2 errata wins.

All unaffected V1.1 rules remain active, including:

- B4.3A schema-only scope;
- B4.3B runtime API and performance work deferred;
- modular-monolith constraints;
- old migration checksum preservation;
- deterministic fill-event numbering;
- LIVE FORBIDDEN.

---

## 3. Exact dispatch ownership must include client_order_id

### Parent backing identity

Migration 0004 must add a UNIQUE index on `dispatch_attempts` over:

```text
(execution_intent_id,
 attempt_id,
 venue,
 account_scope,
 client_order_id)
```

### Order FK

`order_states` must use the exact composite FK:

```text
(execution_intent_id,
 attempt_id,
 venue,
 account_scope,
 client_order_id)

REFERENCES dispatch_attempts(
 execution_intent_id,
 attempt_id,
 venue,
 account_scope,
 client_order_id)
```

This guarantees that an acknowledged venue order cannot be attached to the right attempt while silently carrying the wrong stable client order identifier.

The V1.1 four-column dispatch ownership tuple is superseded.

---

## 4. Order symbol and side must match ExecutionIntent

Migration 0004 must add a UNIQUE parent backing index on `execution_intents`:

```text
(execution_intent_id, symbol, action)
```

`order_states` must add a second composite FK:

```text
(execution_intent_id, symbol, side)

REFERENCES execution_intents(
 execution_intent_id,
 symbol,
 action)
```

`order_states.side` uses `BUY/SELL`, matching `execution_intents.action`.

This prevents the persistence layer from recording an ETH or SELL order against a BTC BUY execution intent.

---

## 5. Fill symbol must be authoritative

`fill_states` adds:

```text
symbol TEXT NOT NULL
```

Migration 0004 must add a UNIQUE backing index on `order_states`:

```text
(venue, account_scope, order_id, symbol)
```

The fill-to-order FK becomes:

```text
(venue, account_scope, order_id, symbol)

REFERENCES order_states(
 venue, account_scope, order_id, symbol)
```

A UNIQUE backing index must also exist on `fill_states` over:

```text
(venue, account_scope, fill_id, symbol)
```

The authoritative fill primary key remains:

```text
(venue, account_scope, fill_id)
```

The additional symbol-bearing key exists to prove downstream semantic ownership, not to redefine fill identity.

---

## 6. Accounting must bind fill and position to the same account and symbol

`position_accounting_details` adds:

```text
source_fill_symbol TEXT NOT NULL
```

Migration 0004 must add a UNIQUE parent backing index on `position_states`:

```text
(position_id, venue, account_scope, symbol)
```

### Exact source-fill FK

```text
(source_fill_venue,
 source_fill_account_scope,
 source_fill_id,
 source_fill_symbol)

REFERENCES fill_states(
 venue,
 account_scope,
 fill_id,
 symbol)
```

### Exact target-position FK

```text
(position_id,
 source_fill_venue,
 source_fill_account_scope,
 source_fill_symbol)

REFERENCES position_states(
 position_id,
 venue,
 account_scope,
 symbol)
```

Together, these constraints guarantee:

```text
fill venue/account/symbol
==
position venue/account/symbol
```

The position side is intentionally not equated to order side. A BUY fill may reduce a SHORT position, close it, cross zero, and then open a LONG position. That mapping belongs to deterministic accounting logic in B4.3B.

---

## 7. Deterministic event identity remains unchanged

The replay identity remains:

```text
(source_fill_venue,
 source_fill_account_scope,
 source_fill_id,
 source_fill_event_no)
```

`source_fill_symbol` is constrained by FK but is not needed to redefine event identity because the scoped fill ID is already authoritative.

Valid zero-crossing sequence remains:

```text
same fill, event_no=1 -> CLOSE
same fill, event_no=2 -> OPEN
```

A duplicate of either event number must be rejected.

---

## 8. Required additional B4.3A tests

The replacement implementation candidate must prove all V1.1 tests plus:

1. order `client_order_id` mismatch against its dispatch attempt is rejected;
2. order symbol mismatch against its execution intent is rejected;
3. order side mismatch against its execution intent action is rejected;
4. fill symbol mismatch against its venue-scoped order is rejected;
5. accounting event using a fill from another account scope is rejected;
6. accounting event using a fill for another symbol is rejected;
7. exact FK grouping and sequence for every new five-/four-column FK;
8. exact UNIQUE backing columns for all new parent keys.

No runtime Python validator may substitute for these database constraints.

---

## 9. Replacement implementation rule

The rejected candidate branch must not be merged or incrementally patched into approval.

After this errata is merged, create a clean B4.3A implementation branch from the new exact `main` SHA. Authorized implementation surface remains:

1. `implementation/src/atos/runtime_migrations.py`
2. `implementation/tests/test_order_fill_position_persistence_schema.py`
3. one-line future-safe legacy-prefix correction in `implementation/tests/test_execution_persistence_schema.py`

No repository/service implementation, B4.3B benchmark, B5 code, or LIVE code is authorized.

---

## 10. Decision

```text
B4.3 CONTRACT BASE: V1.1
AUTHORITY OVERRIDE: V1.2 ERRATA
PR #7: REJECTED / CLOSED / NOT MERGED
B4.3A REPLACEMENT IMPLEMENTATION: NOT STARTED
B4.3B: NOT STARTED
B5: NOT STARTED
LIVE: FORBIDDEN
```
