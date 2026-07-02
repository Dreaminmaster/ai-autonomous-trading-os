from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from atos.domain import TradeIntent, make_hold


@dataclass
class ProviderRequest:
    symbol: str
    candidates: list[dict]
    market_state: dict
    risk_state: dict


class DecisionProvider(Protocol):
    name: str
    def decide(self, request: ProviderRequest) -> TradeIntent: ...


class MockProvider:
    name = "mock"

    def decide(self, request: ProviderRequest) -> TradeIntent:
        for candidate in request.candidates:
            if candidate.get("side") == "BUY" and float(candidate.get("confidence", 0.0)) >= 0.60:
                return TradeIntent(
                    schema_version="trade_intent.v1",
                    action="BUY",
                    symbol=request.symbol,
                    market_type="paper_spot",
                    confidence=float(candidate["confidence"]),
                    thesis=candidate.get("entry_reason", "candidate supports trade"),
                    evidence=[candidate.get("entry_reason", "strategy candidate")],
                    selected_strategy_ids=[candidate.get("strategy_id", "unknown")],
                    position_size_pct=0.5,
                    stop_loss_pct=float(candidate.get("suggested_stop_loss_pct", 1.0)),
                    take_profit_pct=float(candidate.get("suggested_take_profit_pct", 2.0)),
                    max_holding_minutes=int(candidate.get("max_holding_minutes", 240)),
                    invalidation_conditions=["candidate invalidated", "risk worsens"],
                    risk_notes="mock provider decision",
                    metadata={"provider": self.name},
                )
        return make_hold("provider found no valid candidate", symbol=request.symbol)


class ProviderManager:
    def __init__(self, default_provider: str = "mock"):
        self.providers: dict[str, DecisionProvider] = {"mock": MockProvider()}
        self.default_provider = default_provider

    def register(self, provider: DecisionProvider) -> None:
        self.providers[provider.name] = provider

    def choose(self, name: str | None = None) -> DecisionProvider:
        selected = name or self.default_provider
        return self.providers.get(selected, self.providers["mock"])

    def decide(self, request: ProviderRequest, provider_name: str | None = None) -> TradeIntent:
        try:
            return self.choose(provider_name).decide(request)
        except Exception as exc:
            return make_hold(f"provider failure: {exc}", symbol=request.symbol)
