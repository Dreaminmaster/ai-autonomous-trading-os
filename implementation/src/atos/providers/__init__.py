"""ATOS Providers — AI decision layer backends.

Available providers:
  - MockProvider: deterministic, always available (DEFAULT)
  - OpenAIProvider: GPT-4o via OpenAI API
  - DeepSeekProvider: DeepSeek-V3/R1 via DeepSeek API
  - OpenAICompatibleProvider: any OpenAI-compatible endpoint

  - ProviderManager: manages provider chain with fallback

The old providers.py module is still available for backward compatibility.
New code should use:
  from atos.providers import ProviderManager, MockProvider, ProviderRequest
"""

from atos.providers.base import BaseProvider, ProviderManager, ProviderRequest, ProviderResult
from atos.providers.mock_provider import MockProvider
from atos.providers.openai_provider import OpenAIProvider
from atos.providers.deepseek_provider import DeepSeekProvider
from atos.providers.openai_compatible_provider import OpenAICompatibleProvider

__all__ = [
    "BaseProvider",
    "ProviderManager",
    "ProviderRequest",
    "ProviderResult",
    "MockProvider",
    "OpenAIProvider",
    "DeepSeekProvider",
    "OpenAICompatibleProvider",
]
