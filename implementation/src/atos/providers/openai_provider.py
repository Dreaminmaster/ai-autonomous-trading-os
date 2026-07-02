"""
OpenAI Provider — GPT-4/Codex decision layer.

Uses the OpenAI Chat Completions API to generate structured trade decisions.

Key behaviors:
  1. Sends strategy candidates + market context as system/user messages
  2. Requests structured JSON output (TradeIntent format)
  3. Validates the response against schema before returning
  4. On ANY failure (timeout, bad JSON, rate limit) → HOLD
  5. API key from env var OPENAI_API_KEY — never stored or logged
  6. Temperature 0.0 to reduce randomness

Environment variables:
  OPENAI_API_KEY — required
  OPENAI_BASE_URL — optional (default: https://api.openai.com/v1)
  OPENAI_MODEL — optional (default: gpt-4o)
"""

from __future__ import annotations

import json
import logging
import os
import time

from atos.providers.base import BaseProvider, ProviderRequest, ProviderResult
from atos.domain import TradeIntent, make_hold

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────
# Prompt Template
# ─────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an AI trading assistant operating within a deterministic risk-controlled system.

Your role: analyze market context and strategy candidates, then output a structured trade decision.

RULES:
1. Output ONLY valid JSON matching the TradeIntent schema — no other text.
2. BUY requires strong evidence from at least one strategy candidate.
3. If no candidate has clear evidence, output HOLD.
4. Confidence must be between 0.0 and 1.0.
5. Include a clear thesis explaining WHY you chose this action.
6. Risk notes must mention potential downsides.
7. If uncertain, HOLD is the correct action.

YOU CANNOT place orders. You only provide structured intent that goes through risk checks."""


def build_messages(request: ProviderRequest) -> list[dict]:
    """Build OpenAI Chat Completions messages from request context."""
    candidates_text = json.dumps(request.candidates, indent=2, ensure_ascii=False)
    market_text = json.dumps(request.market_state, indent=2, ensure_ascii=False)

    user_message = f"""Symbol: {request.symbol}
Timeframe: 5m
Current mode: {request.risk_state.get('mode', 'paper')}

Market State:
{market_text}

Strategy Candidates:
{candidates_text}

Based on the above, output a structured TradeIntent JSON.
Follow the schema exactly:
- schema_version: "trade_intent.v1"
- action: "BUY" | "SELL" | "REDUCE" | "CLOSE" | "HOLD"
- symbol: "{request.symbol}"
- market_type: "paper_spot"
- confidence: 0.0-1.0
- thesis: string (min 10 chars)
- evidence: [string, ...] (at least 1 item)
- selected_strategy_ids: [string, ...]
- position_size_pct: 1.0-10.0
- stop_loss_pct: 0.5-5.0
- take_profit_pct: 1.0-10.0
- max_holding_minutes: 0-600
- invalidation_conditions: [string, ...] (at least 1 item)
- risk_notes: string
- metadata: {{}}

Remember: if the evidence is weak, HOLD is the correct response."""

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


# ─────────────────────────────────────────────────────────────────────
# OpenAI Provider Implementation
# ─────────────────────────────────────────────────────────────────────

class OpenAIProvider(BaseProvider):
    """OpenAI API provider for AI trading decisions.

    Uses standard /v1/chat/completions endpoint.
    Compatible with Azure OpenAI and any OpenAI-compatible proxy.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "",
        base_url: str = "",
        timeout_seconds: float = 30.0,
        name: str = "openai",
    ):
        super().__init__(name=name, model=model or os.environ.get("OPENAI_MODEL", "gpt-4o"), timeout_seconds=timeout_seconds)
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self.base_url = base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")

    def decide(self, request: ProviderRequest) -> ProviderResult:
        if not self.api_key:
            return self.safe_hold(
                request.symbol,
                "OpenAI API key not configured (set OPENAI_API_KEY)",
                self.name,
                "missing_api_key",
            )

        try:
            return self._call_api(request)
        except Exception as e:
            logger.error(f"OpenAI provider error: {e}", exc_info=True)
            return self.safe_hold(request.symbol, f"OpenAI error: {e}", self.name, str(e))

    def _call_api(self, request: ProviderRequest) -> ProviderResult:
        """Make the actual API call to OpenAI."""
        # Lazy import urllib to keep module importable without network
        import urllib.request
        import urllib.error

        messages = build_messages(request)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 1000,
            "response_format": {"type": "json_object"},
        }

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
                f"OpenAI HTTP {e.code}: {body_text[:200]}",
                self.name,
                f"HTTP {e.code}",
            )
        except Exception as e:
            return self.safe_hold(request.symbol, f"OpenAI request failed: {e}", self.name, str(e))

        # Parse AI response
        try:
            content = data["choices"][0]["message"]["content"]
            intent_dict = json.loads(content)

            # Ensure required fields exist
            intent_dict.setdefault("schema_version", "trade_intent.v1")
            intent_dict.setdefault("action", "HOLD")
            intent_dict.setdefault("symbol", request.symbol)
            intent_dict.setdefault("market_type", "paper_spot")
            intent_dict.setdefault("confidence", 0.0)
            intent_dict.setdefault("thesis", "AI did not provide thesis")
            intent_dict.setdefault("evidence", ["AI output incomplete"])
            intent_dict.setdefault("selected_strategy_ids", [])
            intent_dict.setdefault("position_size_pct", 0.0)
            intent_dict.setdefault("stop_loss_pct", 0.0)
            intent_dict.setdefault("take_profit_pct", 0.0)
            intent_dict.setdefault("max_holding_minutes", 0)
            intent_dict.setdefault("invalidation_conditions", ["AI output incomplete"])
            intent_dict.setdefault("risk_notes", "AI output incomplete — defaulting safe")
            intent_dict.setdefault("metadata", {"provider": self.name})

            tokens_used = data.get("usage", {}).get("total_tokens", 0)

            intent = TradeIntent.from_dict(intent_dict)
            return ProviderResult(
                intent=intent,
                provider_name=self.name,
                latency_ms=latency,
                tokens_used=tokens_used,
            )

        except (KeyError, json.JSONDecodeError, TypeError) as e:
            return self.safe_hold(
                request.symbol,
                f"OpenAI response unparseable: {e}",
                self.name,
                str(e),
            )
