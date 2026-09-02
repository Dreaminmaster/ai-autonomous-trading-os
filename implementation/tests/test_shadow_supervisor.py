from __future__ import annotations

import json
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Self

import pytest
from atos.durable_execution import DurableSimulatedExecutor
from atos.ledger import Ledger
from atos.market import PublicMarketAdapter
from atos.runtime import AutonomousRuntime
from atos.shadow_operator import inspect_shadow_status
from atos.shadow_supervisor import (
    AtomicHealthWriter,
    ShadowSupervisor,
    ShadowSupervisorError,
    build_shadow_supervisor,
)
from atos.strategy_registry import StrategyRegistry


def _policy(tmp_path: Path) -> dict:
    return {
        "mode": "shadow",
        "live_enabled": False,
        "public_data_only": True,
        "allowed_symbols": ["BTC-USDT", "ETH-USDT"],
        "position_limits": {"max_position_pct_per_trade": 1.0},
        "ai_output_limits": {"min_confidence_for_trade": 0.6},
        "trade_limits": {"max_trades_per_day": 20, "cooldown_seconds": 300},
        "risk_limits": {"max_drawdown_pct": 20.0},
        "portfolio_limits": {
            "max_gross_exposure_pct": 20.0,
            "max_symbol_exposure_pct": 5.0,
        },
        "data_freshness": {
            "max_candle_age_seconds": 300,
            "min_candles_required": 20,
            "max_gap_minutes": 15,
        },
        "paper": {"equity_usdt": 1000.0, "fee_bps": 10.0, "slippage_bps": 5.0},
        "persistence": {
            "enabled": True,
            "database_path": str(tmp_path / "runtime.sqlite"),
        },
    }


class FakeResponse:
    def __init__(self, url: str, payload: dict):
        self.url = url
        self.raw = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def geturl(self) -> str:
        return self.url

    def read(self, _: int) -> bytes:
        return self.raw


class PublicFixtureOpener:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[str] = []

    def __call__(self, request: object, **_: object) -> FakeResponse:
        url = str(request.full_url)
        self.calls.append(url)
        if self.fail:
            raise OSError("fixture public transport unavailable")
        parsed = urllib.parse.urlparse(url)
        params = urllib.parse.parse_qs(parsed.query)
        symbol = params["instId"][0]
        now_ms = int(datetime.now(tz=UTC).timestamp() * 1000)
        if parsed.path == "/api/v5/market/ticker":
            payload = {
                "code": "0",
                "data": [{"instId": symbol, "last": "101", "ts": str(now_ms)}],
            }
        elif parsed.path == "/api/v5/market/candles":
            payload = {
                "code": "0",
                "data": [
                    [
                        str(now_ms - index * 60_000),
                        "100",
                        "102",
                        "99",
                        "101",
                        "1000",
                        "0",
                        "0",
                        "1",
                    ]
                    for index in range(21)
                ],
            }
        elif parsed.path == "/api/v5/market/books":
            payload = {
                "code": "0",
                "data": [
                    {
                        "bids": [["100", "1", "0", "1"]],
                        "asks": [["102", "1", "0", "1"]],
                        "ts": str(now_ms),
                    }
                ],
            }
        else:  # pragma: no cover - any new endpoint is a contract failure
            raise AssertionError(parsed.path)
        return FakeResponse(url, payload)


def _runtime(tmp_path: Path, opener: PublicFixtureOpener) -> AutonomousRuntime:
    return AutonomousRuntime(
        _policy(tmp_path),
        Ledger(str(tmp_path / "events.sqlite")),
        registry=StrategyRegistry(),
        market_adapter=PublicMarketAdapter(opener=opener),
    )


def _supervisor(
    tmp_path: Path,
    opener: PublicFixtureOpener,
    *,
    symbols: list[str] | None = None,
    failure_threshold: int = 3,
    sleep_fn=lambda _: None,
) -> ShadowSupervisor:
    return ShadowSupervisor(
        _runtime(tmp_path, opener),
        symbols=symbols or ["BTC-USDT"],
        health_path=tmp_path / "health.json",
        interval_seconds=0,
        failure_threshold=failure_threshold,
        sleep_fn=sleep_fn,
    )


