# Implementation Run Guide

## Quick Start (ATOS only, works anywhere Python 3.11+)

```bash
cd implementation
python -m pip install -e '.[dev]'
python -m atos.cli status
python -m atos.cli risk
python -m atos.cli cycle
python -m atos.cli loop --loops 3
python -m atos.cli review
python -m atos.cli market --symbol BTC-USDT
python -m atos.cli dashboard --port 28787
pytest
```

Expected behavior:

- default mode is paper
- strategy pool generates candidates (trend_following, mean_reversion, breakout, hold)
- provider layer emits structured intent
- risk engine approves or rejects
- paper executor simulates result
- ledger writes runtime records (SQLite)
- public market adapter can fetch OKX ticker, candles, orderbook, trades, funding, and open-interest
- scoring layer produces strategy recommendations
- autonomous runtime can loop without Harness per-trade involvement
- local dashboard shows recent ledger events
- guarded exchange path is disabled by default (raises PermissionError if called)

## Full Setup (requires macOS or Linux for Freqtrade)

```bash
# 1. Install Freqtrade + create config
./scripts/setup_freqtrade.sh

# 2. Download OKX historical data
./scripts/download_data.sh

# 3. Run backtest
./scripts/run_backtest.sh

# 4. Start dry-run (paper trading with live market data)
./scripts/run_dryrun.sh

# 5. ATOS dashboard
./scripts/run_dashboard.sh

# 6. Run all tests + secret scan
./scripts/run_tests.sh
./scripts/validate_no_secrets.sh
```

## Current Modules

```text
src/atos/
├── core.py              # RunMode, Action, RuntimeState
├── domain.py            # Candle, TradeIntent, RiskDecision, StrategyCandidate
├── features.py          # MA, simple returns
├── strategies.py        # TrendFollowing, MeanReversion, Breakout, HoldBaseline
├── providers.py         # MockProvider, ProviderManager
├── risk.py              # Deterministic RiskEngine
├── execution.py         # PaperExecutor, ShadowExecutor, GuardedExchangeExecutor
├── ledger.py            # SQLite ledger (events, strategy_scores, positions)
├── db_store.py          # Extended SQLite store
├── market.py            # OKX public API adapter (ticker, candles, orderbook, etc.)
├── history.py           # CSV replay + metrics
├── scoring.py           # Strategy scoring engine
├── runtime.py           # AutonomousRuntime loop
├── evaluator.py         # Walk-forward evaluation
├── reporting.py         # Report builder
├── research_loop.py     # Research loop
├── timer.py             # Fixed interval timer
├── state_service.py     # System state service
├── account_view.py      # Account view interface
├── account_file.py      # File-based account adapter
├── operator_commands.py # Operator command parser
├── cli.py               # Main CLI (status, risk, cycle, loop, review, market, dashboard)
├── cli_ext.py           # Extended CLI (state, evaluate, timer)
└── dashboard.py         # Full HTML + JSON API dashboard

    # New modules (stages 11+)
    ├── data_freshness.py     # Data freshness guard (stale data → HOLD)
    ├── market_regime.py      # Market regime detector (trending/volatile/ranging)
    ├── okx_cache.py          # OKX data cache with freshness tracking
    ├── okx_readonly_account.py # Read-only OKX account adapter (no trade)
    ├── db_migrations.py      # Versioned SQLite schema migrations
    └── strategy_registry.py  # Registry + 5 additional strategies
```

## Freqtrade Integration

The bridge: `user_data/strategies/ai_supervised_strategy.py`

This is a fully functional Freqtrade IStrategy that:
- Works as a standard Freqtrade strategy (can be used in backtest/dry-run/live)
- Internally calls ATOS pipeline (strategy pool → AI provider → risk check)
- Has a built-in fallback (works even without ATOS installed)
- All safety rules are hard-coded (AI can't bypass risk)
- Default: dry-run only, live requires explicit config change

## Docker Option

```bash
docker pull freqtradeorg/freqtrade:stable
docker run -d --name atos-freqtrade \
  -v $(pwd)/user_data:/freqtrade/user_data \
  freqtradeorg/freqtrade:stable trade \
  --config /freqtrade/user_data/config.dryrun.json \
  --strategy ai_supervised_strategy
```
