from __future__ import annotations

import fcntl
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MIGRATION_PLAN, MigrationManager
from atos.shadow_operator import inspect_shadow_status
from atos.shadow_supervisor import SupervisorProcessLock

NOW = datetime(2026, 9, 2, 4, 0, tzinfo=UTC)
SESSION_ID = "session_0123456789abcdef"


def _policy(tmp_path: Path) -> dict:
    return {
        "mode": "paper",
        "live_enabled": False,
        "public_data_only": True,
        "allowed_symbols": ["BTC-USDT", "ETH-USDT"],
        "persistence": {
            "enabled": True,
            "database_path": str(tmp_path / "runtime.sqlite"),
        },
    }


def _health(
    *,
    state: str = "RUNNING",
    reason: str = "ACTIVE",
    updated_at: datetime = NOW - timedelta(seconds=30),
    stopped_at: datetime | None = None,
    recovery_required: bool = False,
) -> dict:
    started = NOW - timedelta(hours=1)
    return {
        "schema_version": "shadow_supervisor.v1",
        "session_id": SESSION_ID,
        "symbols": ["BTC-USDT", "ETH-USDT"],
        "bar": "1m",
        "state": state,
        "reason": reason,
        "started_at": started.isoformat(),
        "updated_at": updated_at.isoformat(),
        "stopped_at": stopped_at.isoformat() if stopped_at else None,
        "heartbeat_sequence": 120,
        "loops_completed": 60,
        "cycles_completed": 120,
        "total_failures": 0,
        "consecutive_failures": 0,
        "last_status_by_symbol": {},
        "last_failure": None,
        "recovery_required": recovery_required,
        "mode": "shadow",
        "public_data_only": True,
        "account_access": False,
        "private_api": False,
        "external_execution": False,
        "automatic_restart": False,
        "single_process_lock": True,
        "live": "FORBIDDEN",
    }


def _sources(
    tmp_path: Path,
    health: dict,
    *,
    runtime_status: str = "RUNNING",
    stop_reason: str | None = None,
) -> tuple[dict, Path, Path]:
    policy = _policy(tmp_path)
    database_path = Path(policy["persistence"]["database_path"])
    database = RuntimeDatabase(database_path)
    MigrationManager(database, MIGRATION_PLAN).migrate()
    database.connection.execute(
        "INSERT INTO runtime_sessions VALUES (?,?,?,?,?,?)",
        (
            SESSION_ID,
            health["started_at"],
            "shadow",
            runtime_status,
            health["stopped_at"],
            stop_reason,
        ),
    )
    database.connection.commit()
    database.close()
    health_path = tmp_path / "health.json"
    health_path.write_text(json.dumps(health), encoding="utf-8")
    return policy, health_path, database_path


def _inspect(policy: dict, health_path: Path, database_path: Path) -> dict:
    return inspect_shadow_status(
        policy,
        health_path=health_path,
        database_path=database_path,
        max_heartbeat_age_seconds=180,
        now=NOW,
    )


def test_running_status_requires_fresh_health_runtime_and_held_lock(
    tmp_path: Path,
) -> None:
    policy, health_path, database_path = _sources(tmp_path, _health())
    lock = SupervisorProcessLock(database_path, SESSION_ID)
    lock.acquire()
    try:
        report = _inspect(policy, health_path, database_path)
    finally:
        lock.release()

    assert report["operational_state"] == "RUNNING"
    assert report["reason"] == "HEALTHY"
    assert report["heartbeat_age_seconds"] == 30
    assert report["process_lock_held"] is True
    assert report["persisted_session_status"] == "RUNNING"
    assert report["trade_action"] == "HOLD"
    assert report["account_access"] is False
    assert report["private_api"] is False
    assert report["external_execution"] is False
    assert report["authorizes_live"] is False
    assert report["live"] == "FORBIDDEN"


def test_safe_stopped_status_requires_released_lock_and_matching_runtime(
    tmp_path: Path,
) -> None:
    stopped_at = NOW - timedelta(seconds=20)
    health = _health(
        state="STOPPED",
        reason="OPERATOR_STOP",
        updated_at=stopped_at,
        stopped_at=stopped_at,
    )
    policy, health_path, database_path = _sources(
        tmp_path, health, runtime_status="STOPPED", stop_reason="OPERATOR_STOP"
    )
    lock_path = database_path.with_name(database_path.name + ".shadow.lock")
    lock_path.write_text(SESSION_ID + "\n", encoding="utf-8")

    report = _inspect(policy, health_path, database_path)

    assert report["operational_state"] == "STOPPED"
    assert report["reason"] == "OPERATOR_STOP"
    assert report["process_lock_held"] is False


def test_circuit_breaker_is_hold_not_healthy_stop(tmp_path: Path) -> None:
    stopped_at = NOW - timedelta(seconds=20)
    health = _health(
        state="STOPPED",
        reason="CIRCUIT_BREAKER",
        updated_at=stopped_at,
        stopped_at=stopped_at,
    )
    policy, health_path, database_path = _sources(
        tmp_path, health, runtime_status="STOPPED", stop_reason="CIRCUIT_BREAKER"
    )
    database_path.with_name(database_path.name + ".shadow.lock").write_text(
        SESSION_ID + "\n", encoding="utf-8"
    )

    report = _inspect(policy, health_path, database_path)

    assert report["operational_state"] == "HOLD"
    assert report["reason"] == "CIRCUIT_BREAKER"


