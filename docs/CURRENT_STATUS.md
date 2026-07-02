# CURRENT STATUS — AI Autonomous Trading OS

> Generated: 2026-07-02
> Assessed by: Minis agent on iOS iSH (Alpine Linux, Python 3.12)

---

## 1. Current Repository Files

### Root-level
| File | Status | Notes |
|------|--------|-------|
| README.md | OK | Project overview |
| AGENTS.md | OK | Agent implementation guide |
| .gitignore | OK | Standard Python ignores |

### docs/ (10 files)
| File | Status | Notes |
|------|--------|-------|
| 00_overview.md | OK | System overview |
| 01_system_architecture.md | OK | Layered architecture |
| 02_data_memory_strategy.md | OK | Data/strategy layer |
| 03_ai_decision_layer.md | OK | AI decision layer |
| 04_risk_layer.md | OK | Risk layer design |
| 05_execution_layer.md | OK | Execution layer |
| 06_evaluation_layer.md | OK | Evaluation layer |
| 07_review_and_strategy_evolution.md | OK | Review layer |
| 08_governance_and_security.md | OK | Governance |
| 09_mvp_plan.md | OK | MVP & final plan |
| 10_database_schema.md | OK | DB schema design |

### schemas/ (3 files)
| File | Status | Notes |
|------|--------|-------|
| trade_intent.schema.json | OK | JSON Schema 2020-12 |
| risk_decision.schema.json | OK | JSON Schema 2020-12 |
| trade_review.schema.json | OK | JSON Schema 2020-12 |

### configs/ (3 files)
| File | Status | Notes |
|------|--------|-------|
| provider_config.example.yml | OK | Example provider config |
| risk_policy.example.yml | OK | Example risk policy |
| okx_permissions.example.yml | OK | Example OKX permissions |

### prompts/ (3 files)
| File | Status | Notes |
|------|--------|-------|
| ai_trader_system_prompt.md | OK | AI trader prompt |
| daily_review_prompt.md | OK | Daily review prompt |
| risk_reviewer_prompt.md | OK | Risk reviewer prompt |

### tests/ (2 files)
| File | Status | Notes |
|------|--------|-------|
| acceptance_tests.md | OK | Acceptance criteria |
| safety_tests.md | OK | Safety test spec |

### implementation/ (standard package)
| File | Status | Notes |
|------|--------|-------|
| pyproject.toml | OK | Package config, v0.2.0 |
| README.md | OK | Implementation README |
| RUN.md | OK | Run guide |
| PRODUCT_COMPLETION_CHECKLIST.md | OK | What's missing |
| config/policy.json | OK | Default policy |
| scripts/run_all.sh | OK | Run-all script |

### implementation/src/atos/ (21 modules)
| File | Status | Lines | Notes |
|------|--------|-------|-------|
| __init__.py | OK | 4 | v0.2.0 |
| core.py | OK | 41 | RunMode, Action, RuntimeState |
| domain.py | OK | 94 | Candle, TradeIntent, RiskDecision |
| features.py | OK | 16 | MA, simple_return |
| strategies.py | OK | 62 | 4 baseline strategies |
| providers.py | OK | 65 | Mock + ProviderManager |
| risk.py | OK | 66 | Deterministic risk engine |
| execution.py | OK | 51 | Paper/Shadow/Guarded |
| ledger.py | OK | 67 | SQLite ledger |
| db_store.py | OK | 36 | Extended SQLite store |
| market.py | OK | 64 | OKX public API adapter |
| history.py | OK | 50 | CSV replay + metrics |
| scoring.py | OK | 37 | Strategy scoring |
| runtime.py | OK | 62 | Autonomous runtime loop |
| evaluator.py | OK | 42 | Walk-forward, metrics |
| reporting.py | OK | 33 | Report builder |
| research_loop.py | OK | 34 | Research loop |
| timer.py | OK | 30 | Fixed interval timer |
| state_service.py | OK | 31 | State service |
| account_view.py | OK | 40 | Account view interface |
| account_file.py | OK | 25 | File-based account view |
| operator_commands.py | OK | 27 | Operator command parser |
| cli.py | OK | 83 | Main CLI (7 commands) |
| cli_ext.py | OK | 32 | Extended CLI (3 commands) |
| dashboard.py | OK | 55 | Simple HTTP dashboard |

### implementation/tests/ (4 test files)
| File | Status | Tests |
|------|--------|-------|
| test_core.py | OK | 1 test (legacy path) |
| test_package_smoke.py | OK | 3 tests |
| test_more_modules.py | OK | 5 tests |
| test_reporting_and_research.py | OK | 3 tests |

### implementation/python/ (legacy, 13 files)
| File | Status | Notes |
|------|--------|-------|
| atos_core.py | — | Legacy, superseded by src/atos/core.py |
| models.py | — | Legacy, superseded by src/atos/domain.py |
| cli.py | — | Legacy CLI |
| + 10 more | — | Legacy implementations |

**Decision**: `implementation/python/` is legacy. Keep for reference, tests depend on it via sys.path hack (`tests/test_core.py`). Migrate that one test to atos standard package.

---

## 2. Current Runnable Commands

All commands run from `implementation/` directory:

