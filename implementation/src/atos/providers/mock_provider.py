"""
Mock Provider — deterministic test provider that routes StrategyCandidates to TradeIntents.

The mock provider:
  1. Picks the first BUY candidate with confidence >= threshold
  2. Converts it into a TradeIntent
  3. If no BUY candidate, outputs HOLD
  4. Always succeeds (never throws, never times out)
  5. Uses zero tokens

This is the DEFAULT provider and the ultimate FALLBACK.
"""

from __future__ import annotations

from atos.providers.base import BaseProvider, ProviderRequest, ProviderResult
from atos.domain import TradeIntent, make_hold


class MockProvider(BaseProvider):
    """Deterministic mock for testing and fallback.

    Produces BUY signals when a candidate has confidence >= min_confidence.
    Otherwise HOLD.
    """

    def __init__(self, name: str = "mock", min_confidence: float = 0.60):
        super().__init__(name=name, model="mock")
        self.min_confidence = min_confidence

    def decide(self, request: ProviderRequest) -> ProviderResult:
        try:
            # Find the best BUY candidate
            best = None
            for candidate in request.candidates:
                side = candidate.get("side", "HOLD")
                confidence = float(candidate.get("confidence", 0.0))
                if side == "BUY" and confidence >= self.min_confidence:
                    if best is None or confidence > float(best.get("confidence", 0.0)):
                        best = candidate

            if best:
                intent = TradeIntent(
                    schema_version="trade_intent.v1",
                    action="BUY",
                    symbol=request.symbol,
                    market_type="paper_spot",
                    confidence=float(best.get("confidence", 0.60)),
                    thesis=str(best.get("entry_reason", "candidate supports trade")),
                    evidence=[str(best.get("entry_reason", "strategy candidate"))],
                    selected_strategy_ids=[str(best.get("strategy_id", "unknown"))],
                    position_size_pct=5.0,
                    stop_loss_pct=float(best.get("suggested_stop_loss_pct", 1.0)),
                    take_profit_pct=float(best.get("suggested_take_profit_pct", 2.0)),
                    max_holding_minutes=int(best.get("max_holding_minutes", 240)),
                    invalidation_conditions=["candidate invalidated", "risk worsens"],
                    risk_notes="mock provider decision",
                    metadata={"provider": self.name, "selected_strategy": best.get("strategy_id")},
                )
                return ProviderResult(intent=intent, provider_name=self.name, tokens_used=0)

            # No BUY candidate → HOLD
            return ProviderResult(
                intent=make_hold("no valid candidate", symbol=request.symbol),
                provider_name=self.name,
                tokens_used=0,
            )

        except Exception as e:
            return self.safe_hold(request.symbol, f"mock provider error: {e}", self.name, str(e))
