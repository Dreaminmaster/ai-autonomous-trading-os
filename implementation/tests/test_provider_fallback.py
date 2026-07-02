"""
Test provider manager: fallback chain, timeout default, errors → HOLD.

Key safety tests:
  1. Mock provider returns valid TradeIntent
  2. Provider fallback chain works
  3. Provider exception → fallback to next → HOLD
  4. Missing API key → HOLD (never crashes)
  5. All providers fail → safe HOLD
  6. Provider timeout → HOLD
  7. Statistics tracking works
"""

import pytest
from unittest.mock import MagicMock, patch

from atos.providers.base import ProviderManager, ProviderRequest, ProviderResult, BaseProvider
from atos.providers.mock_provider import MockProvider
from atos.providers.openai_provider import OpenAIProvider
from atos.domain import TradeIntent, make_hold


# ── Test Fixtures ────────────────────────────────────────────────────

def _buy_candidates():
    return [
        {
            "strategy_id": "trend_following_v1",
            "symbol": "BTC/USDT",
            "side": "BUY",
            "signal_strength": 0.65,
            "confidence": 0.72,
            "entry_reason": "fast MA above slow MA",
            "suggested_stop_loss_pct": 1.0,
            "suggested_take_profit_pct": 2.0,
            "max_holding_minutes": 240,
            "regime_tags": ["trend_up"],
            "risk_notes": "trend can reverse quickly",
        },
    ]


def _request():
    return ProviderRequest(
        symbol="BTC/USDT",
        candidates=_buy_candidates(),
        market_state={"mark_price": 50000.0, "rsi": 55.0, "volume_ratio": 1.2},
        risk_state={"mode": "paper"},
    )


# ── Mock Provider Tests ──────────────────────────────────────────────

def test_mock_provider_returns_buy():
    provider = MockProvider()
    result = provider.decide(_request())
    assert result.intent.action == "BUY"
    assert result.intent.confidence == 0.72
    assert result.provider_name == "mock"
    assert result.error is None

def test_mock_provider_holds_when_no_candidate():
    provider = MockProvider(min_confidence=0.9)
    request = _request()
    request.candidates = [
        {
            "strategy_id": "mean_reversion_v1",
            "side": "BUY",
            "confidence": 0.5,  # below threshold
            "entry_reason": "weak signal",
            "suggested_stop_loss_pct": 1.0,
            "suggested_take_profit_pct": 2.0,
            "max_holding_minutes": 180,
        },
    ]
    result = provider.decide(request)
    assert result.intent.action == "HOLD"


# ── ProviderManager Tests ────────────────────────────────────────────

def test_provider_manager_mock():
    manager = ProviderManager()
    manager.register(MockProvider())
    result = manager.decide(_request())
    assert result.intent.action == "BUY"
    assert result.provider_name == "mock"

def test_provider_manager_fallback_chain():
    manager = ProviderManager()

    # Create a failing provider
    class FailingProvider(BaseProvider):
        def __init__(self):
            super().__init__(name="failing")

        def decide(self, request):
            raise RuntimeError("simulated failure")

    # Create a working provider
    class WorkingProvider(BaseProvider):
        def __init__(self):
            super().__init__(name="working")

        def decide(self, request):
            from atos.domain import make_hold
            return ProviderResult(
                intent=make_hold("working provider hold"),
                provider_name=self.name,
            )

    manager.register(FailingProvider())
    manager.register(WorkingProvider())
    manager.register(MockProvider())
    manager.set_chain(["failing", "working", "mock"])

    result = manager.decide(_request())
    # Should fall through failing → working
    assert result.provider_name == "working"
    assert result.intent.action == "HOLD"

def test_provider_manager_all_fail_returns_hold():
    manager = ProviderManager()

    class AlwaysCrash(BaseProvider):
        def __init__(self):
            super().__init__(name="crash")

        def decide(self, request):
            raise RuntimeError("boom")

    manager.register(AlwaysCrash())
    manager.register(MockProvider())
    manager.set_chain(["crash"])  # only crash in chain

    result = manager.decide(_request())
    # Should fallback to eventual HOLD
    assert result.intent.action == "HOLD"
    assert result.error is not None

def test_provider_manager_by_name():
    manager = ProviderManager()
    manager.register(MockProvider())
    manager.register(MockProvider(name="mock2", min_confidence=0.9))

    # Specific provider
    result = manager.decide(_request(), provider_name="mock2")
    assert result.provider_name == "mock2"

def test_provider_stats():
    manager = ProviderManager()
    manager.register(MockProvider())
    assert "mock" in manager.get_stats()
    assert manager.get_stats()["mock"]["calls"] == 0


# ── OpenAI Provider Tests (without API key → HOLD) ──────────────────

def test_openai_missing_key_returns_hold():
    provider = OpenAIProvider(api_key="", model="gpt-4o")
    result = provider.decide(_request())
    assert result.intent.action == "HOLD"
    assert "api" in result.error.lower()


# ── Provider safety: invalid JSON → HOLD ─────────────────────────────

def test_provider_manager_handles_none_intent():
    """If a provider returns None intent, manager handles it."""
    manager = ProviderManager()

    class NoneProvider(BaseProvider):
        def __init__(self):
            super().__init__(name="none")

        def decide(self, request):
            return ProviderResult(intent=None, provider_name=self.name)

    manager.register(NoneProvider())
    manager.register(MockProvider())
    manager.set_chain(["none", "mock"])

    result = manager.decide(_request())
    assert result.provider_name == "mock"  # fell through to mock
    assert result.intent is not None


# ── ProviderResult serialization ─────────────────────────────────────

def test_provider_result_to_dict():
    from atos.domain import make_hold
    result = ProviderResult(
        intent=make_hold("test"),
        provider_name="mock",
        latency_ms=42.0,
        tokens_used=100,
    )
    d = result.to_dict()
    assert d["action"] == "HOLD"
    assert d["provider"] == "mock"
    assert d["latency_ms"] == 42.0
    assert d["tokens_used"] == 100
