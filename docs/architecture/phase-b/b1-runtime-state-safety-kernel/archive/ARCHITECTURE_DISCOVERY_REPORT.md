<!-- SUPERSEDED BY B1_DESIGN_BUNDLE_V3.md — DO NOT IMPLEMENT -->
# Architecture Discovery Report

**HEAD**: `2f5054a9b1774a06b89fa7eafd456c6755551a32`  
**Branch**: main  
**Working tree**: clean  
**Evidence SHA**: `7191b6b` (heavy path), `2f5054a` (contract path)  
**Date**: 2026-07-06

---

## 1. Executive Summary

4,218 lines of Python across 31 source modules + 828-line Freqtrade strategy wrapper + ~20 scripts. 183 tests with 7 skipped. Two CI workflows: Simple (dev-only) and Freqtrade Validation (full backtest matrix).

**Core finding: This is a research framework with deep backtest rigor, not an autonomous trading OS.** The entire system has been battle-tested through a stabilization phase — Canonical baseline (244t / -16.12%) is confirmed, lookahead bias detection is zero, structured evidence chain is proven. But the 24/7 autonomous runtime layer is **absent or skeleton-only**.

---

## 2. Current System Classification

**Hybrid — primarily a research / backtest framework with skeleton runtime aspirations.**

| Layer | Classification |
|-------|---------------|
| Research/Backtest pipeline | **IMPLEMENTED** — Freqtrade integration, canonical runner, Round1 matrix, LA analysis |
| Provider pipeline | **PARTIAL** — Mock + OpenAI + DeepSeek + Compatible, tested |
| Risk engine | **IMPLEMENTED** — 10 hard gates, deterministic |
| Execution | **SKELETON** — PaperExecutor + ShadowExecutor exist but no reconciliation |
| Runtime daemon | **SKELETON** — AutonomousRuntime.run_loop exists but no scheduler, heartbeat, crash recovery |
| Persistence | **PARTIAL** — SQLite ledger/db store, but no resume from crash |
| Deployment | **ABSENT** — No Docker, systemd, launchd |

---

## 3. Repository Capability Inventory

### 3.1 Module Inventory

```
implementation/src/atos/
├── __init__.py
├── account_file.py
├── account_view.py
├── cli.py
├── cli_ext.py
├── core.py
├── dashboard.py
├── data_freshness.py
├── db_migrations.py
├── db_store.py
├── domain.py
├── evaluator.py
├── execution.py
├── features.py
├── history.py
├── ledger.py
├── lookahead_contract.py
├── lookahead_decision.py
├── lookahead_parser.py
├── market.py
├── market_regime.py
├── models/
│   ├── __init__.py
│   └── trade_intent.py
├── okx_cache.py
├── okx_readonly_account.py
├── operator_commands.py
├── providers/
│   ├── __init__.py
│   ├── base.py
│   ├── deepseek_provider.py
│   ├── mock_provider.py
│   ├── openai_compatible_provider.py
│   └── openai_provider.py
├── providers.py (DUPLICATED — legacy)
├── reporting.py
├── research_loop.py
├── risk.py
├── runtime.py
├── scoring.py
├── state_service.py
├── strategies.py
├── strategy_registry.py
├── time_context.py
└── timer.py

implementation/scripts/
├── ci_baseline_comparison.py
├── ci_baselines.py
├── ci_multi_period.py
├── ci_multipair_attribution.py
├── ci_strategy_fix_round1.py
├── ci_walk_forward.py
├── download_data.sh
├── run_all.sh
├── run_backtest.sh
├── run_baseline_comparison.sh
├── run_canonical_backtest.py
├── run_dashboard.sh
├── run_dryrun.sh
├── run_lookahead_analysis.sh
├── run_research_report.sh
├── run_tests.sh
├── run_walk_forward.sh
├── setup_freqtrade.sh
└── validate_no_secrets.sh

implementation/config/
├── policy.json
├── policy.validation.json
└── policy.experiment_round1.json

implementation/tests/ (21 test files, 183 tests)
```

