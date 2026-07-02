from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Protocol, Any


@dataclass
class BalanceView:
    currency: str
    available: float
    total: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PositionView:
    symbol: str
    side: str
    quantity: float
    average_price: float
    unrealized_pnl: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AccountViewAdapter(Protocol):
    def balances(self) -> list[BalanceView]: ...
    def positions(self) -> list[PositionView]: ...


class EmptyAccountView:
    def balances(self) -> list[BalanceView]:
        return []

    def positions(self) -> list[PositionView]:
        return []
