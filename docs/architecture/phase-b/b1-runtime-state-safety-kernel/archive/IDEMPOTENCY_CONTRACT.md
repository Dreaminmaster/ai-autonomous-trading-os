<!-- SUPERSEDED BY B1_DESIGN_BUNDLE_V3.md — DO NOT IMPLEMENT -->
# Idempotency Contract — Design Document

**Version**: 1.0  
**Date**: 2026-07-06  
**Status**: DESIGN ONLY

---

## Idempotency Key Structure

```
{session_id_first_8}_{symbol}_{action}_{timestamp_bucket}_{intent_hash_first_8}
```

### Components

| Component | Source | Example |
|-----------|--------|---------|
| session_id prefix | `RuntimeSession.session_id` | `a1b2c3d4` |
| symbol | `TradeIntent.symbol` | `BTC_USDT` |
| action | `TradeIntent.action` | `BUY` |
| timestamp bucket | `floor(decision_ts / 60)` (1-minute bucket) | `1719792300` |
| intent hash | `sha256(intent.to_json())[:8]` | `e5f6a7b8` |

### Full Key Example
```
a1b2c3d4_BTC_USDT_BUY_1719792300_e5f6a7b8
```

---

## Enforcement

### Database Constraint
```sql
CREATE TABLE execution_intents (
    ...
    idempotency_key TEXT NOT NULL UNIQUE,
    ...
);
```

### Runtime Logic
```python
def execute(intent, risk_decision, cycle, account):
    key = generate_idempotency_key(session_id, intent, risk_decision)
    existing = db.query("SELECT * FROM execution_intents WHERE idempotency_key = ?", key)
    if existing:
        log("ALREADY_PROCESSED", key=key)
        return ExecutionResult(status="ALREADY_PROCESSED", existing=existing)
    # ... proceed with execution
```

---

## Crash Scenarios

| Scenario | Behavior |
|----------|----------|
| Insert intent, crash before order sent | Startup: intent.status=PENDING → query exchange, cancel if not found |
| Order sent, crash before fill confirmation | Startup: query exchange for order status → update fill state |
| Fill confirmed, crash before reconciliation | Startup: reconcile fills → positions → ledger |
| Duplicate insert attempt (same key) | DB UNIQUE constraint rejects → log, return existing |
| Intent hash collision (same key, different intent) | Check `trade_intent_id` match → if mismatch, generate new key |

---

## Guarantees

1. **Exactly-once execution**: Same idempotency key → at most one execution.
2. **Crash-safe**: Key is persisted before execution is sent.
3. **Audit trail**: Every key maps to exactly one `ExecutionIntent`.
4. **No key reuse**: Session ID prefix ensures keys are unique across sessions.

---

## Boundary Conditions

| Condition | Handling |
|-----------|----------|
| Same candle, same intent, two cycles | Different cycle_ids → different timestamp buckets → different keys |
| Same candle, same intent, same cycle | DB UNIQUE constraint rejects duplicate INSERT |
| Intent changed (thesis/evidence/pr ice) | Different intent hash → different key |
| Intent unchanged but decision_ts changed | Different timestamp bucket → different key |
