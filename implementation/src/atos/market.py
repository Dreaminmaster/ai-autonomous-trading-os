from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any

from atos.domain import Candle


@dataclass
class MarketSnapshot:
    symbol: str
    ticker: dict[str, Any]
    candles: list[Candle]
    orderbook: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"symbol": self.symbol, "ticker": self.ticker, "candles": [c.to_dict() for c in self.candles], "orderbook": self.orderbook}


class PublicMarketAdapter:
    def __init__(self, base_url: str = "https://www.okx.com"):
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = f"{self.base_url}{path}?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "ai-autonomous-trading-os/0.2"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def ticker(self, inst_id: str) -> dict[str, Any]:
        return self._get("/api/v5/market/ticker", {"instId": inst_id})

    def candles_raw(self, inst_id: str, bar: str = "1m", limit: int = 100) -> dict[str, Any]:
        return self._get("/api/v5/market/candles", {"instId": inst_id, "bar": bar, "limit": limit})

    def trades(self, inst_id: str, limit: int = 100) -> dict[str, Any]:
        return self._get("/api/v5/market/trades", {"instId": inst_id, "limit": limit})

    def orderbook(self, inst_id: str, depth: int = 20) -> dict[str, Any]:
        return self._get("/api/v5/market/books", {"instId": inst_id, "sz": depth})

    def instruments(self, inst_type: str = "SPOT") -> dict[str, Any]:
        return self._get("/api/v5/public/instruments", {"instType": inst_type})

    def funding_rate(self, inst_id: str) -> dict[str, Any]:
        return self._get("/api/v5/public/funding-rate", {"instId": inst_id})

    def open_interest(self, inst_id: str, inst_type: str = "SWAP") -> dict[str, Any]:
        return self._get("/api/v5/public/open-interest", {"instType": inst_type, "instId": inst_id})

    def candles(self, inst_id: str, bar: str = "1m", limit: int = 100) -> list[Candle]:
        raw = self.candles_raw(inst_id, bar=bar, limit=limit).get("data", [])
        candles: list[Candle] = []
        for row in reversed(raw):
            candles.append(Candle(open=float(row[1]), high=float(row[2]), low=float(row[3]), close=float(row[4]), volume=float(row[5]), ts=str(row[0])))
        return candles

    def snapshot(self, inst_id: str) -> MarketSnapshot:
        return MarketSnapshot(symbol=inst_id, ticker=self.ticker(inst_id), candles=self.candles(inst_id), orderbook=self.orderbook(inst_id))
