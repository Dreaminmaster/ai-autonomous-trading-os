"""
Unified Decision Time Context — resolves all time references for RiskEngine.

Callers in backtest pass decision_ts/decision_day via state dict.
In live/dry-run mode (no decision_ts), fall back to wall-clock time.

Usage:
    from atos.time_context import resolve_decision_ts, resolve_decision_day

    ts = resolve_decision_ts(state)      # epoch float
    day = resolve_decision_day(state)    # "YYYY-MM-DD"

All RiskEngine time-dependent rules MUST use these functions.
Never call time.time() or time.strftime() directly inside risk.py.
"""

from __future__ import annotations

import time as _time
from datetime import datetime, timezone
from typing import Any


def resolve_decision_ts(state: dict[str, Any] | None) -> float:
    """Resolve decision timestamp from state, falling back to wall-clock.

    Priority:
      1. state['decision_ts']   (epoch float)
      2. state['candle_ts']     (epoch float)
      3. pandas Timestamp field (state['decision_time'] / state['candle_time'])
      4. time.time()

    Accepts: float, int, pandas.Timestamp, datetime, ISO string, None.
    """
    if not state:
        return _time.time()

    for key in ("decision_ts", "candle_ts"):
        val = state.get(key)
        if val is not None:
            ts = _to_epoch(val)
            if ts is not None:
                return ts

    # Try datetime-like objects
    for key in ("decision_time", "candle_time"):
        val = state.get(key)
        if val is not None:
            ts = _to_epoch(val)
            if ts is not None:
                return ts

    return _time.time()


def resolve_decision_day(state: dict[str, Any] | None) -> str:
    """Resolve decision day from state as 'YYYY-MM-DD'.

    Priority:
      1. state['decision_day']   (explicit)
      2. state['decision_ts'] / state['candle_ts'] → derive date
      3. time.strftime("%Y-%m-%d") (wall-clock)
    """
    if state and "decision_day" in state and state["decision_day"]:
        return str(state["decision_day"])

    ts = resolve_decision_ts(state)
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _to_epoch(val: Any) -> float | None:
    """Convert any time-like value to epoch seconds. Returns None if unparseable."""
    if val is None:
        return None

    # Numeric
    if isinstance(val, (int, float)):
        if val > 1e12:          # milliseconds
            return val / 1000.0
        if val > 1e9:           # seconds
            return float(val)
        return float(val)       # small number → treat as relative, still usable

    # datetime
    if isinstance(val, datetime):
        return val.timestamp()

    # pandas Timestamp (check by duck-typing to avoid import)
    if hasattr(val, "timestamp"):
        try:
            return val.timestamp()
        except Exception:
            pass
    if hasattr(val, "to_pydatetime"):
        try:
            return val.to_pydatetime().timestamp()
        except Exception:
            pass

    # ISO string
    if isinstance(val, str):
        try:
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, TypeError):
            pass

    return None
