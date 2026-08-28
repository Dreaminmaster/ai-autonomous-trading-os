from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self

import pytest

from atos.domain import Candle, StrategyCandidate, TradeIntent
from atos.durable_execution import DurableSimulatedExecutor
from atos.ledger import Ledger
from atos.market import MarketSnapshot, PublicMarketAdapter, PublicMarketDataError
from atos.providers import (
    BaseProvider,
    ProviderManager,
    ProviderRequest,
    ProviderResult,
)
from atos.runtime import AutonomousRuntime, RuntimeSafetyError
from atos.strategy_registry import StrategyRegistry


def _policy(mode: str = "paper") -> dict:
    return {
        "mode": mode,
        "live_enabled": False,
        "allowed_symbols": ["BTC-USDT"],
        "position_limits": {"max_position_pct_per_trade": 10.0},
        "ai_output_limits": {"min_confidence_for_trade": 0.60},
        "trade_limits": {"max_trades_per_day": 20, "cooldown_seconds": 300},
        "risk_limits": {"max_drawdown_pct": 20.0},
        "data_freshness": {
            "max_candle_age_seconds": 300,
            "min_candles_required": 20,
            "max_gap_minutes": 15,
        },
        "paper": {"equity_usdt": 1000.0, "fee_bps": 10.0, "slippage_bps": 5.0},
    }


def _candles(*, age_seconds: int = 60, count: int = 30) -> list[Candle]:
    end = datetime.now(tz=UTC) - timedelta(seconds=age_seconds)
    result = []
    for index in range(count):
        timestamp = end - timedelta(minutes=count - index - 1)
        result.append(
            Candle(
                open=100.0 + index,
                high=102.0 + index,
                low=99.0 + index,
                close=101.0 + index,
                volume=1000.0 + index,
                ts=timestamp.isoformat().replace("+00:00", "Z"),
            )
        )
    return result


class BuyStrategy:
    strategy_id = "buy_plugin_v1"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate:
        return StrategyCandidate(
            self.strategy_id,
            symbol,
            "BUY",
            0.8,
            0.8,
            "validated plugin signal",
            1.0,
            2.0,
            60,
            ["test"],
            "test-only deterministic signal",
        )


class BrokenStrategy:
    strategy_id = "broken_plugin_v1"

    def generate(self, symbol: str, candles: list[Candle]) -> StrategyCandidate:
        raise RuntimeError("plugin crash")


class BrokenExecutor:
    def execute(self, *args: object, **kwargs: object) -> None:
        raise RuntimeError("simulator crash")


class StubMarketAdapter:
    def __init__(self, candles: list[Candle]):
        self.candles = candles
        self.calls = 0

    def snapshot(self, symbol: str, **_: object) -> MarketSnapshot:
        self.calls += 1
        timestamp = str(int(datetime.now(tz=UTC).timestamp() * 1000))
        mark = self.candles[-1].close
        return MarketSnapshot(
            symbol=symbol,
            ticker={
                "code": "0",
                "data": [{"instId": symbol, "last": str(mark), "ts": timestamp}],
            },
            candles=self.candles,
            orderbook={
                "code": "0",
                "data": [
                    {
                        "bids": [[str(mark - 1), "1", "0", "1"]],
                        "asks": [[str(mark + 1), "1", "0", "1"]],
                        "ts": timestamp,
                    }
                ],
            },
        )


def _registry(*strategies: object) -> StrategyRegistry:
    registry = StrategyRegistry()
    for strategy in strategies:
        registry.register(strategy)
    return registry


def test_paper_public_cycle_is_complete_and_audited() -> None:
    ledger = Ledger(":memory:")
    runtime = AutonomousRuntime(
        _policy("paper"),
        ledger,
        registry=_registry(BuyStrategy()),
        market_adapter=StubMarketAdapter(_candles()),
    )

    result = runtime.run_public_once("BTC-USDT")

    assert result["intent_validation"]["is_valid"] is True
    assert result["intent"]["action"] == "BUY"
    assert result["risk"]["decision"] == "APPROVED"
    assert result["execution"]["status"] == "FILLED_SIMULATED"
    assert result["execution"]["mode"] == "paper"
    kinds = [event["kind"] for event in ledger.list_events(limit=50)]
    for expected in (
        "runtime_session_started",
        "runtime_cycle_started",
        "market_snapshot",
        "strategy_candidates",
        "provider_result",
        "trade_intent_validation",
        "trade_intent",
        "risk_decision",
        "execution",
        "runtime_cycle_completed",
    ):
        assert expected in kinds
    snapshot_event = next(
        event
        for event in ledger.list_events(limit=50)
        if event["kind"] == "market_snapshot"
    )
    assert snapshot_event["payload"]["source"] == "OKX_OFFICIAL_PUBLIC"
    assert snapshot_event["payload"]["public_only"] is True
    assert snapshot_event["payload"]["account_access"] is False


