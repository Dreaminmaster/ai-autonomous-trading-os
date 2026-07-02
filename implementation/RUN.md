# Implementation Run Guide

<!-- validation-trigger: CI workflow dispatch -->

## Quick Start (ATOS only, no Freqtrade — works anywhere Python 3.11+)

```bash
cd implementation
pip install -e '.[dev]'                     # ATOS core + tests only
python -m atos.cli status
python -m atos.cli risk
python -m atos.cli cycle
python -m atos.cli loop --loops 3
python -m atos.cli review
python -m atos.cli market --symbol BTC-USDT
python -m atos.cli dashboard --port 28787
pytest
```

Dashboard: **http://127.0.0.1:28787**

## Full Setup (Freqtrade integration — requires macOS/Linux)

```bash
# Install with Freqtrade support
pip install -e '.[dev,freqtrade]'           # ATOS + Freqtrade + pandas/numpy

# 1. Setup Freqtrade + create config
./scripts/setup_freqtrade.sh

# 2. Verify strategy is discoverable
freqtrade list-strategies --strategy-path freqtrade_data/strategies
# Expected: "AISupervisedStrategy"

# 3. Download OKX historical data
./scripts/download_data.sh

# 4. Run backtest
./scripts/run_backtest.sh

# 5. Lookahead bias analysis
./scripts/run_lookahead_analysis.sh

# 6. Start dry-run (paper trading with live market data)
./scripts/run_dryrun.sh

# 7. ATOS dashboard
./scripts/run_dashboard.sh                  # http://127.0.0.1:28787

# 8. Run all tests + secret scan
./scripts/run_tests.sh
./scripts/validate_no_secrets.sh
```

### Install modes

| Command | Includes | Use for |
|---------|----------|---------|
| `pip install -e '.[dev]'` | ATOS + pytest + ruff | Unit tests, CLI, dashboard only |
| `pip install -e '.[dev,freqtrade]'` | ATOS + Freqtrade + pandas + numpy | Backtest, dry-run, lookahead analysis |

## Freqtrade Dashboard

Freqtrade comes with its own WebUI (separate from ATOS dashboard):

**http://127.0.0.1:8080** (Freqtrade API server, started by dry-run)

ATOS dashboard: **http://127.0.0.1:28787**

## Current Modules

```text
src/atos/
├── core.py / domain.py                     # RunMode, Action, Candle, TradeIntent
├── features.py                             # MA, returns
├── strategies.py / strategy_registry.py    # 9 strategies
├── providers/ (5 files)                    # mock, OpenAI, DeepSeek, compatible
├── models/trade_intent.py                  # Pydantic + JSON Schema validation
├── risk.py                                 # 10 deterministic safety gates
├── execution.py                            # paper / shadow / guarded live
├── ledger.py / db_store.py / db_migrations.py  # SQLite + versioned migrations
├── market.py / market_regime.py            # OKX public adapter + regime detection
├── okx_cache.py / data_freshness.py        # Cache + freshness guard
├── okx_readonly_account.py                 # Read-only account adapter
├── scoring.py                              # Sharpe, drawdown, profit factor
├── evaluator.py                            # walk-forward + Monte Carlo
├── runtime.py                              # AutonomousRuntime loop
├── dashboard.py                            # HTML dashboard + 4 JSON APIs
├── reporting.py / state_service.py         # Reports + state
├── cli.py / cli_ext.py                     # 10 CLI commands
```

## Freqtrade Integration

The bridge: `freqtrade_data/strategies/ai_supervised_strategy.py`

This is a fully functional Freqtrade IStrategy (class: `AISupervisedStrategy`) that:
- Works as a standard Freqtrade strategy (can be used in backtest/dry-run/live)
- Internally calls ATOS pipeline (strategy pool → AI provider → risk check)
- Has a built-in fallback (works even without ATOS installed)
- All safety rules are hard-coded (AI can't bypass risk)
- Default: dry-run only, live requires explicit config change

## Docker Option

```bash
docker pull freqtradeorg/freqtrade:stable
docker run -d --name atos-freqtrade \
  -v $(pwd)/freqtrade_data:/freqtrade/user_data \
  freqtradeorg/freqtrade:stable trade \
  --config /freqtrade/user_data/config.dryrun.json \
  --strategy AISupervisedStrategy \
  --strategy-path /freqtrade/user_data/strategies
```