```bash
cd implementation
python -m pip install -e '.[dev]'
python -m atos.cli status       # System status
python -m atos.cli risk         # Risk engine self-check
python -m atos.cli cycle        # Single decision cycle
python -m atos.cli loop --loops 3  # Multi-loop run
python -m atos.cli review       # Strategy scoring
python -m atos.cli market --symbol BTC-USDT  # OKX public data
python -m atos.cli dashboard    # Start HTTP dashboard
python -m atos.cli_ext state    # State service
python -m atos.cli_ext evaluate # Evaluation metrics
python -m atos.cli_ext timer    # Timer test
pytest                          # Run all tests
```

---

## 3. Current Test Results

**All 12 tests pass** ✅

```
============================= 12 passed in 3.12s ==============================
tests/test_core.py::test_hold_intent_ok PASSED
tests/test_more_modules.py::test_evaluator_summary PASSED
tests/test_more_modules.py::test_walk_forward_windows PASSED
tests/test_more_modules.py::test_timer_runs PASSED
tests/test_more_modules.py::test_state_service PASSED
tests/test_more_modules.py::test_empty_account_view PASSED
tests/test_package_smoke.py::test_risk_hold PASSED
tests/test_package_smoke.py::test_strategies_emit_candidates PASSED
tests/test_package_smoke.py::test_runtime_loop_runs PASSED
tests/test_reporting_and_research.py::test_file_account_view_empty PASSED
tests/test_reporting_and_research.py::test_report_builder PASSED
tests/test_reporting_and_research.py::test_research_loop PASSED
```

**CI**: `.github/workflows/ci.yml` runs on push/PR — installs and runs pytest.

---

## 4. Failures Fixed (Stage 1)

| Issue | Root Cause | Fix |
|-------|-----------|-----|
| CLI commands all fail with FileNotFoundError | Default `--policy` path was `implementation/config/policy.json` (relative, double-nested) | Changed to `config/policy.json` in `cli.py` line 62 |

---

## 5. Module Mapping: Current → Target

| Current (src/atos/) | Target | Action |
|---------------------|--------|--------|
| core.py | atos/core.py | KEEP, minor cleanup |
| domain.py | atos/models/ (split) | REFACTOR — split into trade_intent.py, strategy_candidate.py, risk_decision.py |
| features.py | atos/data/feature_builder.py | KEEP, expand |
| strategies.py | atos/strategies/ (split) | SPLIT — each strategy own file |
| providers.py | atos/providers/ (split) | SPLIT — base, mock, openai, deepseek, etc. |
| risk.py | atos/risk/risk_supervisor.py | KEEP, expand |
| execution.py | atos/execution/ (split) | SPLIT — adapter, guards, reconciliation |
| ledger.py | atos/ledger/store.py | KEEP, merge with db_store |
| db_store.py | atos/ledger/migrations.py | MERGE into ledger |
| market.py | atos/data/okx_public_adapter.py | KEEP, rename |
| history.py | atos/research/ | REFACTOR |
| evaluator.py | atos/research/ | KEEP |
| scoring.py | atos/review/strategy_score.py | KEEP |
| runtime.py | atos/runtime/autonomous_loop.py | KEEP |
| timer.py | atos/runtime/scheduler.py | KEEP |
| state_service.py | atos/runtime/state_store.py | KEEP |
| reporting.py | atos/research/report_generator.py | KEEP |
| research_loop.py | atos/research/backtest_runner.py | KEEP |
| dashboard.py | atos/dashboard/app.py | KEEP, expand |
| cli.py / cli_ext.py | atos/cli.py | MERGE |
| account_view.py | atos/data/ | KEEP |
| account_file.py | atos/data/ | KEEP |
| operator_commands.py | atos/runtime/ | KEEP |

---

## 6. Files to Keep / Refactor / Remove

### Keep (stable, move to target dirs)
- core.py, domain.py, risk.py, execution.py, ledger.py
- market.py, features.py, strategies.py
- evaluator.py, scoring.py, runtime.py
- dashboard.py, cli.py, cli_ext.py

### Refactor (functional but needs work)
- providers.py → split into provider manager + per-provider modules
- domain.py → split models into separate files
- history.py → better integration with research loop
- db_store.py → merge into ledger or make separate migration module

### Remove / Archive
- `implementation/python/` — legacy parallel implementation. Keep one test (`test_core.py`) but rewrite it against `atos` package, then remove.

---

## 7. Next Steps (Priority Order)

1. **Stage 1 Complete** ✅ — All tests pass, all CLI commands work
2. **Stage 2: Freqtrade Integration** — Install/setup Freqtrade, download OKX data, run backtest
3. **Stage 3: Freqtrade Strategy Wrapper** — Bridge ATOS ↔ Freqtrade
4. **Stage 4: Trade Intent Hardening** — Pydantic models + JSON schema enforcement
5. **Stage 5: Provider Manager Expansion** — DeepSeek, OpenAI, OpenAI-compatible
6. **Stages 6-17**: Risk supervisor, backtest, review engine, dashboard UI, etc.

---

## 8. Environment Notes

- **Tested on**: Alpine Linux aarch64 (iSH on iOS), Python 3.12
- **OKX public endpoints**: Accessible via `market.py` (no API key needed)
- **Freqtrade**: NOT yet installed. Target: Docker-based or pip install
- **Git push**: May need real network for SSL (iSH sometimes has cert issues)
