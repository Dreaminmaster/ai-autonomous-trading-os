"""
OpenAI-Compatible Provider — generic adapter for any OpenAI-compatible API.

Works with:
  - Anges AI (https://api.anges.ai/v1)
  - Together AI
  - Anyscale
  - Perplexity
  - Local LLM endpoints (Ollama, vLLM, llama.cpp server)
  - Any other /v1/chat/completions endpoint

Usage:
  provider = OpenAICompatibleProvider(
      name="anges",
      api_key="$ANGES_API_KEY",
      base_url="https://api.anges.ai/v1",
      model="anges-gpt-4o",
  )

Environment variables:
  {NAME}_API_KEY — API key for this provider
  {NAME}_BASE_URL — base URL for this provider
  {NAME}_MODEL — model name
"""

from __future__ import annotations

import json
import logging
import os
import time

from atos.providers.base import BaseProvider, ProviderRequest, ProviderResult
from atos.providers.openai_provider import build_messages
from atos.domain import TradeIntent

logger = logging.getLogger(__name__)


class OpenAICompatibleProvider(BaseProvider):
    """Generic OpenAI-compatible API provider.

    Configured via name prefix for env var discovery:
      name="anges" → ANGE_API_KEY, ANGE_BASE_URL, ANGE_MODEL

    Falls back to: name="anges" → ANGES_API_KEY, etc.
    """

    def __init__(
        self,
        name: str,
        api_key: str = "",
        base_url: str = "",
        model: str = "",
        timeout_seconds: float = 30.0,
    ):
        super().__init__(name=name, model=model, timeout_seconds=timeout_seconds)

        # Env var prefix: uppercase name + _
        prefix = name.upper().replace("-", "_")

        self.api_key = api_key or os.environ.get(f"{prefix}_API_KEY", "")
        self.base_url = base_url or os.environ.get(f"{prefix}_BASE_URL", "")

        if not self.model:
            self.model = os.environ.get(f"{prefix}_MODEL", "gpt-4o")

    def decide(self, request: ProviderRequest) -> ProviderResult:
        if not self.api_key:
            return self.safe_hold(
                request.symbol,
                f"API key not configured for provider '{self.name}' (set {self.name.upper()}_API_KEY)",
                self.name,
                "missing_api_key",
            )

        if not self.base_url:
            return self.safe_hold(
                request.symbol,
                f"Base URL not configured for provider '{self.name}'",
                self.name,
                "missing_base_url",
            )

        try:
            return self._call_api(request)
        except Exception as e:
            logger.error(f"{self.name} provider error: {e}", exc_info=True)
            return self.safe_hold(request.symbol, f"{self.name} error: {e}", self.name, str(e))

    def _call_api(self, request: ProviderRequest) -> ProviderResult:
        import urllib.request
        import urllib.error

        messages = build_messages(request)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 1000,
        }

        # Try response_format, but not all providers support it
        body["response_format"] = {"type": "json_object"}

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )

        t0 = time.monotonic()

        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency = (time.monotonic() - t0) * 1000
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            return self.safe_hold(
                request.symbol,
                f"{self.name} HTTP {e.code}: {body_text[:200]}",
                self.name,
                f"HTTP {e.code}",
            )
        except Exception as e:
            return self.safe_hold(request.symbol, f"{self.name} request failed: {e}", self.name, str(e))

        try:
            content = data["choices"][0]["message"]["content"]
            intent_dict = json.loads(content)

            # Fill defaults
            defaults = {
                "schema_version": "trade_intent.v1",
                "action": "HOLD",
                "symbol": request.symbol,
                "market_type": "paper_spot",
                "confidence": 0.0,
                "thesis": f"{self.name} did not provide thesis",
                "evidence": [f"{self.name} output incomplete"],
                "selected_strategy_ids": [],
                "position_size_pct": 0.0,
                "stop_loss_pct": 0.0,
                "take_profit_pct": 0.0,
                "max_holding_minutes": 0,
                "invalidation_conditions": [f"{self.name} output incomplete"],
                "risk_notes": f"{self.name} output incomplete — defaulting safe",
                "metadata": {"provider": self.name, "model": self.model},
            }
            for k, v in defaults.items():
                intent_dict.setdefault(k, v)

            tokens_used = data.get("usage", {}).get("total_tokens", 0)

            return ProviderResult(
                intent=TradeIntent.from_dict(intent_dict),
                provider_name=self.name,
                latency_ms=latency,
                tokens_used=tokens_used,
            )

        except (KeyError, json.JSONDecodeError, TypeError) as e:
            return self.safe_hold(
                request.symbol,
                f"{self.name} response unparseable: {e}",
                self.name,
                str(e),
            )
