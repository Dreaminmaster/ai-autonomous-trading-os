from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from strategy_pool import Candle


@dataclass
class HistoryFrame:
    index: int
    symbol: str
    candles: list[Candle]


class HistoryReplay:
    def __init__(self, data_path: str | Path, symbol: str = 'BTC-USDT', window: int = 50):
        self.data_path = Path(data_path)
        self.symbol = symbol
        self.window = window

    def load(self) -> list[Candle]:
        items: list[Candle] = []
        with self.data_path.open('r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                items.append(Candle(
                    open=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    volume=float(row.get('volume', 0.0)),
                ))
        return items

    def frames(self) -> Iterator[HistoryFrame]:
        items = self.load()
        for idx in range(self.window, len(items) + 1):
            yield HistoryFrame(index=idx, symbol=self.symbol, candles=items[idx - self.window:idx])
