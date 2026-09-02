"""Fail-closed long-running supervisor for public-data Shadow operation.

The supervisor owns process-level liveness, bounded failure handling, durable
health reporting, and graceful stop behavior.  It only drives the existing
public-data Shadow runtime.  It has no account client, private API, exchange
order method, Paper mode, Live mode, or automatic restart path.
"""

from __future__ import annotations

import fcntl
import json
import math
import os
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from time import sleep
from typing import Any

from atos.core import utc_now
from atos.durable_execution import DurableSimulatedExecutor
from atos.ledger import Ledger
from atos.market import ALLOWED_BARS, PublicMarketAdapter
from atos.runtime import AutonomousRuntime

LIVE = "FORBIDDEN"
SCHEMA_VERSION = "shadow_supervisor.v1"
TERMINAL_STATES = frozenset(
    {"OPERATOR_STOP", "BOUNDED_COMPLETE", "CIRCUIT_BREAKER", "RECOVERY_REQUIRED"}
)


class ShadowSupervisorError(RuntimeError):
    """The requested Shadow supervision state is unsafe or invalid."""


@dataclass
class ShadowHealth:
    session_id: str
    symbols: list[str]
    bar: str
    state: str = "STARTING"
    reason: str = "INITIALIZING"
    started_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    stopped_at: str | None = None
    heartbeat_sequence: int = 0
    loops_completed: int = 0
    cycles_completed: int = 0
    total_failures: int = 0
    consecutive_failures: int = 0
    last_status_by_symbol: dict[str, str] = field(default_factory=dict)
    last_failure: dict[str, str] | None = None
    recovery_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            **asdict(self),
            "mode": "shadow",
            "public_data_only": True,
            "account_access": False,
            "private_api": False,
            "external_execution": False,
            "automatic_restart": False,
            "single_process_lock": True,
            "live": LIVE,
        }


