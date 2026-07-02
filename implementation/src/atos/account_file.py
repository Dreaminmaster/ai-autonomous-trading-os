from __future__ import annotations

import json
from pathlib import Path

from atos.account_view import BalanceView, PositionView


class FileAccountView:
    def __init__(self, path: str = "runtime/account_view.json"):
        self.path = Path(path)

    def _load(self) -> dict:
        if not self.path.exists():
            return {"balances": [], "positions": []}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def balances(self) -> list[BalanceView]:
        data = self._load().get("balances", [])
        return [BalanceView(currency=x.get("currency", ""), available=float(x.get("available", 0.0)), total=float(x.get("total", 0.0))) for x in data]

    def positions(self) -> list[PositionView]:
        data = self._load().get("positions", [])
        return [PositionView(symbol=x.get("symbol", ""), side=x.get("side", ""), quantity=float(x.get("quantity", 0.0)), average_price=float(x.get("average_price", 0.0)), unrealized_pnl=float(x.get("unrealized_pnl", 0.0))) for x in data]