### 3.2 Capability Status Table

| Capability | Status | Evidence |
|------------|--------|----------|
| Market data (OKX) | IMPLEMENTED | `market.py`, `okx_cache.py`, `data_freshness.py` |
| Regime detection | IMPLEMENTED | `market_regime.py` |
| Feature generation | IMPLEMENTED | `features.py` |
| Strategy generation | IMPLEMENTED | `strategies.py`, `strategy_registry.py` (9 strategies) |
| Candidate ranking | PARTIAL | Mock provider ranks by confidence |
| Strategy weighting | PARTIAL | Experiment support via `_exp_strategy_weights` |
| Disabled strategies | PARTIAL | Via `_exp_disabled_strategies`, not live-bound |
| No-substitution | IMPLEMENTED | `_exp_no_substitution` branch in populate_entry_trend |
| AI Provider Manager | IMPLEMENTED | `providers/base.py` — Mock, OpenAI, DeepSeek, Compatible |
| Provider fallback | IMPLEMENTED | Chain: [primary, mock] |
| Provider schema validation | IMPLEMENTED | Pydantic + JSON Schema dual validation |
| TradeIntent | IMPLEMENTED | `models/trade_intent.py` |
| Risk Supervisor | IMPLEMENTED | `risk.py` — 10 deterministic gates |
| Cooldown | IMPLEMENTED | Gate 8, decision_ts based |
| Daily loss control | IMPLEMENTED | Gate 7, decision_day based |
| Exposure limits | IMPLEMENTED | Gate 6 — position_size_pct, total_exposure |
| Position limits | PARTIAL | Policy-defined, not runtime-enforced |
| Account state (readonly) | IMPLEMENTED | `okx_readonly_account.py` — HMAC-signed GET only |
| Paper Executor | SKELETON | `execution.py` — PaperExecutor + ShadowExecutor |
| Order state | ABSENT | No order tracking |
| Position reconciliation | ABSENT | No reconciliation loop |
| Retry/idempotency | ABSENT | No idempotency keys |
| Persistence (SQLite) | IMPLEMENTED | `db_store.py`, `ledger.py` |
| DB migrations | IMPLEMENTED | `db_migrations.py` |
| Event log | IMPLEMENTED | `ledger.py` |
| Audit trail | PARTIAL | Ledger records decisions but not full audit |
| Scheduler | ABSENT | No scheduled execution |
| Long-running loop | SKELETON | `runtime.py:run_loop()` exists |
| Daemon/service | ABSENT | No daemon process |
| Heartbeat | ABSENT | No health check |
| Process supervisor | ABSENT | No supervisor process |
| Crash recovery | ABSENT | No state resume from DB on restart |
| State resume | ABSENT | All state in memory |
| Dashboard | IMPLEMENTED | `dashboard.py` — HTTP server on 28787 |
| API/server | SKELETON | Dashboard only, no REST API |
| Secrets handling | PARTIAL | Env vars, not in git. No vault. |
| Config loading | IMPLEMENTED | JSON policy + env var overrides |
| Environment validation | PARTIAL | Some startup checks, not exhaustive |
| Deployment (Docker) | ABSENT | No Dockerfile |
| CI | IMPLEMENTED | Two workflows |
| Freqtrade adapter | IMPLEMENTED | 828-line strategy wrapper |
| Backtest matrix | IMPLEMENTED | Canonical runner + Round1 (11 variants) |
| Lookahead analysis | IMPLEMENTED | Parser + decision engine + contract consumer |
| Walk-forward | IMPLEMENTED | `evaluator.py` |
| Out-of-sample | PARTIAL | Via multi-period backtests |
| Telemetry | IMPLEMENTED | `_telemetry.json` per-variant |
| Experiment registry | PARTIAL | Round1 script, not persistent |
| Human approval | ABSENT | No approval gate |
| Emergency stop | IMPLEMENTED | `risk.py` Gate 2, state flag |
| Kill switch | IMPLEMENTED | `risk.py` Gate 1, flag file |
| Live gate | ABSENT | No explicit live enable toggle |

