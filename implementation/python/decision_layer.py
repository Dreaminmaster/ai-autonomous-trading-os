from __future__ import annotations

from models import TradeIntent, hold_intent


class MockDecisionLayer:
    """Deterministic decision layer for local execution and tests.

    Real model providers should implement the same interface and return only
    schema-compatible TradeIntent objects.
    """

    def decide(self, symbol: str, candidates: list[dict]) -> TradeIntent:
        for candidate in candidates:
            if candidate.get('side') == 'BUY' and candidate.get('confidence', 0) >= 0.60:
                return TradeIntent(
                    schema_version='trade_intent.v1',
                    action='BUY',
                    symbol=symbol,
                    market_type='paper_spot',
                    confidence=float(candidate['confidence']),
                    thesis=candidate.get('entry_reason', 'candidate strategy supports trade'),
                    evidence=[candidate.get('entry_reason', 'strategy candidate')],
                    selected_strategy_ids=[candidate.get('strategy_id', 'unknown')],
                    position_size_pct=0.5,
                    stop_loss_pct=float(candidate.get('suggested_stop_loss_pct', 1.0)),
                    take_profit_pct=float(candidate.get('suggested_take_profit_pct', 2.0)),
                    max_holding_minutes=int(candidate.get('max_holding_minutes', 240)),
                    invalidation_conditions=['candidate no longer valid', 'risk state worsens'],
                    risk_notes='mock decision, paper mode',
                    metadata={'provider': 'mock'},
                )
        return hold_intent('no acceptable candidate', symbol=symbol)