def test_shadow_cycle_is_public_only_and_never_represents_an_order() -> None:
    runtime = AutonomousRuntime(
        _policy("shadow"),
        Ledger(":memory:"),
        registry=_registry(BuyStrategy()),
        market_adapter=StubMarketAdapter(_candles()),
    )

    result = runtime.run_public_once("BTC-USDT")

    assert result["mode"] == "shadow"
    assert result["execution"]["status"] == "SHADOW_SIMULATED"
    assert result["execution"]["mode"] == "shadow"


def test_live_mode_is_rejected_before_any_market_access() -> None:
    adapter = StubMarketAdapter(_candles())
    with pytest.raises(RuntimeSafetyError, match="Live runtime is forbidden"):
        AutonomousRuntime(_policy("live"), market_adapter=adapter)
    assert adapter.calls == 0


def test_broken_strategy_is_isolated_and_hold_baseline_survives() -> None:
    runtime = AutonomousRuntime(
        _policy("paper"),
        Ledger(":memory:"),
        registry=_registry(BrokenStrategy()),
    )

    result = runtime.run_once("BTC-USDT", _candles(), mark_price=130.0)

    assert result["intent"]["action"] == "HOLD"
    assert result["execution"]["status"] == "NOOP_HOLD"
    assert result["strategy_diagnostics"] == [
        {
            "strategy_id": "broken_plugin_v1",
            "status": "PLUGIN_FAILED",
            "detail": "RuntimeError: plugin crash",
        }
    ]
    assert result["candidates"][-1]["strategy_id"] == "hold_baseline"


class InvalidIntentProvider(BaseProvider):
    def __init__(self) -> None:
        super().__init__("invalid")

    def decide(self, request: ProviderRequest) -> ProviderResult:
        return ProviderResult(
            intent=TradeIntent(
                schema_version="bad-version",
                action="BUY",
                symbol=request.symbol,
                market_type="private_swap",
                confidence=2.0,
                thesis="",
                evidence=[],
                selected_strategy_ids=[],
                position_size_pct=999.0,
                stop_loss_pct=0.0,
                take_profit_pct=0.0,
                max_holding_minutes=-1,
                invalidation_conditions=[],
                risk_notes="",
            ),
            provider_name=self.name,
        )


def test_invalid_provider_output_is_schema_corrected_to_hold() -> None:
    providers = ProviderManager()
    providers.register(InvalidIntentProvider())
    providers.set_chain(["invalid"])
    runtime = AutonomousRuntime(
        _policy("paper"),
        Ledger(":memory:"),
        registry=_registry(BuyStrategy()),
        providers=providers,
    )

    result = runtime.run_once("BTC-USDT", _candles(), mark_price=130.0)

    assert result["intent_validation"]["is_valid"] is False
    assert result["intent"]["action"] == "HOLD"
    assert result["execution"]["status"] == "NOOP_HOLD"


def test_simulated_executor_failure_is_audited_hold() -> None:
    runtime = AutonomousRuntime(
        _policy("paper"),
        Ledger(":memory:"),
        registry=_registry(BuyStrategy()),
        executor=BrokenExecutor(),
    )

    result = runtime.run_once("BTC-USDT", _candles(), mark_price=130.0)

    assert result["safe_default"] is True
    assert result["intent"]["action"] == "HOLD"
    assert result["execution"]["status"] == "NOOP_HOLD"
    assert "simulated execution failed" in result["provider_result"]["error"]


def test_stale_public_data_fails_to_audited_hold() -> None:
    runtime = AutonomousRuntime(
        _policy("shadow"),
        Ledger(":memory:"),
        registry=_registry(BuyStrategy()),
        market_adapter=StubMarketAdapter(_candles(age_seconds=3600)),
    )

    result = runtime.run_public_once("BTC-USDT")

    assert result["safe_default"] is True
    assert result["intent"]["action"] == "HOLD"
    assert result["execution"]["status"] == "NOOP_HOLD"
    assert "stale" in result["provider_result"]["error"]