### 3.3 Code Size

| File | Lines |
|------|-------|
| ai_supervised_strategy.py (Freqtrade wrapper) | 828 |
| models/trade_intent.py | 284 |
| providers/base.py | 225 |
| strategy_registry.py | 212 |
| providers/openai_provider.py | 211 |
| evaluator.py | 209 |
| okx_readonly_account.py | 208 |
| scoring.py | 203 |
| providers/deepseek_provider.py | 197 |
| risk.py | 178 |
| dashboard.py | 174 |
| **TOTAL (31 modules)** | **4,218** |

---

## 4. Runtime Truth Maps

### A. Backtest Path
```
Freqtrade CLI → ai_supervised_strategy.populate_indicators()
  → populate_entry_trend()
    → _init_atos()
      → ProviderManager(MockProvider)
      → RiskEngine(policy)
    → _builtin_candidates(window_df) [fallback]
    → experiment filter: disabled_strategies, strategy_weights
    → ProviderManager.decide(request)
    → provider_result.intent (TradeIntent)
    → RiskEngine.evaluate(intent.to_dict(), state)
    → risk_decision.to_dict()
    → enter_long = 1 if APPROVED + BUY
  → Freqtrade backtest engine
    → STRATEGY SUMMARY (trades, profit, winrate, drawdown)
```

### B. Lookahead Path
```
Freqtrade CLI → lookahead-analysis
  → sliced backtests (full vs incremental data)
  → comparison table (has_bias, biased_entry, biased_exit)
  → parse_lookahead_result() → {status, has_bias, evidence_source}
  → decide_lookahead(rc, parsed, output) → {final_status, reason}
  → _lookahead_status.json
```

### C. Round1 Experiment Path
```
ci_strategy_fix_round1.py
  → canonical load (canonical_baseline_summary.json)
  → baseline integrity check (5 metrics)
  → for each variant (11 total):
      → apply_overrides(base_policy, overrides) → exp_policy.json
      → subprocess.run(["python3", "run_canonical_backtest.py", ...])
        → Freqtrade backtesting → ZIP result
        → extract: total_trades, profit_total_pct, winrate, max_drawdown_pct
        → _summary.json
      → best 2 non-baseline:
        → subprocess (RUN_LOOKAHEAD=1)
          → Freqtrade lookahead-analysis
          → write _lookahead_status.json
        → consume_lookahead_status(wrapper_rc, status_path)
        → b["lookahead"] = c["lookahead"]
  → strategy_fix_round1.md report
```

### D. CLI Path
```
python -m atos.cli <command>
  status → StateService.current()
  run-once → AutonomousRuntime.run_once()
  dashboard → run_dashboard()
  backtest → (delegates to Freqtrade)
```

### E. Runtime Path (skeleton)
```
AutonomousRuntime.run_loop(symbol, candle_supplier, loops, interval)
  → while loop:
      → candles = candle_supplier()
      → run_once(symbol, candles)
        → default_strategies() → candidates
        → ProviderManager.decide() → provider_result
        → provider_result.intent → TradeIntent
        → RiskEngine.evaluate(intent.to_dict(), state)
        → PaperExecutor.execute(intent, risk, mark_price, equity)
        → Ledger.record() × 5
      → sleep(interval)
```

### F. Provider Path
```
ProviderManager.decide(request)
  → for each provider in chain:
      → try:
          provider.decide(request) → ProviderResult
          if result.valid: return
      → except: continue
  → fallback: MockProvider → ProviderResult
```