def test_bounded_shadow_supervision_persists_health_audit_and_stop(
    tmp_path: Path,
) -> None:
    opener = PublicFixtureOpener()
    supervisor = _supervisor(tmp_path, opener, symbols=["BTC-USDT", "ETH-USDT"])

    result = supervisor.run(max_loops=2)

    assert result["reason"] == "BOUNDED_COMPLETE"
    assert result["state"] == "STOPPED"
    assert result["loops_completed"] == 2
    assert result["cycles_completed"] == 4
    assert result["heartbeat_sequence"] == 4
    assert result["total_failures"] == 0
    assert result["durable_session_status"] == "STOPPED"
    assert result["account_access"] is False
    assert result["private_api"] is False
    assert result["external_execution"] is False
    assert result["automatic_restart"] is False
    assert result["live"] == "FORBIDDEN"
    assert len(opener.calls) == 12
    health = json.loads((tmp_path / "health.json").read_text(encoding="utf-8"))
    assert health["reason"] == "BOUNDED_COMPLETE"
    assert health["session_id"] == supervisor.runtime.session_id
    assert health["single_process_lock"] is True
    assert not list(tmp_path.glob(".health.json.*.tmp"))
    lock_path = tmp_path / "runtime.sqlite.shadow.lock"
    assert (
        lock_path.read_text(encoding="utf-8").strip() == supervisor.runtime.session_id
    )
    assert lock_path.stat().st_mode & 0o777 == 0o600
    connection = supervisor.runtime.executor.database.connection
    session = connection.execute(
        "SELECT status,stop_reason FROM runtime_sessions WHERE session_id=?",
        (supervisor.runtime.session_id,),
    ).fetchone()
    assert tuple(session) == ("STOPPED", "BOUNDED_COMPLETE")
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM runtime_cycles WHERE status='COMPLETED'"
        ).fetchone()[0]
        == 4
    )
    assert connection.execute("SELECT COUNT(*) FROM order_states").fetchone()[0] == 0
    kinds = [event["kind"] for event in supervisor.runtime.ledger.list_events(100)]
    assert kinds.count("shadow_supervisor_started") == 1
    assert kinds.count("shadow_supervisor_heartbeat") == 4
    assert kinds.count("shadow_supervisor_stopped") == 1


def test_bounded_supervisor_output_is_operator_status_compatible(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path, PublicFixtureOpener())
    result = supervisor.run(max_loops=1)
    assessed_at = datetime.fromisoformat(result["updated_at"])

    report = inspect_shadow_status(
        _policy(tmp_path),
        health_path=tmp_path / "health.json",
        database_path=tmp_path / "runtime.sqlite",
        max_heartbeat_age_seconds=180,
        now=assessed_at,
    )

    assert report["operational_state"] == "STOPPED", report
    assert report["reason"] == "BOUNDED_COMPLETE"
    assert report["errors"] == []
    assert report["authorizes_live"] is False


def test_public_data_failures_trip_circuit_breaker_without_orders(
    tmp_path: Path,
) -> None:
    opener = PublicFixtureOpener(fail=True)
    supervisor = _supervisor(tmp_path, opener, failure_threshold=2)

    result = supervisor.run(max_loops=10)

    assert result["reason"] == "CIRCUIT_BREAKER"
    assert result["cycles_completed"] == 2
    assert result["total_failures"] == 2
    assert result["consecutive_failures"] == 2
    assert result["last_failure"] == {
        "classification": "DATA_FAILURE",
        "symbol": "BTC-USDT",
    }
    assert result["durable_session_status"] == "STOPPED"
    connection = supervisor.runtime.executor.database.connection
    assert connection.execute("SELECT COUNT(*) FROM order_states").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM fill_states").fetchone()[0] == 0


def test_preflight_recovery_blocks_all_public_requests(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    executor = DurableSimulatedExecutor(
        mode="shadow", database_path=policy["persistence"]["database_path"]
    )
    executor.database.connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,NULL,NULL)",
        ("prior-session", "2026-01-01T00:00:00Z", "shadow", "RUNNING"),
    )
    executor.database.connection.execute(
        "INSERT INTO runtime_cycles "
        "(cycle_id,session_id,symbol,started_at,status) VALUES (?,?,?,?,?)",
        (
            "incomplete-cycle",
            "prior-session",
            "BTC-USDT",
            "2026-01-01T00:00:00Z",
            "RISK_DECIDED",
        ),
    )
    executor.database.connection.commit()
    executor.database.close()
    opener = PublicFixtureOpener()
    supervisor = _supervisor(tmp_path, opener)

    result = supervisor.run(max_loops=1)

    assert result["reason"] == "RECOVERY_REQUIRED"
    assert result["state"] == "PAUSED_RECOVERY_REQUIRED"
    assert result["recovery_required"] is True
    assert result["cycles_completed"] == 0
    assert result["durable_session_status"] == "NOT_PERSISTED"
    assert opener.calls == []


def test_graceful_stop_before_first_cycle_has_no_runtime_state(
    tmp_path: Path,
) -> None:
    opener = PublicFixtureOpener()
    supervisor = _supervisor(tmp_path, opener)

    result = supervisor.run(max_loops=None, stop_requested=lambda: True)

    assert result["reason"] == "OPERATOR_STOP"
    assert result["cycles_completed"] == 0
    assert result["durable_session_status"] == "NOT_PERSISTED"
    assert opener.calls == []
    assert (
        supervisor.runtime.executor.database.connection.execute(
            "SELECT COUNT(*) FROM runtime_sessions"
        ).fetchone()[0]
        == 0
    )


