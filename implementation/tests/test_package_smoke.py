from atos.domain import make_hold, Candle
from atos.risk import RiskEngine
from atos.runtime import AutonomousRuntime
from atos.strategies import default_strategies


def policy():
    return {
        "mode": "paper",
        "allowed_symbols": ["BTC-USDT"],
        "position_limits": {"max_position_pct_per_trade": 1.0},
        "ai_output_limits": {"min_confidence_for_trade": 0.6},
    }


def candles():
    return [Candle(100+i, 102+i, 99+i, 101+i, 1000+i) for i in range(40)]


def test_risk_hold():
    decision = RiskEngine(policy()).evaluate(make_hold("test").to_dict())
    assert decision.decision == "APPROVED"


def test_strategies_emit_candidates():
    items = [s.generate("BTC-USDT", candles()) for s in default_strategies()]
    assert any(x for x in items if x is not None)


def test_runtime_loop_runs():
    result = AutonomousRuntime(policy()).run_loop("BTC-USDT", candles, loops=1)
    assert result.loops == 1
    assert result.ledger_events >= 4
