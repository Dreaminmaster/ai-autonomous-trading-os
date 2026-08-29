from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from atos.durable_execution import DurableSimulatedExecutor
from atos.durable_recovery import (
    DurableRecoveryError,
    DurableSimulatedRecoveryController,
)


def _approved_intent() -> dict:
    return {
        "schema_version": "trade_intent.v1",
        "action": "BUY",
        "symbol": "BTC-USDT",
        "market_type": "paper_spot",
        "confidence": 0.8,
        "thesis": "recovery test",
        "evidence": ["deterministic"],
        "selected_strategy_ids": ["test"],
        "position_size_pct": 1.0,
        "stop_loss_pct": 1.0,
        "take_profit_pct": 2.0,
        "max_holding_minutes": 60,
        "invalidation_conditions": ["invalidated"],
        "risk_notes": "test",
        "metadata": {},
    }


def _approved_risk() -> dict:
    return {
        "decision": "APPROVED",
        "reasons": ["all_checks_passed"],
        "risk_score": 0.1,
        "checks": {"external_execution": False},
    }


def _create_dispatch_committed_failure(database_path: Path) -> dict:
    executor = DurableSimulatedExecutor(mode="paper", database_path=database_path)
    observed_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    context = {
        "session_id": "session-recovery-control",
        "session_started_at": observed_at,
        "cycle_id": "cycle-recovery-control",
        "mode": "paper",
        "observed_at": observed_at,
    }

    def fail_after_dispatch(_: object) -> None:
        raise RuntimeError("injected after dispatch commit")

    executor._coordinator.execute = fail_after_dispatch
    with pytest.raises(RuntimeError, match="injected after dispatch commit"):
        executor.execute(
            _approved_intent(),
            _approved_risk(),
            mark_price=100.0,
            equity_usdt=1000.0,
            execution_context=context,
        )
    executor.database.close()
    return context


