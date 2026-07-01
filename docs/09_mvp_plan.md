# 09 MVP Plan and Final Product Plan

## MVP goal

The first implementation should prove the architecture without risking real funds.

MVP target:

```text
AI can generate structured trade intents from historical/live-like data, risk manager can approve/reject, paper executor can simulate, ledger can record, review layer can summarize.
```

No live trading in MVP.

## MVP modules

### 1. Project scaffold

Recommended Python structure:

```text
src/trading_os/
  config/
  data/
  features/
  strategies/
  ai/
  risk/
  execution/
  ledger/
  evaluation/
  review/
  governance/
  cli/
```

### 2. Config system

- load YAML configs,
- environment variable support,
- no secrets in config files,
- config hash logging.

### 3. Schemas and validators

Implement validators for:

- trade intent,
- risk decision,
- trade review,
- strategy card.

### 4. Data ingestion MVP

Start with:

- CSV or downloaded historical OHLCV,
- optional OKX public market data,
- no private trading key needed.

### 5. Strategy MVP

Implement simple baseline strategies:

- trend following,
- mean reversion,
- breakout,
- HOLD baseline.

### 6. AI decision MVP

Start with:

- mock provider,
- then manually selected LLM provider,
- strict JSON output,
- schema validation,
- default HOLD on invalid output.

### 7. Risk MVP

Implement:

- mode check,
- symbol whitelist,
- max position size,
- confidence threshold,
- stop loss requirement,
- max daily trades,
- duplicate order protection,
- kill switch.

### 8. Paper execution MVP

Implement:

- simulated orders,
- fees,
- simple slippage,
- position tracking,
- PnL calculation,
- ledger records.

### 9. Evaluation MVP

Implement:

- historical replay,
- basic backtest metrics,
- cost model,
- report generation.

### 10. Review MVP

Implement:

- daily paper trading summary,
- per-strategy performance,
- AI review prompt output,
- strategy score table.

## MVP acceptance tests

MVP passes only if:

- no live OKX order code is called,
- invalid AI JSON becomes HOLD,
- risk rejection blocks execution,
- kill switch blocks execution,
- paper ledger records every trade intent,
- fees/slippage affect PnL,
- backtest is chronological,
- secrets are not stored or printed.

## Phase 2

Add:

- OKX public data adapter,
- OKX read-only account adapter,
- better feature builder,
- richer strategies,
- walk-forward validation,
- provider manager for Anges/DeepSeek/local models,
- natural language model selection if desired.

## Phase 3

Add:

- shadow mode,
- live market paper decisions,
- reconciliation logic,
- incident reports,
- strategy weight evolution.

## Phase 4

Add tiny live spot trading, disabled by default.

Requirements:

- sub-account,
- trade-only API key,
- no withdrawals,
- no transfers,
- IP whitelist if possible,
- tested kill switch,
- tiny capital cap,
- explicit approval.

## Final product modules

The final system should include:

- desktop/web dashboard,
- live/paper mode status,
- strategy board,
- risk dashboard,
- trade intent viewer,
- AI thesis viewer,
- ledger browser,
- review reports,
- backtest runner,
- walk-forward runner,
- provider manager,
- API key setup wizard,
- kill switch button,
- incident center.