### G. Risk Path
```
RiskEngine.evaluate(intent, state)
  → Gate 1: Kill switch (flag file)
  → Gate 2: Emergency stop (state flag)
  → Gate 3: Mode guard (paper/guarded)
  → Gate 4: Symbol allowlist
  → Gate 5: Confidence threshold
  → Gate 6: Position/exposure limits
  → Gate 7: Daily trade limit (per decision_day)
  → Gate 8: Duplicate cooldown (per decision_ts)
  → Gate 9: Drawdown guard
  → Gate 10: Required fields validation
  → return RiskDecision(APPROVED / REJECTED / KILL_SWITCH_ACTIVE / PAUSED)
```

### H. Execution Path
```
PaperExecutor.execute(trade_intent, risk_decision, mark_price, equity)
  → if decision != APPROVED: return BLOCKED_BY_RISK
  → if action == HOLD: return NOOP_HOLD
  → notional = equity * position_size_pct / 100
  → fee = notional * fee_bps / 10000
  → return ExecutionResult(FILLED_SIMULATED)
```

### Boundary Map

| Boundary | Type |
|----------|------|
| `subprocess.run(["freqtrade", ...])` | Process boundary |
| `subprocess.run(["python3", "run_canonical_backtest.py", ...])` | Process boundary |
| `freqtrade_data/` dir | File boundary |
| `config/policy.*.json` | File boundary |
| `_summary.json` / `_lookahead_status.json` | JSON boundary |
| `db_store.py` / `ledger.py` → SQLite | DB boundary |
| `okx_readonly_account.py` → OKX API | External API boundary |
| `ProviderManager.decide()` → AI API | External API boundary (when not Mock) |

---

## 5. 24/7 Autonomous Runtime Gap Analysis

| Required Capability | Status |
|---------------------|--------|
| Auto market data fetch | PARTIAL — `market.py` has fetch, no scheduler |
| Auto account sync | SKELETON — read-only adapter exists, not scheduled |
| Auto candidate generation | IMPLEMENTED |
| Auto AI decision | IMPLEMENTED (Mock provider) |
| Auto risk check | IMPLEMENTED |
| Auto paper execution | SKELETON — no position tracking |
| Auto reconciliation | **ABSENT** |
| Auto persistence | PARTIAL — DB writes work, no resume |
| Auto heartbeat | **ABSENT** |
| Auto crash recovery | **ABSENT** |
| Auto resume | **ABSENT** |
| Auto audit | PARTIAL — ledger records exist |
| Auto report | PARTIAL — only via CLI/dashboard |

**CRITICAL GAP: The system has no daemon, no scheduler, no restart, no recovery, no heartbeat, no observability.**

---

## 6. Research Plane vs Runtime Plane: PARTIAL

### Current Separation

| Plane | Modules | Status |
|-------|---------|--------|
| **Research** | Freqtrade adapter, canonical runner, Round1, CI scripts, evaluator, scoring, reports | IMPLEMENTED |
| **Runtime** | runtime.py, execution.py, market.py, risk.py, ledger.py, dashboard.py | SKELETON |

### Coupling Points

| Coupling | Risk |
|----------|------|
| `AutonomousRuntime` used by `ResearchLoop` | Shared state between research and runtime |
| Freqtrade strategy imports `ProviderManager`, `RiskEngine` directly | Cannot swap provider/risk for backtest vs live |
| Same `risk.py` for backtest and live | Gate modifications affect both planes |
| `ledger.py` shared | Research events pollute production ledger |
| `policy.json` shared | Backtest validation settings leak to runtime if not guarded |

### Verdict: PARTIAL — needs architectural separation

---

