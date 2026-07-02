"""
Provider Base — abstract interface and shared types for all AI providers.

Every provider:
  1. Accepts a ProviderRequest (candidates, market state, risk context)
  2. Returns a TradeIntent (structured decision)
  3. NEVER places orders directly
  4. On failure → HOLD
  5. MUST NOT access API keys (keys are read at init, never exposed)

The ProviderManager:
  - Holds multiple providers
  - Supports fallback chain: try provider A, fallback to B, default to mock
  - Provider failure → next provider in chain → eventually HOLD
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from atos.domain import TradeIntent, make_hold

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# Shared Types
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ProviderRequest:
    """Request sent to AI provider for a trading decision.

    Contains all context the AI needs to make an informed decision,
    but NO API keys, NO account balances, NO exchange credentials.
    """

    symbol: str
    candidates: list[dict[str, Any]]  # list of StrategyCandidate.to_dict()
    market_state: dict[str, Any]  # current mark_price, RSI, volume_ratio, etc.
    risk_state: dict[str, Any]  # current mode, active positions count, etc.
    recent_review_summary: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderResult:
    """Result from a provider call.

    intent: the TradeIntent (HOLD on failure)
    provider_name: name of the provider that produced this result
    latency_ms: response time
    error: error message if call failed
    tokens_used: estimated token count (for cost tracking)
    """

    intent: TradeIntent
    provider_name: str
    latency_ms: float = 0.0
    error: str | None = None
    tokens_used: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.intent.action,
            "confidence": self.intent.confidence,
            "provider": self.provider_name,
            "latency_ms": self.latency_ms,
            "error": self.error,
            "tokens_used": self.tokens_used,
        }


# ─────────────────────────────────────────────────────────────────────
# Base Provider Interface
# ─────────────────────────────────────────────────────────────────────

class BaseProvider(ABC):
    """Abstract base for all AI decision providers.

    Subclasses:
      - MockProvider (deterministic, for testing)
      - OpenAIProvider (GPT-4/Codex)
      - DeepSeekProvider (DeepSeek-V3)
      - OpenAICompatibleProvider (any OpenAI-compatible endpoint, e.g. Anges)
    """

    def __init__(self, name: str, model: str = "", timeout_seconds: float = 30.0):
        self.name = name
        self.model = model
        self.timeout_seconds = timeout_seconds

    @abstractmethod
    def decide(self, request: ProviderRequest) -> ProviderResult:
        """Make a trading decision.

        Returns ProviderResult with intent=HOLD on any failure.
        Must NOT throw — catch all exceptions internally.
        """
        ...

    @staticmethod
    def safe_hold(symbol: str, reason: str, provider_name: str, error: str | None = None) -> ProviderResult:
        """Create a safe HOLD result."""
        return ProviderResult(
            intent=make_hold(reason, symbol=symbol),
            provider_name=provider_name,
            error=error,
        )


# ─────────────────────────────────────────────────────────────────────
# Provider Manager (with fallback chain)
# ─────────────────────────────────────────────────────────────────────

class ProviderManager:
    """Manages multiple AI providers with fallback chain.

    Usage:
        manager = ProviderManager()
        manager.register(MockProvider())
        manager.register(DeepSeekProvider(api_key=..., model="deepseek-chat"))
        manager.set_chain(["deepseek", "openai", "mock"])

        result = manager.decide(request)
        # If deepseek fails → tries openai → falls back to mock
    """

    def __init__(self, default_provider: str = "mock"):
        self.providers: dict[str, BaseProvider] = {}
        self.chain: list[str] = []
        self.stats: dict[str, dict[str, Any]] = {}
        # Always register MockProvider as the ultimate fallback
        from atos.providers.mock_provider import MockProvider
        self.register(MockProvider())
        self.set_chain([default_provider, "mock"])

    def register(self, provider: BaseProvider) -> None:
        """Register a provider by name."""
        self.providers[provider.name] = provider
        self.stats[provider.name] = {"calls": 0, "failures": 0, "total_latency_ms": 0.0}

    def set_chain(self, chain: list[str]) -> None:
        """Set the fallback chain order (e.g. ['deepseek', 'openai', 'mock'])."""
        self.chain = [name for name in chain if name in self.providers]
        if not self.chain:
            self.chain = ["mock"]

    def choose(self, name: str | None = None) -> BaseProvider | None:
        """Choose a specific provider by name."""
        if name and name in self.providers:
            return self.providers[name]
        for name in self.chain:
            if name in self.providers:
                return self.providers[name]
        return self.providers.get("mock")

    def decide(self, request: ProviderRequest, provider_name: str | None = None) -> ProviderResult:
        """Make a decision, trying each provider in the chain until success.

        On ALL failures: returns HOLD.
        """
        import time

        providers_to_try = [provider_name] if provider_name else self.chain

        last_result: ProviderResult | None = None
        errors: list[str] = []

        for name in providers_to_try:
            provider = self.providers.get(name)
            if not provider:
                continue

            try:
                t0 = time.monotonic()
                result = provider.decide(request)
                latency = (time.monotonic() - t0) * 1000

                self.stats[name]["calls"] += 1
                self.stats[name]["total_latency_ms"] += latency

                if result.error:
                    self.stats[name]["failures"] += 1
                    errors.append(f"{name}: {result.error}")
                    last_result = result
                    logger.warning(f"Provider {name} failed: {result.error}, trying next...")
                    continue

                # Success — ensure it's not None
                if result.intent is None:
                    errors.append(f"{name}: returned None intent")
                    self.stats[name]["failures"] += 1
                    continue

                result.latency_ms = latency
                return result

            except Exception as e:
                self.stats[name]["failures"] += 1
                errors.append(f"{name}: {e}")
                logger.error(f"Provider {name} crashed: {e}", exc_info=True)

        # All providers failed — safe HOLD
        reason = f"all providers failed: {'; '.join(errors)}" if errors else "no provider available"
        logger.error(f"ProviderManager: {reason}")
        return BaseProvider.safe_hold(
            symbol=request.symbol,
            reason=reason,
            provider_name="fallback",
            error=reason,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get provider usage statistics."""
        result = {}
        for name, stats in self.stats.items():
            result[name] = {
                **stats,
                "avg_latency_ms": stats["total_latency_ms"] / max(stats["calls"], 1),
            }
        return result
