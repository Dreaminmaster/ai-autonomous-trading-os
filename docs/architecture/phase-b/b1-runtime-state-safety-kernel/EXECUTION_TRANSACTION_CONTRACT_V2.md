# Execution Transaction Contract V2

**Version**: V2  
**Date**: 2026-07-06  
**Status**: DESIGN ONLY

---

## Transaction Boundary

Every logical execution is a transaction:

```
1. TradeIntent (immutable, already created by AI + Risk)
   ↓
2. Create ExecutionIntent (new UUID, persisted)
   ↓
3. Create ExecutionState=PREPARED (persisted, COMMITTED)
   ↓
4. Create DispatchAttempt (persisted, COMMITTED) ← boundary
   ↓
5. Network call to venue ← outside DB transaction
   ↓
6. Response received → update ExecutionState + OrderState
   ↓
7. Reconcile fills → Positions
```

### Key Rule
Steps 1-4 happen entirely within DB transactions. Step 5 happens AFTER commit. Step 6-7 are new transactions.

---

## DispatchAttempt Lifecycle

```
PENDING_SUBMIT   (step 4 — committed, not yet sent)
  ↓
SUBMITTED        (step 5 — sent, but response pending)
  ↓
ACCEPTED         (venue confirmed order)
  ↓
REJECTED         (venue rejected order)
  ↓
TIMEOUT          (no response within deadline)
  ↓
AMBIGUOUS        (unable to determine venue state)
```

---

## Crash at Each Phase

### Phase A: After PREPARED commit, before DISPATCH commit
```
DB: ExecutionIntent + ExecutionState=PREPARED
Venue: Nothing
Recovery: Intent present. Clear to proceed. Start new DispatchAttempt.
```

### Phase B: After DISPATCH commit, before network call
```
DB: DispatchAttempt + ExecutionState=DISPATCH_COMMITTED
Venue: Nothing
Recovery: Attempt found, status=PENDING_SUBMIT. Query venue → not found.
          Mark Attempt=TIMEOUT. Create new attempt or abandon.
```

### Phase C: During network call (no response)
```
DB: DispatchAttempt status=SUBMITTED
Venue: May have accepted. May not.
Recovery: Query venue by client_order_id.
          If found → update OrderState + reconcile.
          If NOT found → mark AMBIGUOUS. PAUSE. No redispatch.
```

### Phase D: Venue accepted, response lost
```
DB: DispatchAttempt status=SUBMITTED (no response yet in our DB)
Venue: Order exists, possibly partially filled
Recovery: Query venue by client_order_id. Found.
          Update OrderState + reconcile fills → Positions.
          Mark DispatchAttempt=ACCEPTED.
```

### Phase E: Response received, before ACK persisted
```
Recovery: Order found via query. Reconcile fills.
          If response was seen in logs but not committed,
          replay the same fill reconciliation.
```

---

## Retry Rules

| Condition | Action |
|-----------|--------|
| Same execution_intent_id, new DispatchAttempt | OK — retry with new attempt_id |
| Same execution_intent_id, previous attempt AMBIGUOUS | PAUSE — must query venue first |
| Same execution_intent_id, previous attempt ACCEPTED | Do not retry. Reconcile existing order. |
| Same execution_intent_id, previous attempt REJECTED | Retry OK if reject reason is transient (e.g. rate limit) |
| Different execution_intent_id, same symbol/side | New execution. Not related to previous. |

---

## Network Error Classification (V3.3)

| Class | Examples | Action |
|-------|----------|--------|
| **PRE-DISPATCH-PROVEN** | serialization failed, local validation failed, connection refused BEFORE request bytes sent (adapter must prove) | Retry allowed |
| **POST-DISPATCH-AMBIGUOUS** | timeout, connection reset after send, unknown response, HTTP 5xx where side effect cannot be excluded | AMBIGUOUS. Query client_order_id. No blind retry. |
| **VENUE-CONFIRMED-REJECT** | HTTP 4xx (not 429), venue says "invalid order" | REJECTED. Retry only by explicit policy decision. |

**Deleted**: unconditional `HTTP 5xx → retry max 3`. Every retry requires explicit evidence.

---

## Guarantees

1. **No blind dispatch**: Unknown venue state → PAUSE. Query first.
2. **No duplicate registration**: execution_intent_id UNIQUE constraint.
3. **At-most-one logical execution per intent**: dispatch only when ExecutionState = PREPARED.
4. **Immutable audit**: All DispatchAttempts preserved for post-mortem.
5. **Idempotent client_order_id**: Same client_order_id across retries enables venue dedup.