def test_continuous_run_stop_is_checked_after_interruptible_wait(
    tmp_path: Path,
) -> None:
    stop = {"requested": False}

    def request_stop(_: float) -> None:
        stop["requested"] = True

    opener = PublicFixtureOpener()
    supervisor = ShadowSupervisor(
        _runtime(tmp_path, opener),
        symbols=["BTC-USDT"],
        health_path=tmp_path / "health.json",
        interval_seconds=1,
        sleep_fn=request_stop,
    )

    result = supervisor.run(max_loops=None, stop_requested=lambda: stop["requested"])

    assert result["reason"] == "OPERATOR_STOP"
    assert result["loops_completed"] == 1
    assert result["cycles_completed"] == 1


def test_invalid_runtime_output_fails_closed_without_exception_text(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path, PublicFixtureOpener(), failure_threshold=1)
    supervisor.runtime.run_public_once = lambda *args, **kwargs: {}

    result = supervisor.run(max_loops=1)

    assert result["reason"] == "CIRCUIT_BREAKER"
    assert result["last_failure"]["classification"] == "PROGRAM_FAILURE"
    assert result["durable_session_status"] == "NOT_PERSISTED"
    serialized = json.dumps(result)
    assert "exception" not in serialized.lower()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda result: result.update({"intent_validation": {"is_valid": False}}),
        lambda result: result.update(
            {
                "strategy_diagnostics": [
                    {"strategy_id": "broken", "status": "PLUGIN_FAILED"}
                ]
            }
        ),
        lambda result: result.update({"execution": {"mode": "paper"}}),
    ],
)
def test_invalid_decision_pipeline_state_is_program_failure(mutation) -> None:
    result = {
        "provider_result": {"error": None},
        "intent_validation": {"is_valid": True},
        "strategy_diagnostics": [],
        "execution": {"mode": "shadow"},
    }
    mutation(result)

    assert ShadowSupervisor._result_failure(result) == "PROGRAM_FAILURE"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"mode": "paper"}), "Shadow mode"),
        (lambda value: value.update({"live_enabled": True}), "Live"),
        (lambda value: value.update({"public_data_only": False}), "public_data_only"),
        (
            lambda value: value.update({"persistence": {"enabled": False}}),
            "persistence",
        ),
    ],
)
def test_unsafe_policy_is_rejected_before_files_or_network(
    tmp_path: Path, mutation, message: str
) -> None:
    policy = _policy(tmp_path)
    mutation(policy)

    with pytest.raises(ShadowSupervisorError, match=message):
        build_shadow_supervisor(
            policy,
            symbols=["BTC-USDT"],
            health_path=tmp_path / "health.json",
            ledger_path=tmp_path / "events.sqlite",
        )

    assert not (tmp_path / "runtime.sqlite").exists()
    assert not (tmp_path / "events.sqlite").exists()
    assert not (tmp_path / "health.json").exists()


def test_symbols_paths_and_loop_controls_fail_closed(tmp_path: Path) -> None:
    policy = _policy(tmp_path)
    with pytest.raises(ShadowSupervisorError, match="duplicate"):
        build_shadow_supervisor(
            policy,
            symbols=["BTC-USDT", "BTC-USDT"],
            health_path=tmp_path / "health.json",
            ledger_path=tmp_path / "events.sqlite",
        )
    with pytest.raises(ShadowSupervisorError, match="allowlisted"):
        build_shadow_supervisor(
            policy,
            symbols=["DOGE-USDT"],
            health_path=tmp_path / "health.json",
            ledger_path=tmp_path / "events.sqlite",
        )
    with pytest.raises(ShadowSupervisorError, match="paths must differ"):
        build_shadow_supervisor(
            policy,
            symbols=["BTC-USDT"],
            health_path=tmp_path / "same.sqlite",
            ledger_path=tmp_path / "same.sqlite",
        )
    supervisor = _supervisor(tmp_path, PublicFixtureOpener())
    with pytest.raises(ShadowSupervisorError, match="max_loops"):
        supervisor.run(max_loops=0)


def test_atomic_health_writer_rejects_symlink_target(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    link = tmp_path / "health.json"
    link.symlink_to(target)

    with pytest.raises(ShadowSupervisorError, match="symlink"):
        AtomicHealthWriter(link).write({"state": "RUNNING"})

    assert target.read_text(encoding="utf-8") == "{}"


def test_runtime_database_process_lock_rejects_concurrent_supervisor(
    tmp_path: Path,
) -> None:
    first_opener = PublicFixtureOpener()
    second_opener = PublicFixtureOpener()
    first = _supervisor(tmp_path, first_opener)
    second = _supervisor(tmp_path, second_opener)
    first._process_lock.acquire()
    try:
        with pytest.raises(ShadowSupervisorError, match="another Shadow supervisor"):
            second.run(max_loops=1)
    finally:
        first._process_lock.release()

    assert first_opener.calls == []
    assert second_opener.calls == []
    assert not (tmp_path / "health.json").exists()
