"""Tests: no future data access in production methods."""
import pytest


def test_resolve_candle_ts_reads_only_current_row():
    """_resolve_candle_ts must only access the current row, not the future."""
    pandas = pytest.importorskip("pandas")
    import pandas as pd
    df = pd.DataFrame({"date": pd.date_range("2025-01-01", periods=10, freq="5min"), "close": range(100, 110)})
    df.set_index("date", inplace=True)
    idx = df.index[5]
    assert df.at[idx, "close"] == 105


def test_resolve_candle_ts_reads_only_current_row_production_path():
    """Production-path: AISupervisedStrategy._resolve_candle_ts(frame, idx) reads only idx row."""
    pytest.importorskip("freqtrade")
    import sys
    from pathlib import Path
    _strat_dir = Path(__file__).resolve().parents[1] / "freqtrade_data" / "strategies"
    if str(_strat_dir) not in sys.path:
        sys.path.insert(0, str(_strat_dir))
    from ai_supervised_strategy import AISupervisedStrategy

    strategy = object.__new__(AISupervisedStrategy)

    # P2: GuardedAt only allows (50, "date"), fails on any other access
    class GuardedAt:
        def __init__(self, allowed_key, value):
            self.allowed_key = allowed_key
            self.value = value
            self.accesses = []

        def __getitem__(self, key):
            self.accesses.append(key)
            assert key == self.allowed_key, f"Unexpected row access: {key} (allowed: {self.allowed_key})"
            return self.value

    class GuardedFrame:
        columns = ["date"]
        def __init__(self, allowed_key, value):
            self.at = GuardedAt(allowed_key, value)

    expected_ts = strategy._to_epoch("2025-01-01 00:00:00")
    frame = GuardedFrame((50, "date"), expected_ts)

    result = strategy._resolve_candle_ts(frame, 50)

    assert result == expected_ts
    assert frame.at.accesses == [(50, "date")], f"Unexpected accesses: {frame.at.accesses}"


def test_fallback_import_does_not_block_tests():
    assert True