def test_recovery_required_is_distinct_and_never_authorizes_live(
    tmp_path: Path,
) -> None:
    stopped_at = NOW - timedelta(seconds=20)
    health = _health(
        state="PAUSED_RECOVERY_REQUIRED",
        reason="RECOVERY_REQUIRED",
        updated_at=stopped_at,
        stopped_at=stopped_at,
        recovery_required=True,
    )
    policy, health_path, database_path = _sources(
        tmp_path, health, runtime_status="PAUSED_RECOVERY_REQUIRED"
    )
    database_path.with_name(database_path.name + ".shadow.lock").write_text(
        SESSION_ID + "\n", encoding="utf-8"
    )

    report = _inspect(policy, health_path, database_path)

    assert report["operational_state"] == "RECOVERY_REQUIRED"
    assert report["trade_action"] == "HOLD"
    assert report["authorizes_live"] is False


def test_stale_heartbeat_fails_closed_while_process_lock_is_held(
    tmp_path: Path,
) -> None:
    policy, health_path, database_path = _sources(
        tmp_path, _health(updated_at=NOW - timedelta(seconds=181))
    )
    lock = SupervisorProcessLock(database_path, SESSION_ID)
    lock.acquire()
    try:
        report = _inspect(policy, health_path, database_path)
    finally:
        lock.release()

    assert report["operational_state"] == "HOLD"
    assert report["reason"] == "HEARTBEAT_STALE"


def test_running_health_without_process_lock_fails_closed(tmp_path: Path) -> None:
    policy, health_path, database_path = _sources(tmp_path, _health())
    database_path.with_name(database_path.name + ".shadow.lock").write_text(
        SESSION_ID + "\n", encoding="utf-8"
    )

    report = _inspect(policy, health_path, database_path)

    assert report["operational_state"] == "HOLD"
    assert report["reason"] == "RUNNING_PROCESS_NOT_LOCKED"


def test_lock_session_mismatch_fails_closed(tmp_path: Path) -> None:
    policy, health_path, database_path = _sources(tmp_path, _health())
    lock_path = database_path.with_name(database_path.name + ".shadow.lock")
    lock_path.write_text("session_ffffffffffffffff\n", encoding="utf-8")

    report = _inspect(policy, health_path, database_path)

    assert report["reason"] == "LOCK_SESSION_MISMATCH"


def test_health_safety_tamper_fails_closed(tmp_path: Path) -> None:
    health = _health()
    health["account_access"] = True
    policy, health_path, database_path = _sources(tmp_path, health)
    database_path.with_name(database_path.name + ".shadow.lock").write_text(
        SESSION_ID + "\n", encoding="utf-8"
    )

    report = _inspect(policy, health_path, database_path)

    assert report["reason"] == "HEALTH_SAFETY_BOUNDARY_INVALID"
    assert report["account_access"] is False


def test_malformed_policy_symbols_fail_closed_without_exception(tmp_path: Path) -> None:
    policy, health_path, database_path = _sources(tmp_path, _health())
    policy["allowed_symbols"] = [{"symbol": "BTC-USDT"}]
    database_path.with_name(database_path.name + ".shadow.lock").write_text(
        SESSION_ID + "\n", encoding="utf-8"
    )

    report = _inspect(policy, health_path, database_path)

    assert report["operational_state"] == "HOLD"
    assert report["reason"] == "HEALTH_SYMBOLS_INVALID"
    assert report["trade_action"] == "HOLD"


def test_health_symlink_and_database_path_mismatch_fail_closed(
    tmp_path: Path,
) -> None:
    policy, health_path, database_path = _sources(tmp_path, _health())
    target = tmp_path / "target-health.json"
    health_path.rename(target)
    health_path.symlink_to(target)
    report = _inspect(policy, health_path, database_path)
    assert report["reason"] == "HEALTH_SYMLINK_FORBIDDEN"

    report = inspect_shadow_status(
        policy,
        health_path=target,
        database_path=tmp_path / "other.sqlite",
        max_heartbeat_age_seconds=180,
        now=NOW,
    )
    assert report["reason"] == "DATABASE_PATH_MISMATCH"


def test_status_probe_never_steals_or_releases_supervisor_lock(tmp_path: Path) -> None:
    policy, health_path, database_path = _sources(tmp_path, _health())
    lock = SupervisorProcessLock(database_path, SESSION_ID)
    lock.acquire()
    try:
        assert _inspect(policy, health_path, database_path)["process_lock_held"] is True
        probe = os.open(
            database_path.with_name(database_path.name + ".shadow.lock"), os.O_RDONLY
        )
        try:
            try:
                fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                acquired = False
        finally:
            os.close(probe)
        assert acquired is False
    finally:
        lock.release()
