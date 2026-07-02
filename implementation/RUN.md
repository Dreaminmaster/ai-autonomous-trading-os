# Implementation Run Guide

This directory contains the current product source implementation.

Run from repository root:

```bash
cd implementation
python -m pip install -e '.[dev]'
python python/cli.py status
python python/cli.py risk
python python/cli.py cycle
python python/cli.py review
python python/cli.py market --symbol BTC-USDT
pytest
```

Expected behavior:

- default mode is paper
- strategy pool generates candidates
- decision/provider layer emits structured intent
- risk engine approves or rejects
- paper executor simulates result
- ledger writes runtime records
- public market adapter can fetch ticker/candles/orderbook
- review layer can produce strategy score recommendations
- production boundary is disabled by default

Current implementation modules:

```text
python/atos_core.py
python/models.py
python/strategy_pool.py
python/decision_layer.py
python/provider_layer.py
python/risk_engine.py
python/paper_executor.py
python/ledger_store.py
python/market_data.py
python/history_replay.py
python/review_layer.py
python/run_demo.py
python/cli.py
python/production_guard.py
```
