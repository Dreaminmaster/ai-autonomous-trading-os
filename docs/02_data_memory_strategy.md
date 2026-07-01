# 02 Data, Memory, and Strategy Layers

## Data Layer requirements

Data must be reproducible, timestamped, and separated by source.

Recommended tables:

- `market_candles`
- `orderbook_snapshots`
- `public_trades`
- `funding_rates`
- `open_interest`
- `account_snapshots`
- `position_snapshots`
- `news_items`
- `social_signals`
- `onchain_signals`

Every row should include:

- source
- symbol
- timestamp from source
- ingestion timestamp
- raw payload hash
- normalized fields

## Point-in-time rule

Backtests must only use data that would have been available at that historical timestamp.

Bad:

```text
AI sees a full-day candle before the day is over.
AI uses news that was published after the simulated decision time.
AI uses future funding or future realized volatility.
```

Good:

```text
At simulated time T, only records with available_at <= T can be used.
```

## Memory Layer

### Operational memory

Used by the live system:

- current balance
- current positions
- open orders
- current strategy weights
- active risk state
- kill switch state

### Learning memory

Used by AI review and strategy evolution:

- trade thesis
- market regime at decision time
- features used
- outcome
- review
- lessons
- strategy score changes

Learning memory must be versioned. The system must know which memory was available to the AI at decision time.

## Market regime taxonomy

The system should classify market conditions into regimes such as:

- trend up / trend down
- high volatility / low volatility
- range-bound
- breakout attempt
- liquidity shock
- funding overheated
- mean-reversion favorable
- news-driven
- panic / crash
- post-crash recovery

Regime classification can start simple and improve later.

## Strategy Layer

Strategies are plugins. They do not place orders directly.

### Required baseline strategies

1. Trend following
2. Mean reversion
3. Breakout
4. Grid / range trading
5. Volatility breakout
6. Funding / basis awareness
7. Smart-money / on-chain signal strategy
8. News / sentiment strategy
9. AI discretionary strategy

### Strategy candidate format

Each strategy should output:

```json
{
  "strategy_id": "trend_following_v1",
  "symbol": "BTC-USDT",
  "timeframe": "1h",
  "side": "BUY",
  "signal_strength": 0.67,
  "confidence": 0.58,
  "entry_reason": "price above moving average with volume expansion",
  "invalid_if": "price closes below breakout level",
  "suggested_stop_loss_pct": 1.2,
  "suggested_take_profit_pct": 2.4,
  "max_holding_minutes": 240,
  "features_used": ["ma_50", "volume_zscore", "atr"]
}
```

### Strategy weights

Strategy weights should be updated through a controlled process.

Inputs:

- rolling PnL
- max drawdown
- win rate
- profit factor
- average R multiple
- regime-specific performance
- number of trades
- stability across validation windows

No strategy should be promoted based on one lucky trade.
