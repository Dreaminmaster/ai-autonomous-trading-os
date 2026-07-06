# Execution Transaction Contract V2

**Version**: V2
**B1 design baseline**: V3.3
**Last synced commit**: de5bbe8
**Semantics synced to B1 V3.3**
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
Steps 1-4 happen entirely within DB transactions. Step 5 happens AFTER commit. Steps 6-7 are new transactions.

---

## DispatchAttempt Lifecycle (V3.3)

```
PRE_DISPATCH_PROVEN   (step 4 — local proof: no bytes sent)
  ↓
DISPATCH_INITIATED    (bytes MAY have been sent. Ambiguity begins.)
  ↓
SUBMITTED             (venue acknowledged receipt — response received)
  ↓
ACCEPTED              (venue confirmed order open)
  ↓
REJECTED              (venue rejected order)
  ↓
TIMEOUT               (no response within deadline)
  ↓
AMBIGUOUS             (unable to determine venue state conclusively)
```

### Core Rules

1. **PRE_DISPATCH_PROVEN**: Only with explicit local proof that request bytes were definitely never sent (e.g. serialization failed, connection refused before send). Safe for direct retry.

2. **DISPATCH_INITIATED**: Network side effect may have occurred. Crash recovery must query venue by stable client_order_id. If conclusively found → reconcile. If unable to prove absence → AMBIGUOUS. PAUSED_RECOVERY_REQUIRED. No blind redispatch.

3. **Deleted**: Old Phase B "not found → TIMEOUT → create new attempt". Only PRE_DISPATCH_PROVEN allows direct retry.

---

## Crash at Each Phase (V3.3)

### Phase A: After PREPARED commit, before DISPATCH commit
```
DB: ExecutionIntent + ExecutionState=PREPARED
Venue: Nothing
Recovery: Intent present. Clear to proceed. Start new DispatchAttempt.
```

### Phase B: PRE_DISPATCH_PROVEN (local proof no bytes sent)
```
DB: DispatchAttempt(status=PRE_DISPATCH_PROVEN)
Venue: Nothing (proven)
Recovery: Safe to retry. Create new DispatchAttempt. No query needed.
```

### Phase C: DISPATCH_INITIATED (bytes may have been sent)
```
DB: DispatchAttempt(status=DISPATCH_INITIATED)
Venue: May have accepted. May not.
Recovery: Query venue by client_order_id.
    If found → reconcile. Mark Attempt=SUBMITTED/ACCEPTED.
    If NOT found after venue consistency window → AMBIGUOUS.
    PAUSED_RECOVERY_REQUIRED. No blind redispatch.
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

## Retry Rules (V3.3)

| Condition | Action |
|-----------|--------|
| Same execution_intent_id, new DispatchAttempt, PRE_DISPATCH_PROVEN state | OK — retry with new attempt_id |
| Same execution_intent_id, previous attempt DISPATCH_INITIATED or AMBIGUOUS | PAUSE — must query venue first |
| Same execution_intent_id, previous attempt ACCEPTED | Do not retry. Reconcile existing order. |
| Same execution_intent_id, previous attempt REJECTED | Retry OK if reject reason is transient; requires explicit policy decision |
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
