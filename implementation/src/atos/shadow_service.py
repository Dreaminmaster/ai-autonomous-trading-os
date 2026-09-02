"""Controlled, non-restarting background launcher for Shadow soak runs.

The service launcher binds a detached supervisor process to an exact clean Git
commit and policy hash.  Stop requests are scoped by an exclusive local launch
receipt and a unique file path; no PID signal is sent, so a recycled PID cannot
terminate an unrelated process.  The child receives only a minimal environment
and remains public-data/simulated-only.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import uuid
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atos.market import ALLOWED_BARS
from atos.shadow_supervisor import (
    LIVE,
    ShadowSupervisorError,
    validate_shadow_policy,
)

LAUNCH_SCHEMA_VERSION = "shadow_service_launch.v1"
STOP_SCHEMA_VERSION = "shadow_service_stop.v1"
RUN_ID_PATTERN = re.compile(r"shadow_service_[0-9a-f]{32}\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
MAX_CONTROL_BYTES = 64 * 1024


class ShadowServiceError(RuntimeError):
    """The requested Shadow service operation is unsafe or ambiguous."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ShadowServiceError("control payload is not canonical JSON") from exc


def _read_regular(path: Path, label: str) -> bytes:
    if path.is_symlink():
        raise ShadowServiceError(f"{label} must not be a symbolic link")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ShadowServiceError(f"{label} is unavailable") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ShadowServiceError(f"{label} must be a regular file")
        raw = os.read(descriptor, MAX_CONTROL_BYTES + 1)
        if len(raw) > MAX_CONTROL_BYTES:
            raise ShadowServiceError(f"{label} is too large")
        return raw
    finally:
        os.close(descriptor)


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowServiceError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ShadowServiceError(f"{label} must contain an object")
    return value


