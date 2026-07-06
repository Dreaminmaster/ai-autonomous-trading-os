<!-- SUPERSEDED BY B1_DESIGN_BUNDLE_V3.md — DO NOT IMPLEMENT -->
# Architecture Discovery Corrections

**From**: Phase A Architecture Discovery Report  
**Corrected**: 2026-07-06  
**HEAD**: `2f5054a`

---

## Correction 1: Provider Failure → HOLD — FAIL, not PASS

### Original Report
> Provider ERROR → HOLD = PASS

### Correction
ProviderManager has a **fallback chain**: if Provider A fails, the chain tries the next provider (ultimately MockProvider). MockProvider CAN generate BUY decisions.

**ProviderManager.decide() chain logic** (from `providers/base.py`):
- Try each provider in `self.chain`
- On failure: fall through to next provider
- Last resort: MockProvider (always returns valid result)
- MockProvider can return BUY with confidence ≥ 0.60

### Status
**FAIL / POLICY CONFLICT** — If the safety invariant is "provider timeout/error → HOLD", the current fallback chain violates it.

### Evidence
- `providers/base.py`: ProviderManager.decide() iterates chain without HOLD-on-failure policy
- No `provider_error_fallthrough = HOLD` gate in risk.py Gate 10

---

## Correction 2: Exposure Limits — PARTIAL, not IMPLEMENTED

### Original Report
> Exposure limits = IMPLEMENTED

### Correction
Risk Gate 6 only validates `max_position_pct_per_trade` for a single position. No check for:
- **Total portfolio exposure** (sum of all active positions)
- **Active position count** (max concurrent positions)
- **Pending order notional** (intent before execution)

### Status
**PARTIAL** — Gate 6 does single-position-size check only.

### Evidence
- `risk.py` line 131: `max_pos = float(self.policy.get("position_limits", {}).get("max_position_pct_per_trade", 10.0))`
- No `max_total_exposure_pct` enforcement in evaluate()
- No `max_active_positions` check

---

## Correction 3: Runtime Not Bound to Real Account State

### Discovery
In `runtime.py:run_once()`:
- `risk_state = {}` — empty dictionary, no market/account context
- `equity_usdt = 1000.0` — hardcoded constant

### Status
**CRITICAL GAP** — Autonomous runtime does not read real account equity, positions, or market data.

---

## Correction 4: Live Gate — PARTIAL, not ABSENT

### Original Report
> Live gate = ABSENT

### Correction
Multiple safety gates form a partial live-lock:
- `RiskEngine`: mode guard (`paper`/`guarded`)
- `GuardedExchangeExecutor(enabled=False)`: raises PermissionError
- `config.dryrun.json`: `dry_run=true`
- Policy mode: defaults to `"paper"`

But there is **no unified live-enable contract**. The gates are scattered across modules with no single audit point.

### Status
**PARTIAL** — Gates exist but are not composable into a single live-enable decision.

### Evidence
- `execution.py`: `GuardedExchangeExecutor(enabled=False)` — hardcoded False
- `risk.py`: mode guard checks `state["mode"]` vs policy
- No `LIVE_ENABLE_REQUIRED` manifest

---

## Correction 5: Position Persistence — Schema exists, path absent

### Original Report
> Position persistence = memory only

### Correction
- `db_store.py` has a `snapshots` table (for positions)
- But no PositionState class that writes to it
- PaperExecutor returns `ExecutionResult` with no database write
- No recovery path reads snapshots back

### Status
**Schema exists, operational path absent**

---

## Correction 6: Kill Switch — Latched, not Auto-Reset

### Original Report
> E9: Kill Switch Auto-Reset

### Correction
Kill switch must be **latched**: once triggered, requires explicit manual reset. Auto-reset would defeat the purpose.

### Status
**Remove E9 from epic list.** Replace with: "Latched Kill Switch with Manual Reset Protocol."

### Evidence
- `risk.py` Gate 1: `Path("runtime/kill_switch.flag").exists()` — flag file, manual creation needed
- No auto-reset code path exists

---

## Summary of Corrections

| # | Item | Old | Corrected |
|---|------|-----|-----------|
| 1 | Provider failure safety | PASS | **FAIL — fallback chain violates HOLD-on-error** |
| 2 | Exposure limits | IMPLEMENTED | **PARTIAL — single-position only** |
| 3 | Runtime binding | SKELETON | **CRITICAL GAP — hardcoded equity=1000** |
| 4 | Live gate | ABSENT | **PARTIAL — scattered gates, no unified contract** |
| 5 | Position persistence | memory only | **Schema exists, no operational path** |
| 6 | Kill switch behavior | Auto-Reset | **Latched — manual reset required** |