## 7. Critical Safety Audit

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | AI → executor direct path? | **PASS** | ProviderResult → TradeIntent → RiskEngine (gate) → Executor |
| 2 | Provider bypass risk? | **PASS** | RiskEngine.evaluate() called before execution |
| 3 | Risk failure → trade fallback? | **PASS** | `if decision != "APPROVED" → BLOCKED_BY_RISK` |
| 4 | Provider ERROR → HOLD? | **PASS** | Mock provider returns HOLD on error |
| 5 | Invalid JSON → HOLD? | **PASS** | `make_hold()` on parse failure |
| 6 | Low confidence → HOLD? | **PASS** | Gate 5: `confidence < min_conf → rejected` |
| 7 | Stale market data → HOLD? | **PARTIAL** | `data_freshness.py` exists but not wired into decision loop |
| 8 | Missing account data → HOLD? | **UNKNOWN** | Account adapter exists but no automatic fallback |
| 9 | Live default false? | **PASS** | Policy mode = "paper" default |
| 10 | Accidental live enable? | **PASS** | No `LIVE_MODE` or `production_mode` in code |
| 11 | Secret in logs? | **PASS** | `validate_no_secrets.sh` passed; no secret leakage |
| 12 | Secret in prompt? | **PASS** | Keys read from env vars, not embedded |
| 13 | Duplicate order risk? | **FAIL** | No idempotency key. Same intent could execute twice |
| 14 | Idempotency key? | **ABSENT** | No order dedup |
| 15 | Reconciliation? | **ABSENT** | No order vs position vs ledger reconciliation |
| 16 | Partial fill handling? | **ABSENT** | PaperExecutor assumes full fill always |
| 17 | Order timeout? | **ABSENT** | No order timeout logic |
| 18 | Exchange disconnect? | **ABSENT** | No circuit breaker |
| 19 | Process restart recovery? | **ABSENT** | All state in memory |
| 20 | Emergency stop? | **PASS** | Gate 2: emergency_stop state flag |

### Safety Summary

| Rating | Count |
|--------|-------|
| PASS | 10 |
| PARTIAL | 1 |
| FAIL | 1 |
| ABSENT | 5 |
| UNKNOWN | 1 |

---

## 8. Dead Code / Duplicate Logic Audit

| Item | Status | Action |
|------|--------|--------|
| `providers.py` (flat, old) | **DUPLICATED** | Exists alongside `providers/` package. Both define ProviderManager. Remove old. |
| `providers/__init__.py` re-exports from `.base` | OK | Correct delegation |
| `parse_round1.py` at repo root | **DEAD** | Temporary analysis script, not imported anywhere |
| `_fix_canonical.py` | **DELETED** | Cleaned in hygiene commit |
| `apply_fix.py` | **DELETED** | Cleaned in hygiene commit |
| 3x lookahead paths (parser, decision, contract) | **CLEAN** | Now single chain: parser → decision → contract |
| Old exception handler chains in round1 | **CLEANED** | ccbd1fa removed stale except blocks |
| `run_canonical_backtest.py` imports at top vs inline | **CLEAN** | Top-level imports for parser/decision, no duplicate |
| Freqtrade strategy `_FALLBACK_POLICY` | **DUPLICATED** | Same values as `config/policy.json` |

---

## 9. Configuration Audit

### Config Files

| File | Type | Risk |
|------|------|------|
| `config/policy.json` | Safety-immutable | Risk limits, allowed symbols |
| `config/policy.validation.json` | Experiment-only | max_trades_per_day=200, cooldown=0 |
| `config/policy.experiment_round1.json` | Experiment-only | strategy weights, disabled strategies, no_sub |
| `freqtrade_data/config.dryrun.json` | Runtime (generated) | Created by `setup_freqtrade.sh` |
| `pyproject.toml` | Build | Dependencies |

### Config Issues

| Issue | Severity |
|-------|----------|
| `_FALLBACK_POLICY` in strategy duplicates `policy.json` | P3 LOW |
| Validation policy (cooldown=0, daily=200) could accidentally become production | P2 MEDIUM |
| `config.dryrun.json` overwritten by setup script on each run | P2 MEDIUM |
| No config validation on startup | P2 MEDIUM |
| No immutable config manifest | P3 LOW |