def _write_exclusive(path: Path, payload: dict[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise ShadowServiceError("control output already exists")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    raw = _canonical_bytes(payload)
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_CLOEXEC", 0),
            0o600,
        )
        try:
            os.write(descriptor, raw)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        try:
            os.link(temporary, path)
        except FileExistsError as exc:
            raise ShadowServiceError("control output already exists") from exc
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary.exists():
            temporary.unlink()


def _inside(path: Path, parent: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(parent.resolve()):
        raise ShadowServiceError(f"{label} must stay inside {parent}")
    return resolved


def _git_output(
    repository_root: Path,
    arguments: Sequence[str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> str:
    try:
        completed = runner(
            ["git", "-C", str(repository_root), *arguments],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ShadowServiceError("Git provenance check failed") from exc
    if completed.returncode != 0:
        raise ShadowServiceError("Git provenance check failed")
    return completed.stdout.strip()


def _verify_deployment(
    repository_root: Path,
    implementation_sha: str,
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    if not SHA_PATTERN.fullmatch(implementation_sha):
        raise ShadowServiceError("implementation SHA must be exact lowercase SHA")
    head = _git_output(repository_root, ["rev-parse", "HEAD"], runner)
    if head != implementation_sha:
        raise ShadowServiceError("implementation SHA does not match checkout HEAD")
    status = _git_output(
        repository_root,
        ["status", "--porcelain", "--untracked-files=all"],
        runner,
    )
    if status:
        raise ShadowServiceError("Shadow service requires a clean checkout")


def _runtime_path(value: object, implementation_root: Path, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ShadowServiceError(f"{label} path is invalid")
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = implementation_root / candidate
    return _inside(candidate, implementation_root / "runtime", label)


class StopRequestWatcher:
    """Fail-safe file watcher consumed by the long-running supervisor."""

    def __init__(self, path: str | Path, run_id: str) -> None:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            raise ShadowServiceError("service run id is invalid")
        self.path = Path(path)
        self.run_id = run_id

    def requested(self) -> bool:
        if not self.path.exists() and not self.path.is_symlink():
            return False
        try:
            _json_object(_read_regular(self.path, "stop request"), "stop request")
            # A file at this per-run, mode-0700 path always stops the process.
            # Invalid content must stop too; ignoring tampering would be unsafe.
            return True
        except ShadowServiceError:
            # The existence of a malformed or unsafe request is itself a
            # reason to stop; ignoring it could leave an unattended process.
            return True


def start_shadow_service(
    policy: dict[str, Any],
    *,
    policy_path: str | Path,
    repository_root: str | Path,
    implementation_sha: str,
    service_root: str | Path,
    symbols: list[str],
    bar: str,
    limit: int,
    interval_seconds: float,
    failure_threshold: int,
    python_executable: str = sys.executable,
    run_id: str | None = None,
    git_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    popen_factory: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
) -> dict[str, Any]:
    """Launch one detached, non-restarting supervisor and seal its receipt."""
    repository = Path(repository_root).resolve(strict=True)
    implementation_root = repository / "implementation"
    if not implementation_root.is_dir():
        raise ShadowServiceError("implementation directory is unavailable")
    _verify_deployment(repository, implementation_sha, git_runner)
    try:
        validate_shadow_policy({**policy, "mode": "shadow"}, symbols)
    except ShadowSupervisorError as exc:
        raise ShadowServiceError("Shadow policy safety validation failed") from exc
    if bar not in ALLOWED_BARS:
        raise ShadowServiceError("unsupported public candle bar")
    if type(limit) is not int or not 20 <= limit <= 300:
        raise ShadowServiceError("candle limit must be between 20 and 300")
    if (
        isinstance(interval_seconds, bool)
        or not isinstance(interval_seconds, (int, float))
        or not math.isfinite(float(interval_seconds))
        or interval_seconds < 0
    ):
        raise ShadowServiceError("interval_seconds must be finite and non-negative")
    if type(failure_threshold) is not int or failure_threshold < 1:
        raise ShadowServiceError("failure_threshold must be positive")
    if not isinstance(python_executable, str) or not python_executable:
        raise ShadowServiceError("Python executable is invalid")

    policy_candidate = Path(policy_path)
    if policy_candidate.is_symlink():
        raise ShadowServiceError("policy must not be a symbolic link")
    policy_resolved = policy_candidate.resolve(strict=True)
    _inside(policy_resolved, repository, "policy")
    policy_raw = _read_regular(policy_resolved, "policy")
    if _json_object(policy_raw, "policy") != policy:
        raise ShadowServiceError("loaded policy does not match policy file")

    persistence = policy.get("persistence")
    supervisor = policy.get("shadow_supervisor")
    if not isinstance(persistence, dict) or not isinstance(supervisor, dict):
        raise ShadowServiceError("Shadow persistence/supervisor policy is required")
    _runtime_path(persistence.get("database_path"), implementation_root, "database")
    _runtime_path(supervisor.get("health_path"), implementation_root, "health")
    _runtime_path(supervisor.get("ledger_path"), implementation_root, "ledger")

    runtime_root = implementation_root / "runtime"
    if runtime_root.is_symlink() or not runtime_root.resolve().is_relative_to(
        implementation_root.resolve()
    ):
        raise ShadowServiceError("runtime root must remain inside implementation")
    service_parent = Path(service_root)
    if not service_parent.is_absolute():
        service_parent = implementation_root / service_parent
    service_parent = _inside(
        service_parent, implementation_root / "runtime", "service root"
    )
    identifier = run_id or f"shadow_service_{uuid.uuid4().hex}"
    if not RUN_ID_PATTERN.fullmatch(identifier):
        raise ShadowServiceError("service run id is invalid")
    run_root = service_parent / identifier
    try:
        run_root.mkdir(parents=True, mode=0o700)
    except FileExistsError as exc:
        raise ShadowServiceError("service run directory already exists") from exc
    os.chmod(run_root, 0o700)
    receipt_path = run_root / "launch_receipt.json"
    deployed_policy_path = run_root / "deployed_policy.json"
    stop_request_path = run_root / "stop_request.json"
    log_path = run_root / "supervisor.log"
    database_path = run_root / "atos_runtime.sqlite"
    health_path = run_root / "shadow_health.json"
    ledger_path = run_root / "shadow_events.sqlite"
    deployed_policy = json.loads(json.dumps(policy, allow_nan=False))
    deployed_policy["persistence"]["database_path"] = str(database_path)
    deployed_policy["shadow_supervisor"]["health_path"] = str(health_path)
    deployed_policy["shadow_supervisor"]["ledger_path"] = str(ledger_path)
    try:
        validate_shadow_policy({**deployed_policy, "mode": "shadow"}, symbols)
    except ShadowSupervisorError as exc:  # pragma: no cover - defensive parity
        raise ShadowServiceError("deployed Shadow policy validation failed") from exc
    _write_exclusive(deployed_policy_path, deployed_policy)
    deployed_policy_raw = _read_regular(deployed_policy_path, "deployed policy")

    command = [
        python_executable,
        "-m",
        "atos.cli",
        "supervise",
        "--policy",
        str(deployed_policy_path),
        "--symbols",
        ",".join(symbols),
        "--bar",
        bar,
        "--limit",
        str(limit),
        "--interval-seconds",
        str(interval_seconds),
        "--failure-threshold",
        str(failure_threshold),
        "--max-loops",
        "0",
        "--health-path",
        str(health_path),
        "--ledger-path",
        str(ledger_path),
        "--service-run-id",
        identifier,
        "--stop-request-path",
        str(stop_request_path),
    ]
    child_environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(implementation_root / "src"),
        "PYTHONUNBUFFERED": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    descriptor = os.open(
        log_path,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "ab", closefd=False) as log_handle:
            process = popen_factory(
                command,
                cwd=implementation_root,
                env=child_environment,
                stdin=subprocess.DEVNULL,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
    except Exception:
        os.close(descriptor)
        raise
    os.close(descriptor)
    pid = getattr(process, "pid", None)
    if type(pid) is not int or pid < 1:
        raise ShadowServiceError("background process did not return a valid pid")

    receipt = {
        "schema_version": LAUNCH_SCHEMA_VERSION,
        "run_id": identifier,
        "launched_at": datetime.now(tz=UTC).isoformat(),
        "implementation_sha": implementation_sha,
        "source_policy_sha256": hashlib.sha256(policy_raw).hexdigest(),
        "deployed_policy_sha256": hashlib.sha256(deployed_policy_raw).hexdigest(),
        "source_policy_path": str(policy_resolved),
        "deployed_policy_path": str(deployed_policy_path),
        "python_executable": python_executable,
        "pid_observation_only": pid,
        "symbols": symbols,
        "bar": bar,
        "limit": limit,
        "interval_seconds": interval_seconds,
        "failure_threshold": failure_threshold,
        "health_path": str(health_path),
        "ledger_path": str(ledger_path),
        "database_path": str(database_path),
        "stop_request_path": str(stop_request_path),
        "log_path": str(log_path),
        "mode": "shadow",
        "public_data_only": True,
        "account_access": False,
        "private_api": False,
        "external_execution": False,
        "automatic_restart": False,
        "uses_pid_signal_for_stop": False,
        "authorizes_live": False,
        "live": LIVE,
    }
    try:
        _write_exclusive(receipt_path, receipt)
    except Exception:
        emergency = {
            "schema_version": STOP_SCHEMA_VERSION,
            "run_id": identifier,
            "requested_at": datetime.now(tz=UTC).isoformat(),
            "action": "STOP",
            "reason": "LAUNCH_RECEIPT_FAILURE",
            "mode": "shadow",
            "account_access": False,
            "private_api": False,
            "external_execution": False,
            "live": LIVE,
        }
        _write_exclusive(stop_request_path, emergency)
        raise
    return {
        "status": "LAUNCHED",
        "run_id": identifier,
        "pid_observation_only": pid,
        "receipt_path": str(receipt_path),
        "log_path": str(log_path),
        "trade_action": "HOLD",
        "automatic_restart": False,
        "authorizes_live": False,
        "live": LIVE,
    }


def request_shadow_service_stop(receipt_path: str | Path) -> dict[str, Any]:
    """Write an idempotent graceful stop request; never signal a PID."""
    receipt_resolved, receipt = load_shadow_service_receipt(receipt_path)
    stop_path = _receipt_run_path(receipt_resolved, receipt, "stop_request_path")
    request = {
        "schema_version": STOP_SCHEMA_VERSION,
        "run_id": receipt["run_id"],
        "requested_at": datetime.now(tz=UTC).isoformat(),
        "action": "STOP",
        "reason": "OPERATOR_REQUEST",
        "mode": "shadow",
        "account_access": False,
        "private_api": False,
        "external_execution": False,
        "live": LIVE,
    }
    if stop_path.exists() or stop_path.is_symlink():
        existing = _json_object(
            _read_regular(stop_path, "stop request"), "stop request"
        )
        stable_fields = {
            key: value for key, value in request.items() if key != "requested_at"
        }
        existing_stable = {
            key: value for key, value in existing.items() if key != "requested_at"
        }
        if existing_stable != stable_fields:
            raise ShadowServiceError("existing stop request does not match receipt")
    else:
        _write_exclusive(stop_path, request)
    return {
        "status": "STOP_REQUESTED",
        "run_id": receipt["run_id"],
        "stop_request_path": str(stop_path),
        "uses_pid_signal": False,
        "trade_action": "HOLD",
        "authorizes_live": False,
        "live": LIVE,
    }


def _receipt_run_path(receipt_path: Path, receipt: dict[str, Any], field: str) -> Path:
    value = receipt.get(field)
    if not isinstance(value, str) or not value:
        raise ShadowServiceError(f"launch receipt {field} is invalid")
    resolved = Path(value).resolve()
    if resolved.parent != receipt_path.parent:
        raise ShadowServiceError(f"launch receipt {field} escapes its run directory")
    return resolved


def load_shadow_service_receipt(
    receipt_path: str | Path,
) -> tuple[Path, dict[str, Any]]:
    """Load and validate one local service receipt without changing state."""
    receipt_candidate = Path(receipt_path)
    if receipt_candidate.is_symlink():
        raise ShadowServiceError("launch receipt must not be a symbolic link")
    receipt_resolved = receipt_candidate.resolve(strict=True)
    receipt = _json_object(
        _read_regular(receipt_resolved, "launch receipt"), "launch receipt"
    )
    if (
        receipt.get("schema_version") != LAUNCH_SCHEMA_VERSION
        or not isinstance(receipt.get("run_id"), str)
        or not RUN_ID_PATTERN.fullmatch(receipt["run_id"])
        or receipt.get("mode") != "shadow"
        or receipt.get("public_data_only") is not True
        or receipt.get("account_access") is not False
        or receipt.get("private_api") is not False
        or receipt.get("external_execution") is not False
        or receipt.get("automatic_restart") is not False
        or receipt.get("uses_pid_signal_for_stop") is not False
        or receipt.get("authorizes_live") is not False
        or receipt.get("live") != LIVE
    ):
        raise ShadowServiceError("launch receipt safety boundary is invalid")
    if receipt_resolved.name != "launch_receipt.json":
        raise ShadowServiceError("launch receipt filename is invalid")
    if receipt_resolved.parent.name != receipt["run_id"]:
        raise ShadowServiceError("launch receipt run directory is invalid")
    if not SHA_PATTERN.fullmatch(str(receipt.get("implementation_sha", ""))):
        raise ShadowServiceError("launch receipt implementation SHA is invalid")
    for field in (
        "deployed_policy_path",
        "health_path",
        "ledger_path",
        "database_path",
        "stop_request_path",
        "log_path",
    ):
        _receipt_run_path(receipt_resolved, receipt, field)
    return receipt_resolved, receipt


def shadow_service_status_context(receipt_path: str | Path) -> dict[str, Any]:
    """Resolve a status query from a validated receipt and frozen policy."""
    receipt_resolved, receipt = load_shadow_service_receipt(receipt_path)
    deployed_path = _receipt_run_path(receipt_resolved, receipt, "deployed_policy_path")
    deployed_raw = _read_regular(deployed_path, "deployed policy")
    expected_hash = receipt.get("deployed_policy_sha256")
    if (
        not isinstance(expected_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
        or hashlib.sha256(deployed_raw).hexdigest() != expected_hash
    ):
        raise ShadowServiceError("deployed policy hash does not match receipt")
    policy = _json_object(deployed_raw, "deployed policy")
    symbols = receipt.get("symbols")
    if not isinstance(symbols, list) or any(
        not isinstance(symbol, str) for symbol in symbols
    ):
        raise ShadowServiceError("launch receipt symbols are invalid")
    try:
        validate_shadow_policy({**policy, "mode": "shadow"}, symbols)
    except ShadowSupervisorError as exc:
        raise ShadowServiceError("deployed Shadow policy validation failed") from exc
    health_path = _receipt_run_path(receipt_resolved, receipt, "health_path")
    database_path = _receipt_run_path(receipt_resolved, receipt, "database_path")
    persistence = policy.get("persistence")
    supervisor = policy.get("shadow_supervisor")
    if (
        not isinstance(persistence, dict)
        or persistence.get("database_path") != str(database_path)
        or not isinstance(supervisor, dict)
        or supervisor.get("health_path") != str(health_path)
    ):
        raise ShadowServiceError("deployed policy paths do not match receipt")
    return {
        "policy": policy,
        "health_path": str(health_path),
        "database_path": str(database_path),
        "implementation_sha": receipt["implementation_sha"],
        "run_id": receipt["run_id"],
    }
