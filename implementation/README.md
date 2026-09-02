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

# 3. Run one account-free public-market cycle
python -m atos.cli operate --mode paper --symbols BTC-USDT --loops 1
python -m atos.cli operate --mode shadow --symbols BTC-USDT,ETH-USDT --loops 1

# Long-running public-only Shadow supervisor (Ctrl-C/SIGTERM stops safely)
python -m atos.cli supervise --symbols BTC-USDT,ETH-USDT \
  --interval-seconds 60 --max-loops 0

# Read-only liveness/status check. Every ambiguity reports HOLD; it cannot
# start/stop the process or authorize Live.
python -m atos.cli shadow-status

# Bounded operational smoke run; writes atomic health and durable audit state
python -m atos.cli supervise --symbols BTC-USDT --interval-seconds 0 --max-loops 1

# After a completed soak, build one immutable read-only evidence package.
# The exact deployed commit is mandatory and the report can never enable Live.
python -m atos.cli shadow-evidence \
  --implementation-sha "$(git rev-parse HEAD)" \
  --evidence-output runtime/evidence/shadow-soak-001

# Inspect a durable recovery lock (read-only)
python -m atos.cli recover --mode paper --database-path runtime/atos_runtime.sqlite

# Resolve only after reviewing the snapshot; both arguments are mandatory
python -m atos.cli recover --mode paper --database-path runtime/atos_runtime.sqlite \
  --confirm-recovery <sha256-token> --reason "reviewed simulated pre-dispatch failure"

# 4. Setup Freqtrade (requires macOS/Linux, not iOS)
./scripts/setup_freqtrade.sh
./scripts/download_data.sh
./scripts/run_backtest.sh
./scripts/run_dryrun.sh

# 5. Dashboard
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
- This repository has **no connected Live execution path**
- Paper/Shadow decisions use the canonical SQLite lifecycle with immutable
  intents, deterministic idempotency, simulated fills, and position accounting
- API keys are **never** stored in code, git, logs, or prompts
- Any failure → **HOLD** (no trade)

## Modes

| Mode | Description | Default |
|------|-------------|---------|
| `design` | Docs and planning only | — |
| `backtest` | Historical replay | — |
| `paper` | Simulated execution | ✅ |
| `shadow` | Live market, simulated orders | — |
| `live` | Real orders | Forbidden; runtime rejects it before data access |

## CLI Commands

```bash
python -m atos.cli status       # System status
python -m atos.cli risk         # Risk engine self-check
python -m atos.cli cycle        # Single decision cycle
python -m atos.cli loop --loops 3  # Multi-loop autonomous run
python -m atos.cli operate --mode paper --symbols BTC-USDT --loops 1  # Public data + simulated fill
python -m atos.cli operate --mode shadow --symbols BTC-USDT --loops 1 # Public observation + simulated decision
python -m atos.cli review       # Strategy scoring
python -m atos.cli market --symbol BTC-USDT  # OKX public data
python -m atos.cli recover --mode paper       # Inspect durable recovery; no mutation by default
python -m atos.cli shadow-evidence --help      # Completed Shadow soak assessment
python -m atos.cli shadow-status               # Read-only supervisor liveness
python -m atos.cli dashboard    # HTTP dashboard
python -m atos.cli_ext state    # System state
python -m atos.cli_ext evaluate # Evaluation metrics
python -m atos.cli_ext timer    # Timer test
```

## Tests

```bash
pytest                          # Full deterministic test suite
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
