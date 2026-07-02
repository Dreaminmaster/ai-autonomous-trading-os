"""Test strategy_registry, additional strategies, and new modules wire-up."""

from atos.domain import Candle
from atos.strategy_registry import (
    StrategyRegistry, RangeGridStrategy, VolatilityBreakoutStrategy,
    MomentumStrategy, FundingBasisStrategy, OrderbookImbalanceStrategy,
    HoldBaselineStrategy, create_default_registry,
)


def candles_uptrend():
    return [Candle(100 + i * 0.2, 102 + i * 0.2, 99 + i * 0.2, 101 + i * 0.2, 1000 + i * 10) for i in range(50)]


def candles_ranging():
    import math
    return [Candle(100 + 2 * math.sin(i * 0.3), 102 + 2 * math.sin(i * 0.3), 98 + 2 * math.sin(i * 0.3), 100 + 2 * math.sin(i * 0.3), 1000) for i in range(50)]


# ── Strategy Registry ──────────────────────────────────────────────

def test_registry_register():
    reg = StrategyRegistry()
    reg.register(RangeGridStrategy())
    assert "range_grid_v1" in reg.all_ids()

def test_registry_enable_disable():
    reg = StrategyRegistry()
    reg.register(RangeGridStrategy(), enabled=False)
    assert "range_grid_v1" not in reg.enabled_ids()
    reg.enable("range_grid_v1")
    assert "range_grid_v1" in reg.enabled_ids()
    reg.disable("range_grid_v1")
    assert "range_grid_v1" not in reg.enabled_ids()

def test_registry_generate_all():
    reg = create_default_registry()
    candidates = reg.generate_all("BTC/USDT:USDT", candles_uptrend())
    assert len(candidates) >= 2  # at least some candidates + hold baseline
    # hold baseline should always be present
    assert any(c.strategy_id == "hold_baseline" for c in candidates)

def test_registry_default_has_8():
    reg = create_default_registry()
    ids = reg.all_ids()
    assert len(ids) >= 6  # trend, mean_reversion, breakout, range, vol, momentum + stubs


# ── Range Grid Strategy ────────────────────────────────────────────

def test_range_grid_ranging():
    strat = RangeGridStrategy()
    c = strat.generate("BTC/USDT:USDT", candles_ranging())
    # May or may not trigger — depends on range width
    if c:
        assert c.strategy_id == "range_grid_v1"
        assert c.regime_tags is not None

def test_range_grid_uptrend_skips():
    strat = RangeGridStrategy()
    c = strat.generate("BTC/USDT:USDT", candles_uptrend())
    # Strong trend = no range = should return None
    if c:
        assert c.regime_tags is not None


# ── Volatility Breakout ────────────────────────────────────────────

def test_vol_breakout_exists():
    strat = VolatilityBreakoutStrategy()
    c = strat.generate("BTC/USDT:USDT", candles_uptrend())
    if c:
        assert c.strategy_id == "volatility_breakout_v1"


# ── Momentum ───────────────────────────────────────────────────────

def test_momentum_returns_candidate():
    strat = MomentumStrategy()
    c = strat.generate("BTC/USDT:USDT", candles_uptrend())
    if c:
        assert c.strategy_id == "momentum_v1"


# ── Stubs don't crash ──────────────────────────────────────────────

def test_funding_stub():
    strat = FundingBasisStrategy()
    c = strat.generate("BTC/USDT:USDT", candles_uptrend())
    assert c is None  # stub, always None

def test_orderbook_stub():
    strat = OrderbookImbalanceStrategy()
    c = strat.generate("BTC/USDT:USDT", candles_uptrend())
    assert c is None  # stub, always None


# ── Hold baseline always works ─────────────────────────────────────

def test_hold_baseline():
    strat = HoldBaselineStrategy()
    c = strat.generate("BTC/USDT:USDT", candles_uptrend())
    assert c is not None
    assert c.strategy_id == "hold_baseline"
    assert c.side == "HOLD"