def test_recovery_inspection_is_read_only_and_token_bound(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite"
    _create_dispatch_committed_failure(database_path)
    controller = DurableSimulatedRecoveryController(
        mode="paper", database_path=database_path
    )
    before = controller.database.connection.total_changes

    report = controller.inspect()

    assert report["required"] is True
    assert report["resolvable"] is True
    assert len(report["confirmation_token"]) == 64
    assert report["actions"][0]["kind"] == "ABANDON_PRE_DISPATCH_SIMULATION"
    assert report["mutated"] is False
    assert controller.database.connection.total_changes == before
    assert (
        controller.database.connection.execute(
            "SELECT COUNT(*) FROM recovery_states"
        ).fetchone()[0]
        == 0
    )


def test_wrong_recovery_token_has_zero_mutation(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite"
    _create_dispatch_committed_failure(database_path)
    controller = DurableSimulatedRecoveryController(
        mode="paper", database_path=database_path
    )
    before = list(controller.database.connection.iterdump())

    with pytest.raises(DurableRecoveryError, match="token"):
        controller.resolve(confirmation_token="0" * 64, reason="operator review")

    assert list(controller.database.connection.iterdump()) == before


def test_recovery_reason_rejects_secret_markers_with_zero_mutation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite"
    _create_dispatch_committed_failure(database_path)
    controller = DurableSimulatedRecoveryController(
        mode="paper", database_path=database_path
    )
    report = controller.inspect()
    before = list(controller.database.connection.iterdump())

    with pytest.raises(DurableRecoveryError, match="secret markers"):
        controller.resolve(
            confirmation_token=report["confirmation_token"],
            reason="password was pasted here",
        )

    assert list(controller.database.connection.iterdump()) == before


def test_confirmed_recovery_is_atomic_audited_and_unblocks_runtime(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "runtime.sqlite"
    context = _create_dispatch_committed_failure(database_path)
    controller = DurableSimulatedRecoveryController(
        mode="paper", database_path=database_path
    )
    report = controller.inspect()

    result = controller.resolve(
        confirmation_token=report["confirmation_token"],
        reason="reviewed simulated pre-dispatch failure",
    )

    assert result["status"] == "RESOLVED"
    assert result["live"] == "FORBIDDEN"
    assert result["external_reconciliation"] is False
    connection = controller.database.connection
    assert (
        connection.execute("SELECT status FROM execution_states").fetchone()[0]
        == "TERMINAL"
    )
    attempt = connection.execute(
        "SELECT status,error_class FROM dispatch_attempts"
    ).fetchone()
    assert tuple(attempt) == ("REJECTED", "SIMULATION_ABORTED_BY_OPERATOR")
    cycle = connection.execute(
        "SELECT status,last_error FROM runtime_cycles WHERE cycle_id=?",
        (context["cycle_id"],),
    ).fetchone()
    assert cycle["status"] == "COMPLETED"
    assert cycle["last_error"].startswith("RECOVERED_BY_OPERATOR:")
    journal = connection.execute(
        "SELECT from_state,to_state FROM cycle_journal WHERE cycle_id=?",
        (context["cycle_id"],),
    ).fetchone()
    assert tuple(journal) == ("RISK_DECIDED", "COMPLETED")
    recovery = connection.execute(
        "SELECT status,recovered_at FROM recovery_states"
    ).fetchone()
    assert recovery["status"] == "RESOLVED"
    assert recovery["recovered_at"]
    controller.database.close()

    restarted = DurableSimulatedExecutor(mode="paper", database_path=database_path)
    assert restarted.recovery_report()["required"] is False


def test_authoritative_fill_only_requires_cycle_completion(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite"
    executor = DurableSimulatedExecutor(mode="paper", database_path=database_path)
    observed_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    context = {
        "session_id": "session-filled-recovery",
        "session_started_at": observed_at,
        "cycle_id": "cycle-filled-recovery",
        "mode": "paper",
        "observed_at": observed_at,
    }

    def fail_cycle_completion(*_: object) -> None:
        raise RuntimeError("injected after authoritative fill")

    executor._complete_cycle = fail_cycle_completion
    with pytest.raises(RuntimeError, match="after authoritative fill"):
        executor.execute(
            _approved_intent(),
            _approved_risk(),
            mark_price=100.0,
            equity_usdt=1000.0,
            execution_context=context,
        )
    executor.database.close()

    controller = DurableSimulatedRecoveryController(
        mode="paper", database_path=database_path
    )
    report = controller.inspect()
    assert report["resolvable"] is True
    assert report["actions"] == [
        {
            "kind": "COMPLETE_AUTHORITATIVE_CYCLE",
            "session_id": context["session_id"],
            "cycle_id": context["cycle_id"],
            "execution_intent_id": report["snapshot"]["executions"][0][
                "execution_intent_id"
            ],
            "attempt_id": report["snapshot"]["executions"][0]["last_attempt_id"],
        }
    ]
    before = controller.database.connection.execute(
        "SELECT status FROM execution_states"
    ).fetchone()[0]

    controller.resolve(
        confirmation_token=report["confirmation_token"],
        reason="authoritative fill reviewed",
    )

    assert before == "FILLED"
    assert (
        controller.database.connection.execute(
            "SELECT status FROM execution_states"
        ).fetchone()[0]
        == "FILLED"
    )
    assert controller.inspect()["snapshot"]["executions"] == []


def test_unsupported_prepared_state_stays_locked(tmp_path: Path) -> None:
    database_path = tmp_path / "runtime.sqlite"
    executor = DurableSimulatedExecutor(mode="paper", database_path=database_path)
    observed_at = datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")
    context = {
        "session_id": "session-prepared",
        "session_started_at": observed_at,
        "cycle_id": "cycle-prepared",
        "mode": "paper",
        "observed_at": observed_at,
    }
    original = executor._idempotency.commit_dispatch

    def fail_before_dispatch(_: object) -> None:
        raise RuntimeError("injected before dispatch commit")

    executor._idempotency.commit_dispatch = fail_before_dispatch
    with pytest.raises(RuntimeError, match="before dispatch commit"):
        executor.execute(
            _approved_intent(),
            _approved_risk(),
            mark_price=100.0,
            equity_usdt=1000.0,
            execution_context=context,
        )
    executor._idempotency.commit_dispatch = original
    executor.database.close()
    controller = DurableSimulatedRecoveryController(
        mode="paper", database_path=database_path
    )
    report = controller.inspect()
    assert report["required"] is True
    assert report["resolvable"] is False
    assert any("PREPARED" in error for error in report["errors"])
    with pytest.raises(DurableRecoveryError, match="locked"):
        controller.resolve(
            confirmation_token=report["confirmation_token"], reason="must not guess"
        )


def test_live_recovery_is_forbidden_before_database_access(tmp_path: Path) -> None:
    database_path = tmp_path / "must-not-exist.sqlite"
    with pytest.raises(DurableRecoveryError, match="Live recovery is forbidden"):
        DurableSimulatedRecoveryController(mode="live", database_path=database_path)
    assert not database_path.exists()