---

## 10. Persistence / Recovery Audit

| Question | Answer |
|----------|--------|
| Open positions recovery | **memory only** — CRITICAL GAP |
| Pending orders recovery | **memory only** — CRITICAL GAP |
| Last decision recovery | SQLite ledger exists — PARTIAL. `ledger.py:query()` can retrieve |
| Cooldown recovery | **memory only** — `RiskEngine._recent_signals` lost on restart |
| Daily loss state recovery | **memory only** — `RiskEngine._daily_trades` lost on restart |
| Provider request state | **memory only** |
| Market freshness | Not persisted — `DataFreshness` in-memory only |
| Audit trail | Ledger records exist — PARTIAL. `ledger.py:record()` writes JSON |
| DB schema | `db_store.py` — SQLite with 7 tables (events, snapshots, candidates, decisions, assessments, outcomes, scores) |

---

## 11. Deployment Reality Audit

| Capability | Status |
|------------|--------|
| Standalone start via CLI | `python -m atos.cli` — **works** |
| Docker | **ABSENT** — No Dockerfile |
| systemd | **ABSENT** — No service file |
| launchd | **ABSENT** |
| GitHub Actions | Used for **CI only** — not a trading runtime |
| Config reload without restart | **ABSENT** |
| Log rotation | **ABSENT** |
| Health check endpoint | **ABSENT** — Dashboard has no `/health` |
| Readiness probe | **ABSENT** |
| Liveness probe | **ABSENT** |
| Metrics export | **ABSENT** — No Prometheus/OpenMetrics |
| Alerting | **ABSENT** |

---

## 12. Dependency DAG (Recommended Implementation Order)

```
Persistent State + Recovery (SQLite resume)
      ↓
Runtime Supervisor (daemon, health, restart)
      ↓
Market/Account Sync (scheduled fetch)
      ↓
Decision Loop (existing run_once + scheduling)
      ↓
Paper Execution + Position Tracking
      ↓
Reconciliation (orders vs positions vs ledger)
      ↓
Observability (heartbeat, metrics, logs)
      ↓
Shadow/Live Execution Gate
```

---

## 13. Next 10 Implementation Epics

| # | Epic | Why Now | Dependencies | Scope | Risk |
|---|------|---------|-------------|-------|------|
| **E1** | Persistent State Resume | All state in memory; crash = total loss | SQLite schema exists | **M** | None |
| **E2** | Runtime Supervisor | No daemon exists | E1 | **M** | None |
| **E3** | Scheduled Market Sync | Manual data fetch only | E2 | **S** | API key exposure |
| **E4** | Position Tracking | Paper execution is no-op for positions | E2 | **M** | Order tracking accuracy |
| **E5** | Reconciliation Engine | No consistency check between orders/positions/ledger | E4 | **L** | Complexity |
| **E6** | Heartbeat + Observability | No health endpoint | E2 | **S** | None |
| **E7** | Docker Deployment | No reproducible deployment | E1-E2 | **S** | Container security |
| **E8** | Provider De-duplication | Two ProviderManager implementations | None | **S** | Import breakage |
| **E9** | Kill Switch Auto-Reset | Kill switch is manual-only | E2 | **S** | Safety regression |
| **E10** | Shadow/Live Execution Gate | No explicit live enable toggle | E1-E6 | **M** | Live money risk |

### Epic Detail

#### E1: Persistent State Resume
- **Files**: `runtime.py`, `risk.py`, `db_store.py`, `ledger.py`
- **Acceptance**: After SIGKILL, restart resumes from last checkpoint
- **Tests**: Crash-and-resume integration test

#### E2: Runtime Supervisor
- **Files**: New `supervisor.py`
- **Acceptance**: Daemon loop, restart on crash, health endpoint
- **Tests**: Supervisor restart test, heartbeat test