class FakeResponse:
    def __init__(self, url: str, payload: dict, *, final_url: str | None = None):
        self.url = final_url or url
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, _: int) -> bytes:
        return self.raw


def test_public_adapter_keeps_only_confirmed_strict_candles() -> None:
    now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
    rows = []
    for index in range(21):
        timestamp = now_ms - index * 60_000
        rows.append(
            [
                str(timestamp),
                "100",
                "102",
                "99",
                "101",
                "1000",
                "0",
                "0",
                "0" if index == 0 else "1",
            ]
        )

    def opener(request, **_: object):
        return FakeResponse(request.full_url, {"code": "0", "msg": "", "data": rows})

    candles = PublicMarketAdapter(opener=opener).candles("BTC-USDT", limit=21)

    assert len(candles) == 20
    assert candles[0].ts < candles[-1].ts
    assert all(candle.close == 101.0 for candle in candles)


def test_public_adapter_rejects_unofficial_origin_and_redirect_drift() -> None:
    with pytest.raises(PublicMarketDataError, match="official OKX"):
        PublicMarketAdapter("https://example.com")

    def redirected(request, **_: object):
        return FakeResponse(
            request.full_url,
            {"code": "0", "data": []},
            final_url="https://www.okx.com/api/v5/account/balance",
        )

    adapter = PublicMarketAdapter(opener=redirected)
    with pytest.raises(PublicMarketDataError, match="redirect drift"):
        adapter.ticker("BTC-USDT")


def test_snapshot_rejects_crossed_or_wrong_instrument_orderbook() -> None:
    snapshot = StubMarketAdapter(_candles()).snapshot("BTC-USDT")
    snapshot.ticker["data"][0]["instId"] = "ETH-USDT"
    with pytest.raises(PublicMarketDataError, match="ticker instrument"):
        snapshot.validate("BTC-USDT")

    snapshot = StubMarketAdapter(_candles()).snapshot("BTC-USDT")
    snapshot.orderbook["data"][0]["bids"][0][0] = "999"
    with pytest.raises(PublicMarketDataError, match="crossed"):
        snapshot.validate("BTC-USDT")


def test_durable_paper_cycle_persists_idempotent_fill_and_position(
    tmp_path: Path,
) -> None:
    policy = _policy("paper")
    policy["persistence"] = {
        "enabled": True,
        "database_path": str(tmp_path / "runtime.sqlite"),
    }
    runtime = AutonomousRuntime(
        policy,
        Ledger(":memory:"),
        registry=_registry(BuyStrategy()),
    )

    result = runtime.run_once("BTC-USDT", _candles(), mark_price=130.0)

    assert result["execution"]["status"] == "FILLED_SIMULATED"
    assert result["execution"]["execution_intent_id"]
    assert result["execution"]["fill_id"]
    executor = runtime.executor
    counts = {
        table: executor.database.connection.execute(
            f"SELECT COUNT(*) FROM {table}"
        ).fetchone()[0]
        for table in (
            "trade_intents",
            "risk_decisions",
            "execution_intents",
            "execution_idempotency_claims",
            "order_states",
            "fill_states",
            "position_states",
        )
    }
    assert counts == {table: 1 for table in counts}


def test_durable_hold_has_no_execution_side_effects(tmp_path: Path) -> None:
    policy = _policy("shadow")
    policy["persistence"] = {
        "enabled": True,
        "database_path": str(tmp_path / "runtime.sqlite"),
    }
    runtime = AutonomousRuntime(
        policy,
        Ledger(":memory:"),
        registry=_registry(),
    )

    result = runtime.run_once("BTC-USDT", _candles(), mark_price=130.0)

    assert result["intent"]["action"] == "HOLD"
    assert result["execution"]["status"] == "NOOP_HOLD"
    assert result["execution"]["durable_outcome"] == "NO_EXECUTION_INTENT"
    executor = runtime.executor
    assert (
        executor.database.connection.execute(
            "SELECT COUNT(*) FROM execution_intents"
        ).fetchone()[0]
        == 0
    )
    assert (
        executor.database.connection.execute(
            "SELECT COUNT(*) FROM order_states"
        ).fetchone()[0]
        == 0
    )


