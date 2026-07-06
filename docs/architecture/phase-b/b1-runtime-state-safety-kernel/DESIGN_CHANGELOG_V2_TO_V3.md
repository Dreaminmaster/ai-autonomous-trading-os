# B1 Design Changelog — V3 to V3.3 (B1.3 closeout)

**Date**: 2026-07-06
**Version**: V3 → V3.3

---

| # | Area | V3 | V3.3 | Reason |
|---|------|-----|------|--------|
| P0 | DispatchAttempt.PENDING_SUBMIT | Assumed "not sent" | Replaced: PRE_DISPATCH_PROVEN, DISPATCH_INITIATED. Cannot prove absence of side effect from PENDING state. | Crash window: network request may start between state write and crash. |
| P0 | CM8 | Crash after DISPATCH_COMMITTED → safe retry | Revised: DISPATCH_INITIATED → AMBIGUOUS. Query venue. No blind retry. Added CM8a for proven-safe retry. | |
| P1 | Network error retry | HTTP 5xx → retry max 3 | Replaced by 3 error classes: PRE-DISPATCH-PROVEN (safe retry), POST-DISPATCH-AMBIGUOUS (query first), VENUE-CONFIRMED-REJECT. No unconditional retry. | Venue may have accepted order before 5xx response. |
| P2 | RiskDecision FK | dangling FK (not persisted) | Added RiskDecision entity (1.15): risk_decision_id, decision, reasons, risk_score, checks_json. Immutable. | 14 persisted entities → 15. |
| P3 | RuntimeSession.status | missing PAUSED_RECOVERY_REQUIRED | Added to enum: STARTING / RECOVERING / READY / RUNNING / PAUSED / PAUSED_RECOVERY_REQUIRED / STOPPED | Recovery contract referenced state not in model. |
| P4 | AC1 | "14 tables" | "Every authoritative state has explicit storage mapping, constraints, keys, FK, precision, migration" | Table count is derived, not a requirement. |
