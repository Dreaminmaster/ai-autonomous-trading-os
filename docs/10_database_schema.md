# 10 Database Schema

This document defines the first database schema for implementation. SQLite is acceptable for MVP; Postgres can be used later.

## Core principles

- Every decision must be auditable.
- Every record must be timestamped.
- Backtest data must preserve point-in-time availability.
- Secrets must never be stored.

## Tables

### market_candles

```sql
CREATE TABLE market_candles (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  symbol TEXT NOT NULL,
  timeframe TEXT NOT NULL,
  open_time TEXT NOT NULL,
  close_time TEXT NOT NULL,
  open REAL NOT NULL,
  high REAL NOT NULL,
  low REAL NOT NULL,
  close REAL NOT NULL,
  volume REAL NOT NULL,
  available_at TEXT NOT NULL,
  raw_hash TEXT
);
```

### strategy_candidates

```sql
CREATE TABLE strategy_candidates (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  symbol TEXT NOT NULL,
  strategy_id TEXT NOT NULL,
  side TEXT NOT NULL,
  signal_strength REAL NOT NULL,
  confidence REAL NOT NULL,
  payload_json TEXT NOT NULL
);
```

### trade_intents

```sql
CREATE TABLE trade_intents (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  mode TEXT NOT NULL,
  provider TEXT,
  model TEXT,
  schema_version TEXT NOT NULL,
  action TEXT NOT NULL,
  symbol TEXT NOT NULL,
  market_type TEXT NOT NULL,
  confidence REAL NOT NULL,
  payload_json TEXT NOT NULL,
  payload_hash TEXT NOT NULL,
  validation_status TEXT NOT NULL
);
```

### risk_decisions

```sql
CREATE TABLE risk_decisions (
  id TEXT PRIMARY KEY,
  trade_intent_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  decision TEXT NOT NULL,
  risk_score REAL NOT NULL,
  reasons_json TEXT NOT NULL,
  checks_json TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(trade_intent_id) REFERENCES trade_intents(id)
);
```

### orders

```sql
CREATE TABLE orders (
  id TEXT PRIMARY KEY,
  trade_intent_id TEXT NOT NULL,
  risk_decision_id TEXT NOT NULL,
  mode TEXT NOT NULL,
  client_order_id TEXT NOT NULL UNIQUE,
  symbol TEXT NOT NULL,
  side TEXT NOT NULL,
  order_type TEXT NOT NULL,
  requested_qty REAL,
  requested_notional REAL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
```

### fills

```sql
CREATE TABLE fills (
  id TEXT PRIMARY KEY,
  order_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  price REAL NOT NULL,
  qty REAL NOT NULL,
  fee REAL NOT NULL,
  fee_currency TEXT,
  slippage_bps REAL,
  payload_json TEXT NOT NULL,
  FOREIGN KEY(order_id) REFERENCES orders(id)
);
```

### positions

```sql
CREATE TABLE positions (
  id TEXT PRIMARY KEY,
  symbol TEXT NOT NULL,
  mode TEXT NOT NULL,
  strategy_id TEXT,
  qty REAL NOT NULL,
  avg_entry_price REAL NOT NULL,
  stop_loss REAL,
  take_profit REAL,
  opened_at TEXT NOT NULL,
  closed_at TEXT,
  realized_pnl REAL,
  status TEXT NOT NULL
);
```

### trade_reviews

```sql
CREATE TABLE trade_reviews (
  id TEXT PRIMARY KEY,
  trade_intent_id TEXT NOT NULL,
  created_at TEXT NOT NULL,
  outcome TEXT NOT NULL,
  pnl_pct REAL,
  thesis_quality REAL,
  execution_quality REAL,
  risk_quality REAL,
  lesson TEXT NOT NULL,
  recommended_action TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
```

### strategy_scores

```sql
CREATE TABLE strategy_scores (
  id TEXT PRIMARY KEY,
  strategy_id TEXT NOT NULL,
  regime TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  weight REAL NOT NULL,
  return_score REAL,
  drawdown_penalty REAL,
  stability_score REAL,
  fee_efficiency_score REAL,
  evidence_trades INTEGER,
  status TEXT NOT NULL
);
```

### incidents

```sql
CREATE TABLE incidents (
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  severity TEXT NOT NULL,
  category TEXT NOT NULL,
  description TEXT NOT NULL,
  action_taken TEXT NOT NULL,
  resolved_at TEXT,
  payload_json TEXT
);
```

## Secret exclusion

The database must not contain:

- API keys,
- API secrets,
- passphrases,
- seed phrases,
- private account login data.