def test_durable_executor_replay_is_terminal_noop(tmp_path: Path) -> None:
    executor = DurableSimulatedExecutor(
        mode="paper",
        database_path=tmp_path / "runtime.sqlite",
    )
    observed_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    context = {
        "session_id": "session-replay",
        "session_started_at": observed_at,
        "cycle_id": "cycle-replay",
        "mode": "paper",
        "observed_at": observed_at,
    }
    intent = {
        "schema_version": "trade_intent.v1",
        "action": "BUY",
        "symbol": "BTC-USDT",
        "market_type": "paper_spot",
        "confidence": 0.8,
        "thesis": "replay-safe test",
        "evidence": ["deterministic"],
        "selected_strategy_ids": ["test"],
        "position_size_pct": 1.0,
        "stop_loss_pct": 1.0,
        "take_profit_pct": 2.0,
        "max_holding_minutes": 60,
        "invalidation_conditions": ["test invalidated"],
        "risk_notes": "test",
        "metadata": {},
    }
    risk = {
        "decision": "APPROVED",
        "reasons": ["all_checks_passed"],
        "risk_score": 0.1,
        "checks": {"external_execution": False},
    }

    first = executor.execute(
        intent,
        risk,
        mark_price=100.0,
        equity_usdt=1000.0,
        execution_context=context,
    )
    replay = executor.execute(
        intent,
        risk,
        mark_price=100.0,
        equity_usdt=1000.0,
        execution_context=context,
    )

    assert first.durable_outcome == "FILLED"
    assert replay.durable_outcome == "TERMINAL_NOOP"
    assert replay.order_id == first.order_id
    for table in (
        "execution_intents",
        "order_states",
        "fill_states",
        "position_states",
    ):
        assert (
            executor.database.connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
            == 1
        )


def test_durable_portfolio_exposure_survives_runtime_restart(tmp_path: Path) -> None:
    database_path = str(tmp_path / "runtime.sqlite")
    policy = _policy("paper")
    policy["persistence"] = {"enabled": True, "database_path": database_path}
    policy["portfolio_limits"] = {
        "max_gross_exposure_pct": 7.5,
        "max_symbol_exposure_pct": 7.5,
    }
    first_runtime = AutonomousRuntime(
        policy,
        Ledger(":memory:"),
        registry=_registry(BuyStrategy()),
    )
    first = first_runtime.run_once("BTC-USDT", _candles(), mark_price=130.0)
    assert first["execution"]["status"] == "FILLED_SIMULATED"

    restarted_runtime = AutonomousRuntime(
        policy,
        Ledger(":memory:"),
        registry=_registry(BuyStrategy()),
    )
    second = restarted_runtime.run_once("BTC-USDT", _candles(), mark_price=130.0)

    assert second["risk"]["decision"] == "REJECTED"
    assert any(
        "exposure_exceeds_limit" in reason for reason in second["risk"]["reasons"]
    )
    assert second["execution"]["status"] == "BLOCKED_BY_RISK"
    assert (
        restarted_runtime.executor.database.connection.execute(
            "SELECT COUNT(*) FROM execution_intents"
        ).fetchone()[0]
        == 1
    )


def test_durable_startup_detects_incomplete_cycle_and_pauses(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite"
    executor = DurableSimulatedExecutor(mode="paper", database_path=database_path)
    executor.database.connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        ("session-incomplete", "2026-01-01T00:00:00Z", "paper", "RUNNING"),
    )
    executor.database.connection.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (
            "cycle-incomplete",
            "session-incomplete",
            "BTC-USDT",
            "2026-01-01T00:00:00Z",
            "RISK_DECIDED",
        ),
    )
    executor.database.connection.commit()
    executor.database.close()

    restarted = DurableSimulatedExecutor(mode="paper", database_path=database_path)
    report = restarted.recovery_report()

    assert report["required"] is True
    assert report["classification"] == "RECOVERY_REQUIRED"
    assert report["cycles"][0]["cycle_id"] == "cycle-incomplete"
    with pytest.raises(RuntimeError, match="startup recovery"):
        restarted.execute(
            {},
            {},
            mark_price=100.0,
            equity_usdt=1000.0,
            execution_context={},
        )
