"""Tests: no lookahead bias — strategy must not use future data."""

import sys
from pathlib import Path
import pytest

_atos_dir = Path(__file__).resolve().parents[1] / "src"
if str(_atos_dir) not in sys.path:
    sys.path.insert(0, str(_atos_dir))

from atos.risk import RiskEngine

# Check Freqtrade availability
try:
    import freqtrade
    import pandas as pd
    import numpy as np
    FREQTRADE_AVAILABLE = True
except ImportError:
    FREQTRADE_AVAILABLE = False


def test_risk_engine_is_fresh_each_call():
    """RiskEngine state should NOT persist across calls (no daily_trade carryover)."""
    policy = {
        "mode": "paper",
        "allowed_symbols": ["BTC/USDT"],
        "position_limits": {"max_position_pct_per_trade": 10.0},
        "ai_output_limits": {"min_confidence_for_trade": 0.60},
        "trade_limits": {"max_trades_per_day": 5, "cooldown_seconds": 0},
    }

    buy = {
        "schema_version": "trade_intent.v1",
        "action": "BUY",
        "symbol": "BTC/USDT",
        "market_type": "paper_spot",
        "confidence": 0.72,
        "thesis": "Test trade",
        "evidence": ["test signal"],
        "selected_strategy_ids": ["test_v1"],
        "position_size_pct": 5.0,
        "stop_loss_pct": 1.0,
        "take_profit_pct": 2.0,
        "max_holding_minutes": 60,
        "invalidation_conditions": ["test"],
        "risk_notes": "test",
    }

    # Engine 1: approve 6 trades (hits 5/day limit)
    r1 = RiskEngine(policy)
    for i in range(6):
        r = r1.evaluate(buy, {"mode": "paper", "decision_ts": 1000.0 + i * 10, "decision_day": "2025-01-01"})
        if i == 5:
            assert r.decision == "REJECTED"  # 6th exceeds daily limit

    # Engine 2 (fresh): should approve trades again
    r2 = RiskEngine(policy)
    r = r2.evaluate(buy, {"mode": "paper", "decision_ts": 2000.0, "decision_day": "2025-01-02"})
    assert r.decision == "APPROVED", f"Fresh engine rejected: {r.reasons}"


def test_backtest_risk_engine_reset_clears_state():
    """Two RiskEngine instances must have independent daily_trades."""
    policy = {
        "mode": "paper",
        "allowed_symbols": ["BTC/USDT"],
        "position_limits": {"max_position_pct_per_trade": 10.0},
        "ai_output_limits": {"min_confidence_for_trade": 0.60},
        "trade_limits": {"max_trades_per_day": 3, "cooldown_seconds": 0},
    }

    buy = {
        "schema_version": "trade_intent.v1",
        "action": "BUY",
        "symbol": "BTC/USDT",
        "market_type": "paper_spot",
        "confidence": 0.72,
        "thesis": "Test trade",
        "evidence": ["test signal"],
        "selected_strategy_ids": ["test_v1"],
        "position_size_pct": 5.0,
        "stop_loss_pct": 1.0,
        "take_profit_pct": 2.0,
        "max_holding_minutes": 60,
        "invalidation_conditions": ["test"],
        "risk_notes": "test",
    }

    # Fill r1 to limit
    r1 = RiskEngine(policy)
    for i in range(3):
        r1.evaluate(buy, {"mode": "paper", "decision_ts": float(i * 10), "decision_day": "2025-01-01"})
    assert r1.stats()["max_trades_in_single_day"] == 3

    # r2 starts fresh
    r2 = RiskEngine(policy)
    assert r2.stats()["daily_trade_days_count"] == 0
    r = r2.evaluate(buy, {"mode": "paper", "decision_ts": 2000.0, "decision_day": "2025-01-01"})
    assert r.decision == "APPROVED"


@pytest.mark.skipif(not FREQTRADE_AVAILABLE, reason="Freqtrade not installed")
def test_fallback_window_is_position_based():
    """_builtin_candidates must accept a sliced window DataFrame."""
    _strat_dir = Path(__file__).resolve().parents[1] / "freqtrade_data" / "strategies"
    if str(_strat_dir) not in sys.path:
        sys.path.insert(0, str(_strat_dir))
    from ai_supervised_strategy import _builtin_candidates

    df = pd.DataFrame({
        "open": [100.0 + i * 0.8 for i in range(60)],
        "high": [102.0 + i * 0.8 for i in range(60)],
        "low": [98.0 + i * 0.8 for i in range(60)],
        "close": [101.0 + i * 0.8 for i in range(60)],
        "volume": [1000 + i * 20 for i in range(60)],
    })
    # Only pass last 40 rows
    window = df.iloc[20:60]
    candidates = _builtin_candidates(window)
    buy = [c for c in candidates if c.get("side") == "BUY"]
    assert len(buy) >= 1, "Fallback candidate gen should produce BUY on uptrend window"


def test_resolve_candle_ts_reads_only_current_row():
    """_resolve_candle_ts must only access the current row, not the future."""
    import pytest
    pandas = pytest.importorskip("pandas")
    import pandas as pd
    df = pd.DataFrame({
        "date": pd.date_range("2025-01-01", periods=100, freq="5min"),
        "close": [100.0 + i * 0.1 for i in range(100)],
    })
    idx = df.index[50]
    from atos.time_context import _to_epoch
    ts = _to_epoch(df.at[idx, "date"])
    assert ts > 0
    import datetime
    dt = datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc)
    assert dt.year == 2025
    assert dt.month == 1
    assert dt.day == 1


def test_resolve_candle_ts_reads_only_current_row_production_path():
    """Production-path: real AISupervisedStrategy._resolve_candle_ts via GuardedAt.

    Uses importorskip('freqtrade') — this skips in Simple CI (no Freqtrade)
    but PASSES in Freqtrade Validation job (has Freqtrade).

    Must call real production method (not _to_epoch).
    Must detect future-row access as failure.
    """
    import pytest
    pytest.importorskip("freqtrade")
    import pandas as pd
    import sys
    from pathlib import Path
    _strat_dir = Path(__file__).resolve().parents[1] / "freqtrade_data" / "strategies"
    if str(_strat_dir) not in sys.path:
        sys.path.insert(0, str(_strat_dir))
    from ai_supervised_strategy import AISupervisedStrategy

    idx = 50
    ts_correct = 1719792000.0 + idx * 300  # 2025-01-01 00:00 + 50*5min

    # GuardedAt: only allows access to (idx, "date"), fails on any other row
    class GuardedAt:
        def __init__(self, allowed_key, value):
            self._allowed = allowed_key
            self._value = value
        def __getitem__(self, key):
            assert key == self._allowed, f"FUTURE ACCESS: requested {key}, allowed {self._allowed}"
            return self._value

    class GuardedFrame:
        columns = ["date"]
        def __init__(self, row_key, ts_value):
            self.at = GuardedAt(row_key, ts_value)
        def __getattribute__(self, name):
            if name == "at": return super().__getattribute__("at")
            if name == "columns": return ["date"]
            raise AttributeError(name)

    strategy = object.__new__(AISupervisedStrategy)
    frame = GuardedFrame((idx, "date"), ts_correct)
    ts = strategy._resolve_candle_ts(frame, idx)
    assert ts == ts_correct, f"Expected {ts_correct}, got {ts}"

    # Future row access must fail
    future_frame = GuardedFrame((idx + 1, "date"), ts_correct + 300)
    try:
        strategy._resolve_candle_ts(future_frame, idx + 1)
        assert False, "Should have raised AssertionError for future row"
    except AssertionError:
        pass