#### E3: Scheduled Market Sync
- **Files**: `market.py`, `okx_cache.py`
- **Acceptance**: Auto-fetch on configurable interval
- **Tests**: Schedule accuracy, stale-data guard

#### E4: Position Tracking
- **Files**: `execution.py`, New `positions.py`
- **Acceptance**: Paper positions tracked across restarts
- **Tests**: Position open/close lifecycle

#### E5: Reconciliation Engine
- **Files**: New `reconciliation.py`
- **Acceptance**: Mismatch between orders, positions, and ledger detected
- **Tests**: Reconciliation test with synthetic mismatches

#### E6: Heartbeat + Observability
- **Files**: `dashboard.py`, New `metrics.py`
- **Acceptance**: `/health` endpoint, basic Prometheus metrics
- **Tests**: Health check test

#### E7: Docker Deployment
- **Files**: New `Dockerfile`, `docker-compose.yml`
- **Acceptance**: `docker compose up` starts system
- **Tests**: Container startup smoke test

#### E8: Provider De-duplication
- **Files**: `providers.py` (delete), `providers/__init__.py`
- **Acceptance**: Single import path for ProviderManager
- **Tests**: Import and initialization tests

#### E9: Kill Switch Auto-Reset
- **Files**: `risk.py`, `runtime.py`
- **Acceptance**: Kill switch auto-checks on each loop
- **Tests**: Kill switch activation/deactivation test

#### E10: Shadow/Live Execution Gate
- **Files**: `execution.py`, `runtime.py`
- **Acceptance**: Multi-signature live enable
- **Tests**: Live gate cannot be bypassed

---

## 14. Direct Answers (A14)

1. **当前项目本质上是什么？**  
   **Hybrid** — primarily a research/backtest framework with deep rigor (244t canonical baseline, 0% lookahead bias, 11-variant Round1 matrix). Has skeleton runtime aspirations but missing 24/7 daemon, crash recovery, reconciliation.

2. **距离真正 24/7 autonomous paper runtime 还缺什么？**  
   Scheduler, process supervisor, crash recovery, state resume, position tracking, reconciliation, heartbeat, deployment.

3. **当前最大架构风险是什么？**  
   All state in memory. Process crash = total loss of positions, orders, cooldown, daily loss counter.

4. **当前最大 safety gap 是什么？**  
   No position reconciliation. Paper executor could drift silently without detection.

5. **当前最大 reliability gap 是什么？**  
   No crash recovery path. No restart. No health check.

6. **当前最大 observability gap 是什么？**  
   No heartbeat, no metrics, no alerting. Dashboard exists but has no health endpoint.

7. **当前最可能导致真实资金损失的 5 个问题是什么？**  
   (1) No idempotency → duplicate orders  
   (2) No reconciliation → untracked positions  
   (3) No circuit breaker on exchange disconnect  
   (4) Stale data guard unwired into decision loop  
   (5) Accidental live mode via config drift

8. **Freqtrade 当前应该是什么角色？**  
   **Research/Backtest Engine** (not core runtime). Core runtime should be ATOS-native with Freqtrade as optional adapter. Evidence: Freqtrade is only used for backtest/lookahead; live paper path is via `AutonomousRuntime.run_loop()` in `runtime.py`.

9. **是否应该现在 Round2？**  
   **NO.** Evidence: Backtest profit -16.12%, all 8 experiment variants worse than baseline, no persistent state layer. Round2 would waste CI minutes without foundation.

10. **下一阶段唯一推荐目标是什么？**  
    **Implement persistent state + runtime supervisor foundation** (Epics E1+E2). These unlock all subsequent phases.

---

## 15. Final Recommendation

```
RECOMMENDED NEXT PHASE:
  Persistent State + Runtime Supervisor Foundation (Epics E1 + E2)

READY TO IMPLEMENT:
  YES — stabilization checkpoint READY, evidence chain proven

LIVE:
  FORBIDDEN
```
