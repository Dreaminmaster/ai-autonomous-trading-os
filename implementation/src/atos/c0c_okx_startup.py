"""Exchange-reproducible startup-candle contract for C0C on OKX 5m data."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

OKX_5M_MAX_STARTUP_CANDLES = 1499
OKX_STARTUP_ANALYSIS: dict[str, Any] = {
    "pairs": ["BTC/USDT", "ETH/USDT", "SOL/USDT"],
    "timerange": "20240101-20240201",
    "startup_candidates": [499, 999, 1499],
    "selected_startup_candles": OKX_5M_MAX_STARTUP_CANDLES,
    "max_variance_pct": 0.10,
    "required_indicators": [
        "ema_fast_20",
        "ema_slow_50",
        "ema_spread",
        "slow_slope_12",
        "atr_ratio_14",
        "close_1h",
        "htf_ema_100_1h",
        "htf_slope_6_1h",
    ],
}


def apply_okx_startup_contract() -> None:
    """Bind C0C to the maximum startup count reproducible from OKX 5m API data.

    The original preregistration selected 1999 candles before the authoritative
    run exposed OKX/Freqtrade's hard 1499-candle ceiling. The failed run stopped
    before recursive evidence, Hyperopt, validation, or development-test reads.
    This correction is therefore prospective and keeps the holdout closed.
    """
    from . import c0c_walk_forward as c0c

    current = getattr(c0c, "STARTUP_CANDLE_COUNT", None)
    if current not in {1999, OKX_5M_MAX_STARTUP_CANDLES}:
        raise RuntimeError(f"unexpected C0C startup contract before OKX binding: {current!r}")
    c0c.STARTUP_CANDLE_COUNT = OKX_5M_MAX_STARTUP_CANDLES
    c0c.STARTUP_ANALYSIS = deepcopy(OKX_STARTUP_ANALYSIS)
