"""
DeepSeek Provider — DeepSeek-V3/R1 decision layer.

DeepSeek API is OpenAI-compatible with base URL: https://api.deepseek.com/v1

Key behaviors:
  1. Uses OpenAI-compatible chat completions protocol
  2. DeepSeek models: deepseek-chat (V3), deepseek-reasoner (R1)
  3. Same structured output constraints as OpenAI
  4. On ANY failure → HOLD
  5. API key from env var DEEPSEEK_API_KEY — never stored or logged

Environment variables:
  DEEPSEEK_API_KEY — required
  DEEPSEEK_MODEL — optional (default: deepseek-chat)
"""

from __future__ import annotations

import json
import logging
import os

from atos.providers.openai_provider import OpenAIProvider, build_messages
from atos.providers.base import ProviderResult, ProviderRequest
from atos.domain import TradeIntent

logger = logging.getLogger(__name__)


class DeepSeekProvider(OpenAIProvider):
    """DeepSeek API provider — inherits from OpenAI provider.

    DeepSeek uses the same OpenAI-compatible API format.
    The only differences are:
      - base_url: https://api.deepseek.com/v1 (or https://api.deepseek.com for beta)
      - models: deepseek-chat, deepseek-reasoner
      - No response_format for deepseek-reasoner (it uses reasoning_content)

    API docs: https://api-docs.deepseek.com/
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "",
        timeout_seconds: float = 60.0,  # DeepSeek can be slower
        name: str = "deepseek",
    ):
        super().__init__(
            api_key=api_key,
            model=model or os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            timeout_seconds=timeout_seconds,
            name=name,
        )
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY", "")

    def _call_api(self, request: ProviderRequest) -> ProviderResult:
        """Override API call to handle DeepSeek-specific response format."""
        import urllib.request
        import urllib.error
        import time

        messages = build_messages(request)
        body = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.0,
            "max_tokens": 1000,
        }

        # DeepSeek reasoner doesn't support response_format
        if "reasoner" not in self.model.lower():
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
                f"DeepSeek HTTP {e.code}: {body_text[:200]}",
                self.name,
                f"HTTP {e.code}",
            )
        except Exception as e:
            return self.safe_hold(request.symbol, f"DeepSeek request failed: {e}", self.name, str(e))

        # Parse response
        try:
            choice = data["choices"][0]["message"]

            # DeepSeek reasoner wraps JSON in reasoning_content; extract it
            content = choice.get("content", "")
            if not content and "reasoning_content" in choice:
                # Try to extract JSON from reasoning
                content = choice["reasoning_content"]

            # Try to find JSON in the content
            intent_dict = self._extract_json(content)

            intent_dict.setdefault("schema_version", "trade_intent.v1")
            intent_dict.setdefault("action", "HOLD")
            intent_dict.setdefault("symbol", request.symbol)
            intent_dict.setdefault("market_type", "paper_spot")
            intent_dict.setdefault("confidence", 0.0)
            intent_dict.setdefault("thesis", "DeepSeek did not provide thesis")
            intent_dict.setdefault("evidence", ["DeepSeek output incomplete"])
            intent_dict.setdefault("selected_strategy_ids", [])
            intent_dict.setdefault("position_size_pct", 0.0)
            intent_dict.setdefault("stop_loss_pct", 0.0)
            intent_dict.setdefault("take_profit_pct", 0.0)
            intent_dict.setdefault("max_holding_minutes", 0)
            intent_dict.setdefault("invalidation_conditions", ["DeepSeek output incomplete"])
            intent_dict.setdefault("risk_notes", "DeepSeek output incomplete — defaulting safe")
            intent_dict.setdefault("metadata", {"provider": self.name, "model": self.model})

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
                f"DeepSeek response unparseable: {e}",
                self.name,
                str(e),
            )

    @staticmethod
    def _extract_json(content: str) -> dict:
        """Extract JSON from potentially markdown-wrapped content.

        DeepSeek reasoner sometimes wraps JSON in ```json blocks.
        """
        if not content or not content.strip():
            return {}

        content = content.strip()

        # Try direct parse
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # Try extracting from ```json ... ``` blocks
        if "```json" in content:
            start = content.index("```json") + 7
            end = content.find("```", start)
            if end > start:
                try:
                    return json.loads(content[start:end].strip())
                except json.JSONDecodeError:
                    pass

        # Try extracting from ``` ... ``` blocks
        if "```" in content:
            start = content.index("```") + 3
            end = content.find("```", start)
            if end > start:
                try:
                    return json.loads(content[start:end].strip())
                except json.JSONDecodeError:
                    pass

        # Try to find first { ... } block
        brace_start = content.find("{")
        if brace_start >= 0:
            brace_end = content.rfind("}")
            if brace_end > brace_start:
                try:
                    return json.loads(content[brace_start:brace_end + 1])
                except json.JSONDecodeError:
                    pass

        return {}
