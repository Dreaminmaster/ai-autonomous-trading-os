"""
Test: cooldown must use candle time, NOT wall-clock time, during backtest.

P0: When decision_ts is provided in state, duplicate cooldown should use
    that timestamp, not time.time().
    
P1: When NOT provided, fall back to time.time() for live/dry-run.
"""

import time
import pytest
from atos.risk import RiskEngine


POLICY = {
    "mode": "paper",
    "allowed_symbols": ["BTC/USDT"],
    "position_limits": {"max_position_pct_per_trade": 10.0},
    "ai_output_limits": {"min_confidence_for_trade": 0.60},
    "trade_limits": {"max_trades_per_day": 100, "cooldown_seconds": 300},
}


def _buy_intent():
    return {
        "schema_version": "trade_intent.v1",
        "action": "BUY",
        "symbol": "BTC/USDT",
        "market_type": "paper_spot",
        "confidence": 0.72,
        "thesis": "Strong trend up",
        "evidence": ["fast MA > slow MA"],
        "selected_strategy_ids": ["trend_following_v1"],
        "position_size_pct": 5.0,
        "stop_loss_pct": 1.5,
        "take_profit_pct": 3.0,
        "max_holding_minutes": 240,
        "invalidation_conditions": ["price drops"],
        "risk_notes": "test",
    }


def test_backtest_5min_candles_not_rejected_by_cooldown():
    """5-minute-spaced candles should NOT all be rejected by 300s cooldown.

    Simulates 5 candles at 5-min intervals in backtest time.
    Each should be APPROVED because they are 300s apart.
    """
    risk = RiskEngine(POLICY)

    # Base time: a specific epoch (2025-06-01 00:00:00)
    base_ts = 1717200000.0
    interval = 300  # 5 minutes = 300 seconds

    for i in range(5):
        candle_ts = base_ts + i * interval
        state = {"mode": "paper", "decision_ts": candle_ts, "candle_ts": candle_ts}
        result = risk.evaluate(_buy_intent(), state)

        if i == 0:
            assert result.decision == "APPROVED", f"Candle 0 (ts={candle_ts}) rejected: {result.reasons}"
        else:
            # Each candle is exactly 300s after the previous — right at the boundary.
            # Freqtrade gives us discrete candle timestamps; 300s apart > 300s cooldown
            # (the check is strictly < not <=), so they SHOULD be approved.
            # If they are rejected due to cooldown, the boundary check is wrong.
            assert result.decision == "APPROVED", (
                f"Candle {i} (ts={candle_ts}, delta={interval}s) rejected: {result.reasons}. "
                f"Cooldown should allow candles spaced exactly at the boundary."
            )


def test_same_candle_rejected_by_cooldown():
    """Two BUYs at the exact same candle time must be rejected by cooldown."""
    risk = RiskEngine(POLICY)
    same_ts = 1717200000.0

    # First one approved
    r1 = risk.evaluate(_buy_intent(), {"mode": "paper", "decision_ts": same_ts})
    assert r1.decision == "APPROVED"

    # Second one at same time → cooldown
    r2 = risk.evaluate(_buy_intent(), {"mode": "paper", "decision_ts": same_ts})
    assert r2.decision == "REJECTED"
    assert any("duplicate" in reason for reason in r2.reasons)


def test_live_no_decision_ts_falls_back_to_wall_clock():
    """Without decision_ts in state, use time.time() for live/dry-run compatibility."""
    risk = RiskEngine(POLICY)
    # No decision_ts at all
    result = risk.evaluate(_buy_intent(), {"mode": "paper"})
    assert result.decision == "APPROVED"  # First trade always approved


def test_very_old_then_recent_candle_not_rejected():
    """A signal at t=0 and a signal at t=+1hour should not be rejected."""
    risk = RiskEngine(POLICY)

    # Old trade at t=0
    risk.evaluate(_buy_intent(), {"mode": "paper", "decision_ts": 0.0})

    # New trade at t=3600 (1 hour later)
    result = risk.evaluate(_buy_intent(), {"mode": "paper", "decision_ts": 3600.0})
    assert result.decision == "APPROVED", f"Rejected: {result.reasons}"
