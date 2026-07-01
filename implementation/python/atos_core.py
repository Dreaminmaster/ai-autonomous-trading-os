from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from datetime import datetime, timezone
import uuid


class RunMode(StrEnum):
    DESIGN = 'design'
    BACKTEST = 'backtest'
    PAPER = 'paper'
    SHADOW = 'shadow'
    LIVE = 'live'


class Action(StrEnum):
    BUY = 'BUY'
    SELL = 'SELL'
    REDUCE = 'REDUCE'
    CLOSE = 'CLOSE'
    HOLD = 'HOLD'


@dataclass(frozen=True)
class SystemState:
    mode: RunMode = RunMode.PAPER
    kill_switch_active: bool = False
    live_enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f'{prefix}_{uuid.uuid4().hex[:16]}'
