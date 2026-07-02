from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass
class MarketDataSnapshot:
    symbol: str
    ticker: dict[str, Any]
    candles: list[list[Any]]
    orderbook: dict[str, Any]


class PublicMarketDataAdapter:
    def __init__(self, base_url: str = 'https://www.okx.com'):
        self.base_url = base_url.rstrip('/')

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f'{self.base_url}{path}?{query}'
        req = urllib.request.Request(url, headers={'User-Agent': 'ai-autonomous-trading-os/0.1'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))

    def ticker(self, inst_id: str) -> dict[str, Any]:
        return self._get('/api/v5/market/ticker', {'instId': inst_id})

    def candles(self, inst_id: str, bar: str = '1m', limit: int = 100) -> dict[str, Any]:
        return self._get('/api/v5/market/candles', {'instId': inst_id, 'bar': bar, 'limit': limit})

    def orderbook(self, inst_id: str, depth: int = 20) -> dict[str, Any]:
        return self._get('/api/v5/market/books', {'instId': inst_id, 'sz': depth})

    def snapshot(self, inst_id: str) -> MarketDataSnapshot:
        ticker = self.ticker(inst_id)
        candles = self.candles(inst_id)
        orderbook = self.orderbook(inst_id)
        return MarketDataSnapshot(
            symbol=inst_id,
            ticker=ticker,
            candles=candles.get('data', []),
            orderbook=orderbook,
        )