class AtomicHealthWriter:
    """Atomically replace one local JSON health snapshot."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, payload: dict[str, Any]) -> None:
        if self.path.exists() and self.path.is_symlink():
            raise ShadowSupervisorError("health path must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        data = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        try:
            with temporary.open("x", encoding="utf-8") as handle:
                handle.write(data + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            directory = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if temporary.exists():
                temporary.unlink()


class SupervisorProcessLock:
    """Non-blocking OS lock bound to the canonical runtime database."""

    def __init__(self, database_path: str | Path, session_id: str) -> None:
        database = Path(database_path)
        self.path = database.with_name(database.name + ".shadow.lock")
        self.session_id = session_id
        self._handle: Any | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            raise ShadowSupervisorError("supervisor process lock is already held")
        if self.path.exists() and self.path.is_symlink():
            raise ShadowSupervisorError("supervisor lock path must not be a symlink")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path,
            os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW,
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        handle = os.fdopen(descriptor, "r+", encoding="utf-8")
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            handle.seek(0)
            handle.truncate()
            handle.write(self.session_id + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        except BlockingIOError as exc:
            handle.close()
            raise ShadowSupervisorError(
                "another Shadow supervisor holds the runtime database lock"
            ) from exc
        except Exception:
            handle.close()
            raise
        self._handle = handle

    def release(self) -> None:
        if self._handle is None:
            return
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


def validate_shadow_policy(policy: dict[str, Any], symbols: list[str]) -> None:
    """Reject unsafe supervisor configuration before runtime construction."""
    if not isinstance(policy, dict):
        raise ShadowSupervisorError("policy must be an object")
    if policy.get("mode") != "shadow":
        raise ShadowSupervisorError("supervisor requires explicit Shadow mode")
    if policy.get("live_enabled") is not False:
        raise ShadowSupervisorError("Live must be explicitly disabled")
    if policy.get("public_data_only") is not True:
        raise ShadowSupervisorError("supervisor requires public_data_only=true")
    persistence = policy.get("persistence")
    if not isinstance(persistence, dict) or persistence.get("enabled") is not True:
        raise ShadowSupervisorError("durable persistence must be enabled")
    database_path = persistence.get("database_path")
    if not isinstance(database_path, str) or not database_path.strip():
        raise ShadowSupervisorError("durable database_path is required")
    allowed_characters = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-")
    if not symbols or any(
        not isinstance(symbol, str)
        or not symbol
        or symbol != symbol.strip()
        or len(symbol) > 64
        or any(character not in allowed_characters for character in symbol)
        for symbol in symbols
    ):
        raise ShadowSupervisorError("at least one valid symbol is required")
    if len(set(symbols)) != len(symbols):
        raise ShadowSupervisorError("duplicate symbols are forbidden")
    allowed = policy.get("allowed_symbols")
    if (
        not isinstance(allowed, list)
        or any(not isinstance(symbol, str) for symbol in allowed)
        or not set(symbols).issubset(set(allowed))
    ):
        raise ShadowSupervisorError("supervisor symbols must be policy-allowlisted")


class ShadowSupervisor:
    """Drive one durable public-data Shadow runtime until a safe stop."""

    def __init__(
        self,
        runtime: AutonomousRuntime,
        *,
        symbols: list[str],
        health_path: str | Path,
        bar: str = "1m",
        limit: int = 100,
        interval_seconds: float = 60.0,
        failure_threshold: int = 3,
        sleep_fn: Callable[[float], None] = sleep,
    ) -> None:
        validate_shadow_policy(runtime.policy, symbols)
        if runtime.mode != "shadow":
            raise ShadowSupervisorError("runtime mode must be Shadow")
        if not isinstance(runtime.market_adapter, PublicMarketAdapter):
            raise ShadowSupervisorError("official public market adapter is required")
        if not isinstance(runtime.executor, DurableSimulatedExecutor):
            raise ShadowSupervisorError("durable Shadow executor is required")
        if runtime.executor.mode != "shadow":
            raise ShadowSupervisorError("executor mode must be Shadow")
        if bar not in ALLOWED_BARS:
            raise ShadowSupervisorError("unsupported public candle bar")
        if type(limit) is not int or not 20 <= limit <= 300:
            raise ShadowSupervisorError("candle limit must be between 20 and 300")
        if (
            isinstance(interval_seconds, bool)
            or not isinstance(interval_seconds, (int, float))
            or not math.isfinite(float(interval_seconds))
            or interval_seconds < 0
        ):
            raise ShadowSupervisorError(
                "interval_seconds must be finite and non-negative"
            )
        if type(failure_threshold) is not int or failure_threshold < 1:
            raise ShadowSupervisorError("failure_threshold must be a positive integer")
        self.runtime = runtime
        self.symbols = list(symbols)
        self.bar = bar
        self.limit = limit
        self.interval_seconds = float(interval_seconds)
        self.failure_threshold = failure_threshold
        self.health = ShadowHealth(
            session_id=runtime.session_id,
            symbols=list(symbols),
            bar=bar,
            started_at=runtime.session_started_at,
            updated_at=runtime.session_started_at,
        )
        self._health_writer = AtomicHealthWriter(health_path)
        self._sleep = sleep_fn
        self._process_lock = SupervisorProcessLock(
            runtime.executor.database.path, runtime.session_id
        )

    @staticmethod
    def _result_failure(result: object) -> str | None:
        if not isinstance(result, dict):
            return "PROGRAM_FAILURE"
        provider = result.get("provider_result")
        execution = result.get("execution")
        if not isinstance(provider, dict) or not isinstance(execution, dict):
            return "PROGRAM_FAILURE"
        validation = result.get("intent_validation")
        if not isinstance(validation, dict) or validation.get("is_valid") is not True:
            return "PROGRAM_FAILURE"
        diagnostics = result.get("strategy_diagnostics")
        if not isinstance(diagnostics, list) or any(
            not isinstance(item, dict) or item.get("status") == "PLUGIN_FAILED"
            for item in diagnostics
        ):
            return "PROGRAM_FAILURE"
        error = provider.get("error")
        if isinstance(error, str) and error:
            if error.startswith("public market acquisition failed:"):
                return "DATA_FAILURE"
            return "PROGRAM_FAILURE"
        if execution.get("mode") != "shadow":
            return "PROGRAM_FAILURE"
        return None

    def _record_health(self, kind: str) -> None:
        payload = self.health.to_dict()
        self._health_writer.write(payload)
        self.runtime.ledger.record(kind, payload)

    def _stop(self, reason: str, *, recovery_required: bool = False) -> dict[str, Any]:
        if reason not in TERMINAL_STATES:
            raise ShadowSupervisorError("invalid terminal supervisor state")
        now = utc_now()
        self.health.state = (
            "PAUSED_RECOVERY_REQUIRED" if recovery_required else "STOPPED"
        )
        self.health.reason = reason
        self.health.updated_at = now
        self.health.stopped_at = now
        self.health.recovery_required = recovery_required
        persisted = self.runtime.executor.finalize_session(
            self.runtime.session_id,
            at_utc=now,
            reason=reason,
            recovery_required=recovery_required,
        )
        self._record_health("shadow_supervisor_stopped")
        return {**self.health.to_dict(), "durable_session_status": persisted}

    def run(
        self,
        *,
        max_loops: int | None = None,
        stop_requested: Callable[[], bool] = lambda: False,
    ) -> dict[str, Any]:
        if max_loops is not None and (type(max_loops) is not int or max_loops < 1):
            raise ShadowSupervisorError("max_loops must be positive or None")
        self._process_lock.acquire()
        try:
            return self._run_locked(max_loops=max_loops, stop_requested=stop_requested)
        finally:
            self._process_lock.release()

    def _run_locked(
        self,
        *,
        max_loops: int | None,
        stop_requested: Callable[[], bool],
    ) -> dict[str, Any]:
        recovery = self.runtime.executor.recovery_report()
        if recovery["required"]:
            self.health.last_failure = {
                "classification": "RECOVERY_REQUIRED",
                "symbol": "",
            }
            return self._stop("RECOVERY_REQUIRED", recovery_required=True)

        self.health.state = "RUNNING"
        self.health.reason = "ACTIVE"
        self.health.updated_at = utc_now()
        self._record_health("shadow_supervisor_started")

        while max_loops is None or self.health.loops_completed < max_loops:
            if stop_requested():
                return self._stop("OPERATOR_STOP")
            completed_iteration = True
            for symbol in self.symbols:
                if stop_requested():
                    completed_iteration = False
                    break
                classification: str | None = None
                result: object = None
                try:
                    result = self.runtime.run_public_once(
                        symbol, bar=self.bar, limit=self.limit
                    )
                    recovery = self.runtime.executor.recovery_report()
                    classification = (
                        "RECOVERY_REQUIRED"
                        if recovery["required"]
                        else self._result_failure(result)
                    )
                except Exception:  # noqa: BLE001 - process boundary fails closed
                    recovery = self.runtime.executor.recovery_report()
                    classification = (
                        "RECOVERY_REQUIRED"
                        if recovery["required"]
                        else "PROGRAM_FAILURE"
                    )

                self.health.cycles_completed += 1
                self.health.heartbeat_sequence += 1
                self.health.updated_at = utc_now()
                if isinstance(result, dict) and isinstance(
                    result.get("execution"), dict
                ):
                    self.health.last_status_by_symbol[symbol] = str(
                        result["execution"].get("status", "INVALID")
                    )
                else:
                    self.health.last_status_by_symbol[symbol] = "PROGRAM_FAILURE"

                if classification is None:
                    self.health.consecutive_failures = 0
                    self.health.last_failure = None
                else:
                    self.health.total_failures += 1
                    self.health.consecutive_failures += 1
                    self.health.last_failure = {
                        "classification": classification,
                        "symbol": symbol,
                    }
                    self.runtime.ledger.record(
                        "shadow_supervisor_failure",
                        {
                            "session_id": self.runtime.session_id,
                            "classification": classification,
                            "symbol": symbol,
                            "consecutive_failures": self.health.consecutive_failures,
                            "mode": "shadow",
                            "public_data_only": True,
                            "account_access": False,
                            "private_api": False,
                            "external_execution": False,
                            "automatic_restart": False,
                            "single_process_lock": True,
                            "live": LIVE,
                        },
                    )
                self._record_health("shadow_supervisor_heartbeat")

                if classification == "RECOVERY_REQUIRED":
                    return self._stop("RECOVERY_REQUIRED", recovery_required=True)
                if self.health.consecutive_failures >= self.failure_threshold:
                    return self._stop("CIRCUIT_BREAKER")

            if not completed_iteration:
                return self._stop("OPERATOR_STOP")
            self.health.loops_completed += 1
            if stop_requested():
                return self._stop("OPERATOR_STOP")
            if max_loops is not None and self.health.loops_completed >= max_loops:
                return self._stop("BOUNDED_COMPLETE")
            if self.interval_seconds > 0:
                self._sleep(self.interval_seconds)

        raise AssertionError("unreachable supervisor loop exit")


def build_shadow_supervisor(
    policy: dict[str, Any],
    *,
    symbols: list[str],
    health_path: str | Path,
    ledger_path: str | Path,
    bar: str = "1m",
    limit: int = 100,
    interval_seconds: float = 60.0,
    failure_threshold: int = 3,
    sleep_fn: Callable[[float], None] = sleep,
) -> ShadowSupervisor:
    """Build the production supervisor with the official public adapter only."""
    validate_shadow_policy(policy, symbols)
    if not str(health_path).strip() or not str(ledger_path).strip():
        raise ShadowSupervisorError("health and ledger paths are required")
    database_path = Path(str(policy["persistence"]["database_path"])).resolve()
    resolved_ledger = Path(ledger_path).resolve()
    resolved_health = Path(health_path).resolve()
    if len({database_path, resolved_ledger, resolved_health}) != 3:
        raise ShadowSupervisorError("database, ledger, and health paths must differ")
    ledger = Ledger(str(ledger_path))
    runtime = AutonomousRuntime(
        policy,
        ledger,
        market_adapter=PublicMarketAdapter(),
    )
    return ShadowSupervisor(
        runtime,
        symbols=symbols,
        health_path=health_path,
        bar=bar,
        limit=limit,
        interval_seconds=interval_seconds,
        failure_threshold=failure_threshold,
        sleep_fn=sleep_fn,
    )
