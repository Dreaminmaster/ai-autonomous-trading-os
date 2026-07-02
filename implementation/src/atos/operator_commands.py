from __future__ import annotations

from dataclasses import dataclass


@dataclass
class OperatorCommand:
    intent: str
    provider: str | None = None
    mode: str | None = None
    raw: str = ""


def parse_operator_command(text: str) -> OperatorCommand:
    lowered = text.lower().strip()
    if "deepseek" in lowered:
        return OperatorCommand(intent="set_provider", provider="deepseek", raw=text)
    if "anges" in lowered:
        return OperatorCommand(intent="set_provider", provider="anges", raw=text)
    if "mock" in lowered:
        return OperatorCommand(intent="set_provider", provider="mock", raw=text)
    if "paper" in lowered:
        return OperatorCommand(intent="set_mode", mode="paper", raw=text)
    if "shadow" in lowered:
        return OperatorCommand(intent="set_mode", mode="shadow", raw=text)
    return OperatorCommand(intent="none", raw=text)
