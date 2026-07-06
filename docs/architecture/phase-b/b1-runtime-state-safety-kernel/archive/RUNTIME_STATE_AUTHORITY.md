<!-- SUPERSEDED BY B1_DESIGN_BUNDLE_V3.md — DO NOT IMPLEMENT -->
# Runtime State Authority — Design Document

**Version**: 1.0  
**Date**: 2026-07-06  
**Status**: DESIGN ONLY

---

## Authoritative Source Rules

Each state entity has exactly ONE authoritative source. No module may maintain its own divergent copy.

| Entity | Authoritative Source | Storage | Read By |
|--------|---------------------|---------|---------|
| RuntimeSession | `state_service.py` | SQLite `sessions` table | All modules |
| RuntimeCycle | `state_service.py` | SQLite `cycles` table | `runtime.py`, `risk.py`, `execution.py` |
| MarketSnapshot | `market.py` | SQLite `market_snapshots` table + memory cache (TTL) | `features.py`, `strategies.py`, Provider |
| AccountSnapshot | `okx_readonly_account.py` | SQLite `account_snapshots` table | `risk.py`, `execution.py` |
| ExecutionIntent | `runtime.py` (create) → immutable | SQLite `execution_intents` table | `execution.py`, `ledger.py` |
| OrderState | `execution.py` | SQLite `orders` table | `reconciliation.py` |
| FillState | `execution.py` | SQLite `fills` table | `reconciliation.py`, `scoring.py` |
| PositionState | `execution.py` | SQLite `positions` table | `reconciliation.py`, `scoring.py` |
| RiskRuntimeState | `risk.py` | SQLite `risk_state` table | `runtime.py` (on startup) |
| RecoveryState | `state_service.py` | SQLite `recoveries` table | `runtime.py` (on startup) |
| Ledger Events | `ledger.py` | SQLite `events` table (append-only) | `reporting.py`, `dashboard.py` |

---

## Prohibited Patterns

1. **Dual source**: Two modules each maintaining their own position state (e.g., `execution.py` vs `risk.py`).
2. **Memory-only divergence**: Writing to DB but reading from memory without sync.
3. **Silent fallback**: Using default values when authoritative source is unavailable (e.g., `equity_usdt=1000.0`).
4. **Cross-module mutation**: Module A directly modifying Module B's state without going through Module B's API.
5. **Unlogged state transition**: Changing an entity's status without writing a ledger event.

---

## Read/Write Access Matrix

| Module | Session | Cycle | Market | Account | Intent | Order | Position | Risk | Recovery |
|--------|---------|-------|--------|---------|--------|-------|----------|------|----------|
| `runtime.py` | RW | RW | R | R | W | — | — | R (init) | R (init) |
| `market.py` | — | — | RW | — | — | — | — | — | — |
| `okx_readonly_account.py` | — | — | — | RW | — | — | — | — | — |
| `risk.py` | — | R | — | R | R | — | — | RW | — |
| `execution.py` | — | R | — | R | R | RW | RW | — | — |
| `reconciliation.py` | — | R | — | R | R | R | R | R | — |
| `ledger.py` | Append | Append | Append | Append | Append | Append | Append | Append | Append |
| `state_service.py` | RW | RW | — | — | — | — | — | R | RW |

### Key
- **RW**: Read + Write (authoritative source)
- **R**: Read only
- **W**: Write only (idempotent)
- **—**: No access
- **Append**: Append-only (immutable log)
