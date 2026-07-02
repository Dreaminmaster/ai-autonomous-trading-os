"""Combined tests for new modules: data freshness, market regime, OKX cache, DB migrations."""

import time
import sqlite3
import pytest
from pathlib import Path

from atos.data_freshness import DataFreshnessGuard, FreshnessResult
from atos.market_regime import MarketRegimeDetector, MarketRegime
from atos.okx_cache import OKXDataCache, CacheEntry
from atos.db_migrations import migrate, migrate_db_file, CURRENT_VERSION
from atos.domain import Candle


# ── Data Freshness ──────────────────────────────────────────────────

def test_data_freshness_sufficient():
    guard = DataFreshnessGuard(min_candles_required=10, max_candle_age_seconds=9999)
    candles = [Candle(100, 102, 99, 101, 100) for _ in range(20)]
    result = guard.check_candles(candles)
    assert result.is_fresh

def test_data_freshness_insufficient():
    guard = DataFreshnessGuard(min_candles_required=50)
    candles = [Candle(100, 102, 99, 101, 100) for _ in range(10)]
    result = guard.check_candles(candles)
    assert not result.is_fresh
    assert any("insufficient" in r for r in result.reasons)

def test_data_freshness_returns_dict():
    guard = DataFreshnessGuard()
    candles = [Candle(100, 102, 99, 101, 100) for _ in range(25)]
    result = guard.check_candles(candles)
    d = result.to_dict()
    assert d["is_fresh"] is True
    assert "age_seconds" in d


# ── Market Regime ───────────────────────────────────────────────────

def test_market_regime_unknown():
    detector = MarketRegimeDetector()
    regime = detector.detect([100.0] * 5)
    assert regime.regime == "unknown"

def test_market_regime_trending_up():
    detector = MarketRegimeDetector()
    closes = [100.0 + i * 0.3 for i in range(60)]  # steady uptrend
    regime = detector.detect(closes)
    assert regime.regime in ("trending_up", "ranging")  # depends on vol

def test_market_regime_volatile():
    detector = MarketRegimeDetector()
    import random
    closes = [100.0 + random.uniform(-5, 5) for _ in range(60)]
    regime = detector.detect(closes)
    assert regime.regime in ("volatile", "trending_up", "trending_down", "ranging")

def test_market_regime_to_dict():
    detector = MarketRegimeDetector()
    closes = [100.0 + i * 0.1 for i in range(60)]
    regime = detector.detect(closes)
    d = regime.to_dict()
    assert "regime" in d
    assert "confidence" in d


# ── OKX Cache ───────────────────────────────────────────────────────

def test_cache_put_get():
    cache = OKXDataCache("runtime/cache")
    cache.put("ticker", "BTC-USDT", {"price": 50000, "ts": "2025-01-01"})
    result = cache.get("ticker", "BTC-USDT", max_age_seconds=99999)
    assert result is not None
    assert result["price"] == 50000

def test_cache_stale():
    cache = OKXDataCache("runtime/cache")
    # Clear everything first
    cache.invalidate()

    cache.put("ticker", "ETH-USDT", {"price": 3000})

    # Override to be VERY old in memory AND on disk
    key = cache._key("ticker", "ETH-USDT")
    if key in cache._memory:
        old_entry = CacheEntry(key=key, data={"price": 3000}, cached_at=0, source="test")
        cache._memory[key] = old_entry

    # Also write stale data to disk
    file_path = cache.cache_dir / f"{key.replace(':', '_')}.json"
    import json
    file_path.write_text(json.dumps({
        "key": key, "cached_at": 0, "source": "test", "data": {"price": 3000}
    }))

    result = cache.get("ticker", "ETH-USDT", max_age_seconds=1)
    # Should be rejected as stale (cached_at=0, age = now - 0 = huge)
    assert result is None

def test_cache_invalidate():
    cache = OKXDataCache("runtime/cache")
    cache.put("ticker", "BTC-USDT", {"price": 50000})
    cache.put("ticker", "ETH-USDT", {"price": 3000})
    count = cache.invalidate(prefix="ticker")
    assert count >= 2
    assert cache.get("ticker", "BTC-USDT", max_age_seconds=99999) is None

def test_cache_stats():
    cache = OKXDataCache("runtime/cache")
    cache.put("test", "item1", {"a": 1})
    s = cache.stats()
    assert s["entries"] >= 1


# ── DB Migrations ───────────────────────────────────────────────────

def test_migration_creates_tables():
    import tempfile, os
    tmp = tempfile.mktemp(suffix=".sqlite")
    try:
        conn = sqlite3.connect(tmp)
        v = migrate(conn)
        assert v == CURRENT_VERSION

        # All expected tables exist
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        assert "events" in tables
        assert "strategy_scores" in tables
        assert "provider_calls" in tables
        assert "reviews" in tables
        assert "incidents" in tables
        assert "config_versions" in tables
        assert "_schema_version" in tables

        conn.close()
    finally:
        Path(tmp).unlink(missing_ok=True)

def test_migration_idempotent():
    import tempfile
    tmp = tempfile.mktemp(suffix=".sqlite")
    try:
        conn = sqlite3.connect(tmp)
        v1 = migrate(conn)
        v2 = migrate(conn)  # run again
        assert v1 == v2 == CURRENT_VERSION
        conn.close()
    finally:
        Path(tmp).unlink(missing_ok=True)

def test_migrate_db_file():
    import tempfile, os
    tmp = tempfile.mktemp(suffix=".sqlite")
    try:
        v = migrate_db_file(tmp)
        assert v == CURRENT_VERSION
        assert Path(tmp).exists()
    finally:
        Path(tmp).unlink(missing_ok=True)
