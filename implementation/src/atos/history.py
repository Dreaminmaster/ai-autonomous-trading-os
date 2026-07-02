from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from atos.domain import Candle


@dataclass
class HistoryFrame:
    index: int
    symbol: str
    candles: list[Candle]


class HistoryTimeline:
    def __init__(self, data_path: str | Path, symbol: str = "BTC-USDT", window: int = 50):
        self.data_path = Path(data_path)
        self.symbol = symbol
        self.window = window

    def load(self) -> list[Candle]:
        items: list[Candle] = []
        with self.data_path.open("r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                items.append(Candle(open=float(row["open"]), high=float(row["high"]), low=float(row["low"]), close=float(row["close"]), volume=float(row.get("volume", 0.0)), ts=row.get("ts")))
        return items

    def frames(self) -> Iterator[HistoryFrame]:
        items = self.load()
        for idx in range(self.window, len(items) + 1):
            yield HistoryFrame(index=idx, symbol=self.symbol, candles=items[idx - self.window:idx])


class MetricsEngine:
    def summarize(self, pnl_values: list[float], fees_paid: float = 0.0) -> dict:
        wins = len([x for x in pnl_values if x > 0])
        losses = len([x for x in pnl_values if x < 0])
        equity = 0.0
        peak = 0.0
        max_dd = 0.0
        for pnl in pnl_values:
            equity += pnl
            peak = max(peak, equity)
            max_dd = min(max_dd, equity - peak)
        return {"trades": len(pnl_values), "wins": wins, "losses": losses, "total_pnl_pct": sum(pnl_values), "max_drawdown_pct": abs(max_dd), "fees_paid": fees_paid}
