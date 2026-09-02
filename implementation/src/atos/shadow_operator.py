"""Read-only operator status for the public-data Shadow supervisor.

This module observes the supervisor health snapshot, its kernel process lock,
and the canonical runtime session.  It never starts or stops a process, opens
an exchange client, mutates SQLite, or authorizes Live trading.  Any source
ambiguity is reported as HOLD.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import sqlite3
import stat
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atos.shadow_supervisor import LIVE
from atos.shadow_supervisor import SCHEMA_VERSION as HEALTH_SCHEMA_VERSION

SCHEMA_VERSION = "shadow_operator_status.v1"
MAX_HEALTH_BYTES = 64 * 1024
MAX_LOCK_BYTES = 256
SESSION_PATTERN = re.compile(r"session_[0-9a-f]{16}\Z")
SAFE_STOP_REASONS = frozenset({"OPERATOR_STOP", "BOUNDED_COMPLETE"})
EXPECTED_RUNTIME_SESSION_COLUMNS = (
    "session_id",
    "started_at",
    "mode",
    "status",
    "stopped_at",
    "stop_reason",
)


class ShadowOperatorError(RuntimeError):
    """Operator status could not prove a safe, coherent Shadow state."""


def _utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ShadowOperatorError(f"{label.upper()}_INVALID")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ShadowOperatorError(f"{label.upper()}_INVALID") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShadowOperatorError(f"{label.upper()}_INVALID")
    if parsed.utcoffset() != parsed.astimezone(UTC).utcoffset():
        raise ShadowOperatorError(f"{label.upper()}_NOT_UTC")
    return parsed.astimezone(UTC)


def _regular_file_bytes(path: Path, *, label: str, limit: int) -> bytes:
    if path.is_symlink():
        raise ShadowOperatorError(f"{label}_SYMLINK_FORBIDDEN")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ShadowOperatorError(f"{label}_UNAVAILABLE") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ShadowOperatorError(f"{label}_NOT_REGULAR")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ShadowOperatorError(f"{label}_TOO_LARGE")
        return raw
    finally:
        os.close(descriptor)


def _health(path: Path) -> dict[str, Any]:
    raw = _regular_file_bytes(path, label="HEALTH", limit=MAX_HEALTH_BYTES)
    try:
        payload = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowOperatorError("HEALTH_JSON_INVALID") from exc
    if not isinstance(payload, dict):
        raise ShadowOperatorError("HEALTH_NOT_OBJECT")
    return payload


def _lock_status(path: Path) -> tuple[bool, str]:
    """Return whether another process holds the supervisor's exclusive lock."""
    if path.is_symlink():
        raise ShadowOperatorError("LOCK_SYMLINK_FORBIDDEN")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ShadowOperatorError("LOCK_UNAVAILABLE") from exc
    acquired = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ShadowOperatorError("LOCK_NOT_REGULAR")
        raw = os.read(descriptor, MAX_LOCK_BYTES + 1)
        if len(raw) > MAX_LOCK_BYTES:
            raise ShadowOperatorError("LOCK_TOO_LARGE")
        try:
            session_id = raw.decode("utf-8").strip()
        except UnicodeError as exc:
            raise ShadowOperatorError("LOCK_SESSION_INVALID") from exc
        if not SESSION_PATTERN.fullmatch(session_id):
            raise ShadowOperatorError("LOCK_SESSION_INVALID")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            return True, session_id
        return False, session_id
    finally:
        if acquired:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _runtime_session(path: Path, session_id: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ShadowOperatorError("DATABASE_SYMLINK_FORBIDDEN")
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise ShadowOperatorError("DATABASE_UNAVAILABLE") from exc
    if not resolved.is_file():
        raise ShadowOperatorError("DATABASE_NOT_REGULAR")
    encoded = urllib.parse.quote(str(resolved), safe="/")
    try:
        connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise ShadowOperatorError("DATABASE_NOT_QUERY_ONLY")
        columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(runtime_sessions)")
        )
        if columns != EXPECTED_RUNTIME_SESSION_COLUMNS:
            raise ShadowOperatorError("DATABASE_SCHEMA_DRIFT")
        row = connection.execute(
            "SELECT session_id,started_at,mode,status,stopped_at,stop_reason "
            "FROM runtime_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
    except sqlite3.Error as exc:
        raise ShadowOperatorError("DATABASE_READ_FAILED") from exc
    finally:
        if "connection" in locals():
            connection.close()
    if row is None:
        raise ShadowOperatorError("RUNTIME_SESSION_MISSING")
    return dict(row)


def _non_negative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ShadowOperatorError(f"{label}_INVALID")
    return value


def inspect_shadow_status(
    policy: dict[str, Any],
    *,
    health_path: str | Path,
    database_path: str | Path,
    max_heartbeat_age_seconds: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return one fail-closed, read-only operator assessment."""
    assessed_at = (now or datetime.now(tz=UTC)).astimezone(UTC)
    report: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "assessed_at": assessed_at.isoformat(),
        "operational_state": "HOLD",
        "reason": "STATUS_UNAVAILABLE",
        "trade_action": "HOLD",
        "session_id": None,
        "health_state": None,
        "heartbeat_age_seconds": None,
        "process_lock_held": None,
        "persisted_session_status": None,
        "errors": [],
        "mode": "shadow",
        "public_data_only": True,
        "account_access": False,
        "private_api": False,
        "external_execution": False,
        "automatic_restart": False,
        "authorizes_live": False,
        "live": LIVE,
    }
    try:
        if not isinstance(policy, dict):
            raise ShadowOperatorError("POLICY_NOT_OBJECT")
        if policy.get("live_enabled") is not False:
            raise ShadowOperatorError("LIVE_NOT_DISABLED")
        if policy.get("public_data_only") is not True:
            raise ShadowOperatorError("PUBLIC_DATA_ONLY_NOT_PROVEN")
        persistence = policy.get("persistence")
        if not isinstance(persistence, dict) or persistence.get("enabled") is not True:
            raise ShadowOperatorError("PERSISTENCE_NOT_ENABLED")
        configured_database = persistence.get("database_path")
        if not isinstance(configured_database, str) or not configured_database.strip():
            raise ShadowOperatorError("DATABASE_PATH_INVALID")
        if Path(configured_database).resolve() != Path(database_path).resolve():
            raise ShadowOperatorError("DATABASE_PATH_MISMATCH")
        if (
            isinstance(max_heartbeat_age_seconds, bool)
            or not isinstance(max_heartbeat_age_seconds, (int, float))
            or not math.isfinite(float(max_heartbeat_age_seconds))
            or max_heartbeat_age_seconds <= 0
        ):
            raise ShadowOperatorError("HEARTBEAT_THRESHOLD_INVALID")

        health = _health(Path(health_path))
        if health.get("schema_version") != HEALTH_SCHEMA_VERSION:
            raise ShadowOperatorError("HEALTH_SCHEMA_MISMATCH")
        exact_safety = {
            "mode": "shadow",
            "public_data_only": True,
            "account_access": False,
            "private_api": False,
            "external_execution": False,
            "automatic_restart": False,
            "single_process_lock": True,
            "live": LIVE,
        }
        if any(health.get(key) != value for key, value in exact_safety.items()):
            raise ShadowOperatorError("HEALTH_SAFETY_BOUNDARY_INVALID")

        session_id = health.get("session_id")
        if not isinstance(session_id, str) or not SESSION_PATTERN.fullmatch(session_id):
            raise ShadowOperatorError("HEALTH_SESSION_INVALID")
        report["session_id"] = session_id
        state = health.get("state")
        reason = health.get("reason")
        if not isinstance(state, str) or not isinstance(reason, str):
            raise ShadowOperatorError("HEALTH_STATE_INVALID")
        report["health_state"] = state
        symbols = health.get("symbols")
        allowed_symbols = policy.get("allowed_symbols")
        if (
            not isinstance(symbols, list)
            or not symbols
            or any(not isinstance(item, str) for item in symbols)
            or len(set(symbols)) != len(symbols)
            or not isinstance(allowed_symbols, list)
            or any(not isinstance(item, str) for item in allowed_symbols)
            or not set(symbols).issubset(set(allowed_symbols))
        ):
            raise ShadowOperatorError("HEALTH_SYMBOLS_INVALID")
        cycles = _non_negative_int(health.get("cycles_completed"), "CYCLES")
        heartbeats = _non_negative_int(
            health.get("heartbeat_sequence"), "HEARTBEAT_SEQUENCE"
        )
        _non_negative_int(health.get("loops_completed"), "LOOPS")
        _non_negative_int(health.get("total_failures"), "TOTAL_FAILURES")
        _non_negative_int(health.get("consecutive_failures"), "CONSECUTIVE_FAILURES")
        if cycles != heartbeats:
            raise ShadowOperatorError("HEARTBEAT_SEQUENCE_MISMATCH")
        started_at = _utc(health.get("started_at"), "HEALTH_STARTED_AT")
        updated_at = _utc(health.get("updated_at"), "HEALTH_UPDATED_AT")
        if updated_at < started_at:
            raise ShadowOperatorError("HEALTH_TIME_ORDER_INVALID")
        age = (assessed_at - updated_at).total_seconds()
        if not math.isfinite(age) or age < 0:
            raise ShadowOperatorError("HEALTH_CLOCK_INVALID")
        report["heartbeat_age_seconds"] = age

        lock_path = Path(database_path).with_name(
            Path(database_path).name + ".shadow.lock"
        )
        lock_held, lock_session_id = _lock_status(lock_path)
        report["process_lock_held"] = lock_held
        if lock_session_id != session_id:
            raise ShadowOperatorError("LOCK_SESSION_MISMATCH")
        runtime = _runtime_session(Path(database_path), session_id)
        report["persisted_session_status"] = runtime.get("status")
        if runtime.get("mode") != "shadow":
            raise ShadowOperatorError("RUNTIME_MODE_INVALID")
        if _utc(runtime.get("started_at"), "RUNTIME_STARTED_AT") != started_at:
            raise ShadowOperatorError("RUNTIME_START_MISMATCH")

        recovery_required = health.get("recovery_required")
        if type(recovery_required) is not bool:
            raise ShadowOperatorError("RECOVERY_FLAG_INVALID")
        if state == "RUNNING":
            if reason != "ACTIVE" or recovery_required:
                raise ShadowOperatorError("RUNNING_HEALTH_INVALID")
            if not lock_held:
                raise ShadowOperatorError("RUNNING_PROCESS_NOT_LOCKED")
            if runtime.get("status") != "RUNNING":
                raise ShadowOperatorError("RUNNING_RUNTIME_MISMATCH")
            if health.get("stopped_at") is not None:
                raise ShadowOperatorError("RUNNING_STOP_TIME_PRESENT")
            if age > float(max_heartbeat_age_seconds):
                raise ShadowOperatorError("HEARTBEAT_STALE")
            report["operational_state"] = "RUNNING"
            report["reason"] = "HEALTHY"
        elif state == "STOPPED":
            if lock_held:
                raise ShadowOperatorError("STOPPED_PROCESS_STILL_LOCKED")
            if runtime.get("status") != "STOPPED":
                raise ShadowOperatorError("STOPPED_RUNTIME_MISMATCH")
            stopped_at = _utc(health.get("stopped_at"), "HEALTH_STOPPED_AT")
            if stopped_at < updated_at:
                raise ShadowOperatorError("STOP_TIME_ORDER_INVALID")
            if _utc(runtime.get("stopped_at"), "RUNTIME_STOPPED_AT") != stopped_at:
                raise ShadowOperatorError("RUNTIME_STOP_MISMATCH")
            if reason in SAFE_STOP_REASONS and runtime.get("stop_reason") == reason:
                report["operational_state"] = "STOPPED"
                report["reason"] = reason
            elif reason == "CIRCUIT_BREAKER" and runtime.get("stop_reason") == reason:
                report["operational_state"] = "HOLD"
                report["reason"] = "CIRCUIT_BREAKER"
            else:
                raise ShadowOperatorError("STOP_REASON_INVALID")
        elif state == "PAUSED_RECOVERY_REQUIRED":
            if lock_held:
                raise ShadowOperatorError("PAUSED_PROCESS_STILL_LOCKED")
            if not recovery_required or reason != "RECOVERY_REQUIRED":
                raise ShadowOperatorError("RECOVERY_HEALTH_INVALID")
            if runtime.get("status") != "PAUSED_RECOVERY_REQUIRED":
                raise ShadowOperatorError("RECOVERY_RUNTIME_MISMATCH")
            report["operational_state"] = "RECOVERY_REQUIRED"
            report["reason"] = "RECOVERY_REQUIRED"
        else:
            raise ShadowOperatorError("HEALTH_STATE_UNSUPPORTED")
    except ShadowOperatorError as exc:
        report["errors"] = [str(exc)]
        report["operational_state"] = "HOLD"
        report["reason"] = str(exc)
    except Exception:  # noqa: BLE001 - operator boundary must fail closed
        report["errors"] = ["PROGRAM_FAILURE"]
        report["operational_state"] = "HOLD"
        report["reason"] = "PROGRAM_FAILURE"
    return report
