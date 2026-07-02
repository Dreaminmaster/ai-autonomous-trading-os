# Implementation Run Guide

This directory contains the current product source implementation.

Run from repository root:

```bash
cd implementation
python -m pip install -e '.[dev]'
python -m atos.cli status
python -m atos.cli risk
python -m atos.cli cycle
python -m atos.cli loop --loops 3
python -m atos.cli review
python -m atos.cli market --symbol BTC-USDT
python -m atos.cli dashboard --port 8787
pytest
```

Legacy compatibility commands are still available under `python/cli.py`.

Expected behavior:

- default mode is paper
- strategy pool generates candidates
- provider layer emits structured intent
- risk engine approves or rejects
- paper executor simulates result
- ledger writes runtime records
- public market adapter can fetch ticker, candles, orderbook, trades, funding, and open-interest interfaces
- scoring layer can produce strategy recommendations
- autonomous runtime can loop without Harness per-trade involvement
- local dashboard can show recent ledger events
- guarded exchange path is disabled by default

Current standard implementation modules:

```text
src/atos/core.py
src/atos/domain.py
src/atos/strategies.py
src/atos/providers.py
src/atos/risk.py
src/atos/execution.py
src/atos/ledger.py
src/atos/market.py
src/atos/history.py
src/atos/scoring.py
src/atos/runtime.py
src/atos/dashboard.py
src/atos/cli.py
```
