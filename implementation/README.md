# AI Autonomous Trading OS — Implementation

## Quick Start

```bash
cd implementation

# 1. Install ATOS
pip install -e '.[dev]'

# 2. Verify ATOS works
python -m atos.cli status
python -m atos.cli cycle
pytest

# 3. Setup Freqtrade (requires macOS/Linux, not iOS)
./scripts/setup_freqtrade.sh
./scripts/download_data.sh
./scripts/run_backtest.sh
./scripts/run_dryrun.sh

# 4. Dashboard
./scripts/run_dashboard.sh
```

## Architecture

```
               ┌─────────────────────┐
               │   Market Data       │  (OKX public, CSV, …)
               └────────┬────────────┘
                        ▼
               ┌─────────────────────┐
               │   Feature Builder   │  (MA, RSI, Bollinger, …)
               └────────┬────────────┘
                        ▼
               ┌─────────────────────┐
               │   Strategy Pool     │  (trend, mean_reversion, breakout, …)
               └────────┬────────────┘
                        ▼
               ┌─────────────────────┐
               │   AI Provider       │  (mock / OpenAI / DeepSeek / Anges)
               └────────┬────────────┘
                        ▼
               ┌─────────────────────┐
               │   Trade Intent      │  (structured JSON, schema validated)
               └────────┬────────────┘
                        ▼
               ┌─────────────────────┐
               │   Risk Supervisor   │  (deterministic, cannot be bypassed)
               └────────┬────────────┘
                        ▼
               ┌─────────────────────┐
               │   Execution         │  (paper / shadow / guarded live)
               └────────┬────────────┘
                        ▼
               ┌─────────────────────┐
               │   Ledger            │  (SQLite, full audit trail)
               └─────────────────────┘
```

## Safety Rules

- AI **never** places orders directly
- All trade intents **must** pass deterministic risk checks
- Default mode is **dry-run** (paper trading)
- Live trading requires **explicit** config change
- API keys are **never** stored in code, git, logs, or prompts
- Any failure → **HOLD** (no trade)

## Modes

| Mode | Description | Default |
|------|-------------|---------|
| `design` | Docs and planning only | — |
| `backtest` | Historical replay | — |
| `paper` | Simulated execution | ✅ |
| `shadow` | Live market, simulated orders | — |
| `live` | Real orders | Disabled |

## CLI Commands

```bash
python -m atos.cli status       # System status
python -m atos.cli risk         # Risk engine self-check
python -m atos.cli cycle        # Single decision cycle
python -m atos.cli loop --loops 3  # Multi-loop autonomous run
python -m atos.cli review       # Strategy scoring
python -m atos.cli market --symbol BTC-USDT  # OKX public data
python -m atos.cli dashboard    # HTTP dashboard
python -m atos.cli_ext state    # System state
python -m atos.cli_ext evaluate # Evaluation metrics
python -m atos.cli_ext timer    # Timer test
```

## Tests

```bash
pytest                          # 12 tests, all pass
./scripts/validate_no_secrets.sh  # Scan for secret leakage
```

## Freqtrade Integration

The bridge between ATOS and Freqtrade is [`user_data/strategies/ai_supervised_strategy.py`](user_data/strategies/ai_supervised_strategy.py).

This strategy:
1. Accepts Freqtrade candles
2. Runs ATOS strategy pool
3. Calls AI provider for decision
4. Passes through deterministic risk supervisor
5. Returns Freqtrade signals (enter_long/exit_long)

Works even without ATOS installed — includes a built-in fallback.
