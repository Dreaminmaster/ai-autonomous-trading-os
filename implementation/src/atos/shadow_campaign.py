"""Resumable, segment-based local Shadow campaign controller.

Campaigns reuse the public-only Shadow supervisor.  They never create an
exchange/account client and never authorize external execution.  Accumulated
time is derived only from completed durable cycles that have an official OKX
public snapshot and a subsequent supervisor heartbeat.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.parse
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import Any

from atos.durable_recovery import DurableSimulatedRecoveryController
from atos.shadow_operator import inspect_shadow_status
from atos.shadow_service import (
    load_shadow_service_receipt,
    request_shadow_service_stop,
    shadow_service_status_context,
    start_shadow_service,
)
from atos.strategy_registry import create_default_registry

SCHEMA_VERSION = "shadow_campaign.v1"
EVIDENCE_SCHEMA_VERSION = "shadow_campaign_evidence.v1"
LIVE = "FORBIDDEN"
CAMPAIGN_PATTERN = re.compile(r"campaign_[0-9a-f]{32}\Z")
SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
TERMINAL_SEGMENT_STATES = frozenset(
    {"PAUSED_CLEAN", "ABORTED_UNCLEAN", "CIRCUIT_BREAKER", "RECOVERY_REQUIRED"}
)


class ShadowCampaignError(RuntimeError):
    """A Campaign action could not be completed without weakening safety."""


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


def _utc_text(value: datetime | None = None) -> str:
    return (value or _utc_now()).astimezone(UTC).isoformat()


def _parse_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value:
        raise ShadowCampaignError("timestamp is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as exc:
        raise ShadowCampaignError("timestamp is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShadowCampaignError("timestamp must be timezone-aware")
    return parsed.astimezone(UTC)


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
        raise ShadowCampaignError("campaign value is not canonical JSON") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    raw = _canonical_bytes(dict(payload))
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, raw)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise ShadowCampaignError(f"{path.name} already exists")
    _atomic_json(path, payload)


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ShadowCampaignError(f"{label} must not be a symbolic link")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowCampaignError(f"{label} is unavailable or invalid") from exc
    if not isinstance(value, dict):
        raise ShadowCampaignError(f"{label} must contain an object")
    return value


def _readonly_connection(path: Path) -> sqlite3.Connection:
    if path.is_symlink() or not path.is_file():
        raise ShadowCampaignError("SQLite source is unavailable")
    encoded = urllib.parse.quote(str(path.resolve()), safe="/")
    connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=5.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _decimal(value: object, label: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ShadowCampaignError(f"{label} is invalid") from exc
    if not result.is_finite():
        raise ShadowCampaignError(f"{label} is not finite")
    return result


def _decimal_text(value: Decimal) -> str:
    return "0" if value == 0 else format(value.normalize(), "f")


def _sqlite_backup(source: Path, destination: Path) -> None:
    if source.is_symlink() or destination.exists() or destination.is_symlink():
        raise ShadowCampaignError("SQLite backup path is unsafe")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with (
            _readonly_connection(source) as source_connection,
            sqlite3.connect(temporary, timeout=5.0) as target,
        ):
            source_connection.backup(target)
            target.commit()
        os.chmod(temporary, 0o600)
        descriptor = os.open(temporary, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()


def _strategy_version(repository_root: Path) -> str:
    paths = (
        repository_root / "implementation/src/atos/strategies.py",
        repository_root / "implementation/src/atos/strategy_registry.py",
        repository_root / "implementation/src/atos/providers/mock_provider.py",
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(repository_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    digest.update(
        _canonical_bytes({"enabled_strategy_ids": create_default_registry().enabled_ids()})
    )
    return "default-registry@" + digest.hexdigest()[:16]


def _git(repository_root: Path, *arguments: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repository_root), *arguments],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ShadowCampaignError("Git provenance check failed") from exc
    if completed.returncode != 0:
        raise ShadowCampaignError("Git provenance check failed")
    return completed.stdout.strip()


def _runtime_flush(path: Path) -> None:
    if not path.exists():
        return
    try:
        with sqlite3.connect(path, timeout=10.0) as connection:
            connection.execute("PRAGMA wal_checkpoint(FULL)")
            connection.commit()
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except (OSError, sqlite3.Error) as exc:
        raise ShadowCampaignError("SQLite flush failed") from exc


class ShadowCampaignManager:
    """Create, resume, pause, inspect, and freeze one local Campaign at a time."""

    def __init__(
        self,
        repository_root: str | Path,
        *,
        policy_path: str | Path = "implementation/config/policy.json",
        campaign_root: str | Path = "implementation/runtime/shadow_campaigns",
        launcher: Callable[..., dict[str, Any]] = start_shadow_service,
        stop_requester: Callable[[str | Path], dict[str, Any]] = request_shadow_service_stop,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.repository_root = Path(repository_root).resolve(strict=True)
        self.implementation_root = self.repository_root / "implementation"
        self.policy_path = Path(policy_path)
        if not self.policy_path.is_absolute():
            repository_candidate = self.repository_root / self.policy_path
            implementation_candidate = self.implementation_root / self.policy_path
            self.policy_path = (
                repository_candidate
                if repository_candidate.exists()
                else implementation_candidate
            )
        self.policy_path = self.policy_path.resolve(strict=True)
        root = Path(campaign_root)
        if not root.is_absolute():
            root = self.repository_root / root
        self.root = root.resolve()
        runtime_root = (self.implementation_root / "runtime").resolve()
        if not self.root.is_relative_to(runtime_root):
            raise ShadowCampaignError("campaign root must stay inside implementation/runtime")
        self.root.mkdir(parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)
        self._launcher = launcher
        self._stop_requester = stop_requester
        self._sleep = sleep_fn

    @contextmanager
    def _locked(self) -> Iterator[None]:
        path = self.root / ".campaign.lock"
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _current_path(self) -> Path | None:
        pointer_path = self.root / "current_campaign.json"
        if pointer_path.exists():
            pointer = _read_json(pointer_path, "current Campaign pointer")
            identifier = pointer.get("campaign_id")
            if isinstance(identifier, str) and CAMPAIGN_PATTERN.fullmatch(identifier):
                candidate = self.root / identifier / "campaign.json"
                if candidate.exists():
                    return candidate
        candidates = sorted(
            self.root.glob("campaign_*/campaign.json"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
        return candidates[0] if candidates else None

    def _load_current(self) -> tuple[Path, dict[str, Any]]:
        path = self._current_path()
        if path is None:
            raise ShadowCampaignError("no Campaign exists yet")
        campaign = _read_json(path, "Campaign state")
        if (
            campaign.get("schema_version") != SCHEMA_VERSION
            or not isinstance(campaign.get("campaign_id"), str)
            or not CAMPAIGN_PATTERN.fullmatch(campaign["campaign_id"])
            or path.parent.name != campaign["campaign_id"]
            or campaign.get("live") != LIVE
        ):
            raise ShadowCampaignError("Campaign state safety boundary is invalid")
        return path, campaign

    def _policy(self) -> tuple[dict[str, Any], bytes]:
        raw = self.policy_path.read_bytes()
        try:
            policy = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ShadowCampaignError("policy is invalid") from exc
        if not isinstance(policy, dict):
            raise ShadowCampaignError("policy must contain an object")
        if policy.get("live_enabled") is not False or policy.get("public_data_only") is not True:
            raise ShadowCampaignError("Campaign requires public-only policy with Live disabled")
        return policy, raw

    def _current_binding(self, *, require_clean: bool) -> dict[str, str]:
        head = _git(self.repository_root, "rev-parse", "HEAD")
        if not SHA_PATTERN.fullmatch(head):
            raise ShadowCampaignError("checkout HEAD is not an exact commit")
        if require_clean and _git(
            self.repository_root, "status", "--porcelain", "--untracked-files=all"
        ):
            raise ShadowCampaignError("Campaign start/resume requires a clean checkout")
        _, raw = self._policy()
        return {
            "implementation_sha": head,
            "policy_sha256": hashlib.sha256(raw).hexdigest(),
            "strategy_version": _strategy_version(self.repository_root),
        }

    def _assert_binding(self, campaign: Mapping[str, Any]) -> None:
        binding = self._current_binding(require_clean=True)
        expected = {
            key: campaign.get(key)
            for key in ("implementation_sha", "policy_sha256", "strategy_version")
        }
        if binding != expected:
            raise ShadowCampaignError(
                "checkout/policy/strategy changed; start a new Campaign instead"
            )

    def create(self, *, start: bool = True) -> dict[str, Any]:
        with self._locked():
            policy, policy_raw = self._policy()
            binding = self._current_binding(require_clean=True)
            identifier = f"campaign_{uuid.uuid4().hex}"
            campaign_dir = self.root / identifier
            campaign_dir.mkdir(mode=0o700)
            frozen_policy = campaign_dir / "frozen_policy.json"
            descriptor = os.open(frozen_policy, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                os.write(descriptor, policy_raw)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            evidence = policy.get("shadow_evidence")
            supervisor = policy.get("shadow_supervisor")
            if not isinstance(evidence, dict) or not isinstance(supervisor, dict):
                raise ShadowCampaignError("policy Shadow sections are required")
            now = _utc_text()
            campaign: dict[str, Any] = {
                "schema_version": SCHEMA_VERSION,
                "campaign_id": identifier,
                "state": "PAUSED",
                "created_at": now,
                "updated_at": now,
                "frozen_at": None,
                **binding,
                "frozen_policy_path": str(frozen_policy),
                "symbols": list(policy.get("allowed_symbols", [])),
                "bar": "1m",
                "limit": 100,
                "interval_seconds": float(supervisor.get("interval_seconds", 60.0)),
                "failure_threshold": int(supervisor.get("failure_threshold", 3)),
                "targets": {
                    "minimum_duration_seconds": int(evidence["minimum_duration_seconds"]),
                    "minimum_cycles": int(evidence["minimum_cycles"]),
                    "minimum_simulated_fills": int(evidence["minimum_simulated_fills"]),
                    "max_failure_rate": float(evidence["max_failure_rate"]),
                    "max_heartbeat_gap_seconds": float(evidence["max_heartbeat_gap_seconds"]),
                    "max_equity_drawdown_pct": float(evidence["max_equity_drawdown_pct"]),
                    "require_positive_net_pnl": bool(evidence["require_positive_net_pnl"]),
                },
                "segments": [],
                "active_segment_id": None,
                "safe_to_power_off": True,
                "public_data_only": True,
                "account_access": False,
                "private_api": False,
                "external_execution": False,
                "authorizes_live": False,
                "live": LIVE,
            }
            state_path = campaign_dir / "campaign.json"
            _exclusive_json(state_path, campaign)
            _atomic_json(self.root / "current_campaign.json", {"campaign_id": identifier})
            if start:
                return self._resume_unlocked(state_path, campaign)
            return self._status_unlocked(state_path, campaign)

    def _receipt_paths(self, segment: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
        receipt_path, receipt = load_shadow_service_receipt(str(segment["receipt_path"]))
        return receipt_path, receipt

    def _prepare_unclean_seed(
        self, campaign_path: Path, segment: dict[str, Any], receipt: Mapping[str, Any]
    ) -> tuple[Path, Path, dict[str, Any]]:
        sequence = len(_read_json(campaign_path, "Campaign state")["segments"]) + 1
        seed_dir = (
            campaign_path.parent
            / "recovery_seeds"
            / f"segment_{sequence:04d}_{uuid.uuid4().hex}"
        )
        seed_dir.mkdir(parents=True, mode=0o700)
        database = seed_dir / "atos_runtime.sqlite"
        ledger = seed_dir / "shadow_events.sqlite"
        _sqlite_backup(Path(str(receipt["database_path"])), database)
        _sqlite_backup(Path(str(receipt["ledger_path"])), ledger)
        controller = DurableSimulatedRecoveryController(mode="shadow", database_path=database)
        try:
            report = controller.inspect()
            resolved: dict[str, Any] | None = None
            if report["required"]:
                if not report["resolvable"]:
                    raise ShadowCampaignError(
                        "unclean Segment has an unresolved durable state; Campaign remains HOLD"
                    )
                resolved = controller.resolve(
                    confirmation_token=report["confirmation_token"],
                    reason="CAMPAIGN_RESUME_AFTER_UNCLEAN",
                )
            session_id = segment.get("session_id")
            cutoff = segment.get("last_valid_heartbeat") or segment.get("ended_at")
            if isinstance(session_id, str) and isinstance(cutoff, str):
                with controller.database.transaction(immediate=True) as connection:
                    connection.execute(
                        "UPDATE runtime_sessions SET status='STOPPED',stopped_at=?,stop_reason=? "
                        "WHERE session_id=? AND status IN ('RUNNING','PAUSED_RECOVERY_REQUIRED')",
                        (cutoff, "ABORTED_UNCLEAN", session_id),
                    )
        finally:
            controller.database.close()
        _runtime_flush(database)
        _runtime_flush(ledger)
        recovery = {
            "kind": "DERIVED_UNCLEAN_RECOVERY",
            "source_segment_id": segment["segment_id"],
            "source_database_sha256": _sha256_file(Path(str(receipt["database_path"]))),
            "source_ledger_sha256": _sha256_file(Path(str(receipt["ledger_path"]))),
            "derived_database_sha256": _sha256_file(database),
            "derived_ledger_sha256": _sha256_file(ledger),
            "durable_recovery_required": bool(report["required"]),
            "durable_recovery_actions": 0 if resolved is None else len(resolved["resolved_actions"]),
            "mutates_original_segment": False,
            "external_reconciliation": False,
            "live": LIVE,
        }
        return database, ledger, recovery

    def _resume_unlocked(
        self, campaign_path: Path, campaign: dict[str, Any]
    ) -> dict[str, Any]:
        campaign = self._reconcile_unlocked(campaign_path, campaign)
        if campaign["state"] == "FROZEN":
            raise ShadowCampaignError("frozen Campaign cannot resume")
        if campaign["state"] in {"RUNNING", "STARTING", "PAUSING"}:
            return self._status_unlocked(campaign_path, campaign)
        self._assert_binding(campaign)
        seed_database: Path | None = None
        seed_ledger: Path | None = None
        recovery: dict[str, Any] | None = None
        if campaign["segments"]:
            previous = campaign["segments"][-1]
            _, receipt = self._receipt_paths(previous)
            if previous["state"] == "ABORTED_UNCLEAN":
                seed_database, seed_ledger, recovery = self._prepare_unclean_seed(
                    campaign_path, previous, receipt
                )
            else:
                seed_database = Path(str(receipt["database_path"]))
                seed_ledger = Path(str(receipt["ledger_path"]))
                _runtime_flush(seed_database)
                _runtime_flush(seed_ledger)
        policy = _read_json(Path(str(campaign["frozen_policy_path"])), "frozen policy")
        try:
            launched = self._launcher(
                policy,
                policy_path=campaign["frozen_policy_path"],
                repository_root=self.repository_root,
                implementation_sha=campaign["implementation_sha"],
                service_root=campaign_path.parent / "segments",
                symbols=campaign["symbols"],
                bar=campaign["bar"],
                limit=campaign["limit"],
                interval_seconds=campaign["interval_seconds"],
                failure_threshold=campaign["failure_threshold"],
                seed_database_path=seed_database,
                seed_ledger_path=seed_ledger,
            )
        finally:
            if recovery is not None and seed_database is not None and seed_ledger is not None:
                for seed_path in (seed_database, seed_ledger):
                    if seed_path.exists() and not seed_path.is_symlink():
                        seed_path.unlink()
                try:
                    seed_database.parent.rmdir()
                except OSError:
                    pass
        now = _utc_text()
        segment = {
            "sequence": len(campaign["segments"]) + 1,
            "segment_id": launched["run_id"],
            "receipt_path": launched["receipt_path"],
            "state": "STARTING",
            "started_at": now,
            "ended_at": None,
            "session_id": None,
            "last_valid_heartbeat": None,
            "valid_duration_seconds": 0.0,
            "valid_cycles": 0,
            "failures": 0,
            "simulated_fills": 0,
            "seeded_from_previous_segment": seed_database is not None,
            "unclean_recovery": recovery,
        }
        campaign["segments"].append(segment)
        campaign["active_segment_id"] = launched["run_id"]
        campaign["state"] = "STARTING"
        campaign["safe_to_power_off"] = False
        campaign["updated_at"] = now
        _atomic_json(campaign_path, campaign)
        return self._status_unlocked(campaign_path, campaign)

    def resume(self) -> dict[str, Any]:
        with self._locked():
            path, campaign = self._load_current()
            return self._resume_unlocked(path, campaign)

    def _segment_assessment(self, segment: Mapping[str, Any]) -> dict[str, Any]:
        receipt_path, receipt = self._receipt_paths(segment)
        health_path = Path(str(receipt["health_path"]))
        database_path = Path(str(receipt["database_path"]))
        ledger_path = Path(str(receipt["ledger_path"]))
        health = _read_json(health_path, "Shadow health") if health_path.exists() else {}
        session_id = health.get("session_id") or segment.get("session_id")
        if not isinstance(session_id, str):
            return {
                "session_id": None,
                "valid_duration_seconds": 0.0,
                "valid_cycles": 0,
                "failures": 0,
                "simulated_fills": 0,
                "last_valid_heartbeat": None,
                "latest_public_market_at": None,
                "events": [],
                "safety_errors": [],
            }
        completed: set[str] = set()
        if database_path.exists():
            with _readonly_connection(database_path) as connection:
                rows = connection.execute(
                    "SELECT cycle_id FROM runtime_cycles WHERE session_id=? "
                    "AND status='COMPLETED' AND last_completed_stage='COMPLETED' "
                    "AND last_error IS NULL",
                    (session_id,),
                ).fetchall()
                completed = {str(row[0]) for row in rows}
        rows: list[dict[str, Any]] = []
        ledger_parse_error = False
        if ledger_path.exists():
            with _readonly_connection(ledger_path) as connection:
                for row in connection.execute(
                    "SELECT id,created_at,kind,payload_json FROM events ORDER BY id"
                ):
                    try:
                        payload = json.loads(row["payload_json"])
                    except (TypeError, json.JSONDecodeError):
                        ledger_parse_error = True
                        continue
                    if isinstance(payload, dict) and payload.get("session_id") == session_id:
                        rows.append(
                            {
                                "id": row["id"],
                                "created_at": row["created_at"],
                                "kind": row["kind"],
                                "payload": payload,
                            }
                        )
        markets: dict[str, dict[str, Any]] = {}
        completed_events: set[str] = set()
        executions: dict[str, dict[str, Any]] = {}
        failures = 0
        safety_errors: list[str] = (
            ["ledger contains invalid JSON"] if ledger_parse_error else []
        )
        latest_market_at: str | None = None
        for row in rows:
            payload = row["payload"]
            cycle_id = payload.get("cycle_id")
            if row["kind"] == "market_snapshot" and isinstance(cycle_id, str):
                if cycle_id in markets:
                    safety_errors.append("duplicate market snapshot cycle")
                markets[cycle_id] = payload
                latest_market_at = row["created_at"]
                if (
                    payload.get("source") != "OKX_OFFICIAL_PUBLIC"
                    or payload.get("public_only") is not True
                    or payload.get("account_access") is not False
                ):
                    safety_errors.append("non-public market snapshot")
            elif row["kind"] == "runtime_cycle_completed" and isinstance(cycle_id, str):
                completed_events.add(cycle_id)
            elif row["kind"] == "execution" and isinstance(cycle_id, str):
                executions[cycle_id] = payload
            elif row["kind"] == "shadow_supervisor_failure":
                failures += 1
            if row["kind"].startswith("shadow_supervisor_") and (
                payload.get("mode") != "shadow"
                or payload.get("public_data_only") is not True
                or payload.get("account_access") is not False
                or payload.get("private_api") is not False
                or payload.get("external_execution") is not False
                or payload.get("live") != LIVE
            ):
                safety_errors.append("supervisor safety boundary drift")
        eligible = completed & set(markets) & completed_events & set(executions)
        pending: str | None = None
        valid_points: list[tuple[str, datetime]] = []
        event_subset: list[dict[str, Any]] = []
        for row in rows:
            cycle_id = row["payload"].get("cycle_id")
            if isinstance(cycle_id, str) and cycle_id in eligible and row["kind"] in {
                "market_snapshot",
                "execution",
            }:
                event_subset.append(row)
            if row["kind"] == "runtime_cycle_completed" and cycle_id in eligible:
                pending = str(cycle_id)
            elif row["kind"] == "shadow_supervisor_heartbeat":
                if pending is not None:
                    updated = row["payload"].get("updated_at") or row["created_at"]
                    valid_points.append((pending, _parse_utc(updated)))
                pending = None
            elif row["kind"] == "shadow_supervisor_failure":
                pending = None
        threshold = float(
            _read_json(Path(str(receipt["deployed_policy_path"])), "deployed policy")
            ["shadow_evidence"]["max_heartbeat_gap_seconds"]
        )
        gaps = [
            (right[1] - left[1]).total_seconds()
            for left, right in pairwise(valid_points)
        ]
        valid_duration = sum(gap for gap in gaps if 0 <= gap <= threshold)
        valid_ids = {item[0] for item in valid_points}
        event_subset = [
            row for row in event_subset if row["payload"].get("cycle_id") in valid_ids
        ]
        fill_count = sum(
            1
            for cycle_id in valid_ids
            if executions[cycle_id].get("status") == "SHADOW_SIMULATED"
        )
        return {
            "session_id": session_id,
            "valid_duration_seconds": valid_duration,
            "valid_cycles": len(valid_points),
            "failures": failures,
            "simulated_fills": fill_count,
            "last_valid_heartbeat": valid_points[-1][1].isoformat() if valid_points else None,
            "latest_public_market_at": latest_market_at,
            "events": event_subset,
            "safety_errors": sorted(set(safety_errors)),
            "receipt_path": str(receipt_path),
        }

    def _metrics(self, campaign: Mapping[str, Any]) -> dict[str, Any]:
        assessments = [self._segment_assessment(item) for item in campaign["segments"]]
        all_events = [
            row
            for assessment in assessments
            for row in assessment["events"]
        ]
        all_events.sort(key=lambda row: (row["created_at"], row["id"]))
        positions: dict[str, Decimal] = {}
        marks: dict[str, Decimal] = {}
        cash = Decimal(0)
        fees = Decimal(0)
        starting_equity = _decimal(
            _read_json(Path(str(campaign["frozen_policy_path"])), "frozen policy")
            ["paper"]["equity_usdt"],
            "starting equity",
        )
        equity_curve: list[Decimal] = [starting_equity]
        market_by_cycle: dict[str, dict[str, Any]] = {}
        for row in all_events:
            payload = row["payload"]
            cycle_id = str(payload.get("cycle_id", ""))
            if row["kind"] == "market_snapshot":
                mark = _decimal(payload.get("mark_price"), "market mark")
                if mark <= 0:
                    continue
                market_by_cycle[cycle_id] = payload
                marks[str(payload.get("symbol"))] = mark
                if set(positions).issubset(marks):
                    equity_curve.append(
                        starting_equity
                        + cash
                        + sum((quantity * marks[symbol] for symbol, quantity in positions.items()), Decimal(0))
                    )
            elif row["kind"] == "execution" and payload.get("status") == "SHADOW_SIMULATED":
                market = market_by_cycle.get(cycle_id)
                if market is None or payload.get("action") not in {"BUY", "SELL"}:
                    continue
                symbol = str(payload.get("symbol"))
                mark = _decimal(market.get("mark_price"), "execution mark")
                price = _decimal(payload.get("price"), "execution price")
                notional = _decimal(payload.get("notional"), "execution notional")
                fee = _decimal(payload.get("fee"), "execution fee")
                if min(mark, price, notional) <= 0 or fee < 0:
                    continue
                quantity = (notional / mark).quantize(Decimal("0.00000001"))
                signed = quantity if payload["action"] == "BUY" else -quantity
                positions[symbol] = positions.get(symbol, Decimal(0)) + signed
                cash -= signed * price
                cash -= fee
                fees += fee
        marked = sum(
            (quantity * marks.get(symbol, Decimal(0)) for symbol, quantity in positions.items()),
            Decimal(0),
        )
        net_pnl = cash + marked
        equity_curve.append(starting_equity + net_pnl)
        peak = equity_curve[0]
        max_drawdown = Decimal(0)
        for value in equity_curve:
            peak = max(peak, value)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - value) / peak * Decimal(100))
        valid_cycles = sum(item["valid_cycles"] for item in assessments)
        failures = sum(item["failures"] for item in assessments)
        denominator = valid_cycles + failures
        latest_heartbeat = max(
            (item["last_valid_heartbeat"] for item in assessments if item["last_valid_heartbeat"]),
            default=None,
        )
        latest_market = max(
            (item["latest_public_market_at"] for item in assessments if item["latest_public_market_at"]),
            default=None,
        )
        return {
            "valid_duration_seconds": sum(item["valid_duration_seconds"] for item in assessments),
            "current_segment_valid_duration_seconds": assessments[-1]["valid_duration_seconds"] if assessments else 0.0,
            "valid_cycles": valid_cycles,
            "simulated_fills": sum(item["simulated_fills"] for item in assessments),
            "failures": failures,
            "failure_rate": failures / denominator if denominator else 0.0,
            "net_pnl_usdt": _decimal_text(net_pnl),
            "fees_usdt": _decimal_text(fees),
            "max_drawdown_pct": _decimal_text(max_drawdown),
            "last_valid_heartbeat": latest_heartbeat,
            "latest_public_market_at": latest_market,
            "safety_errors": sorted(
                {error for item in assessments for error in item["safety_errors"]}
            ),
            "segment_assessments": assessments,
        }

    def _mark_terminal(
        self,
        campaign_path: Path,
        campaign: dict[str, Any],
        segment: dict[str, Any],
        state: str,
    ) -> dict[str, Any]:
        assessment = self._segment_assessment(segment)
        _, receipt = self._receipt_paths(segment)
        health_path = Path(str(receipt["health_path"]))
        health = _read_json(health_path, "Shadow health") if health_path.exists() else {}
        ended_at = (
            health.get("stopped_at")
            if state != "ABORTED_UNCLEAN" and health.get("stopped_at")
            else assessment["last_valid_heartbeat"] or _utc_text()
        )
        segment.update(
            {
                "state": state,
                "ended_at": ended_at,
                "session_id": assessment["session_id"],
                "last_valid_heartbeat": assessment["last_valid_heartbeat"],
                "valid_duration_seconds": assessment["valid_duration_seconds"],
                "valid_cycles": assessment["valid_cycles"],
                "failures": assessment["failures"],
                "simulated_fills": assessment["simulated_fills"],
            }
        )
        campaign["state"] = "PAUSED" if state != "RECOVERY_REQUIRED" else "RECOVERY_REQUIRED"
        campaign["active_segment_id"] = None
        campaign["safe_to_power_off"] = True
        campaign["updated_at"] = _utc_text()
        _atomic_json(campaign_path, campaign)
        return campaign

    def _reconcile_unlocked(
        self, campaign_path: Path, campaign: dict[str, Any]
    ) -> dict[str, Any]:
        if campaign["state"] == "FROZEN" or not campaign.get("active_segment_id"):
            return campaign
        segment = next(
            (item for item in campaign["segments"] if item["segment_id"] == campaign["active_segment_id"]),
            None,
        )
        if segment is None:
            raise ShadowCampaignError("active Segment is missing")
        receipt_path, receipt = self._receipt_paths(segment)
        context: dict[str, Any] | None = None
        report: dict[str, Any] | None = None
        try:
            context = shadow_service_status_context(receipt_path)
            report = inspect_shadow_status(
                context["policy"],
                health_path=context["health_path"],
                database_path=context["database_path"],
                max_heartbeat_age_seconds=float(campaign["targets"]["max_heartbeat_gap_seconds"]),
            )
        except Exception:  # noqa: BLE001 - reconciliation remains fail-closed below
            report = None
        if report and report["operational_state"] == "RUNNING":
            segment["state"] = "RUNNING"
            segment["session_id"] = report["session_id"]
            campaign["state"] = "RUNNING"
            return campaign
        if report and report["operational_state"] == "STOPPED":
            if context:
                _runtime_flush(Path(context["database_path"]))
                _runtime_flush(Path(str(receipt["ledger_path"])))
            return self._mark_terminal(campaign_path, campaign, segment, "PAUSED_CLEAN")
        if report and report["reason"] == "CIRCUIT_BREAKER":
            return self._mark_terminal(campaign_path, campaign, segment, "CIRCUIT_BREAKER")
        if report and report["operational_state"] == "RECOVERY_REQUIRED":
            return self._mark_terminal(campaign_path, campaign, segment, "RECOVERY_REQUIRED")
        if report and report.get("process_lock_held") is True:
            segment["state"] = "DEGRADED"
            campaign["state"] = "RUNNING"
            return campaign
        launched_at = _parse_utc(receipt["launched_at"])
        if (_utc_now() - launched_at).total_seconds() <= 20:
            segment["state"] = "STARTING"
            campaign["state"] = "STARTING"
            return campaign
        return self._mark_terminal(campaign_path, campaign, segment, "ABORTED_UNCLEAN")

    def _conditions(
        self, campaign: Mapping[str, Any], metrics: Mapping[str, Any]
    ) -> list[dict[str, Any]]:
        targets = campaign["targets"]
        checks = [
            ("累计有效运行时间", metrics["valid_duration_seconds"] >= targets["minimum_duration_seconds"]),
            ("完整 Cycles", metrics["valid_cycles"] >= targets["minimum_cycles"]),
            ("模拟成交数", metrics["simulated_fills"] >= targets["minimum_simulated_fills"]),
            ("Failure rate", metrics["failure_rate"] <= targets["max_failure_rate"]),
            ("最大回撤", _decimal(metrics["max_drawdown_pct"], "drawdown") <= Decimal(str(targets["max_equity_drawdown_pct"]))),
            ("扣除成本后 PnL", not targets["require_positive_net_pnl"] or _decimal(metrics["net_pnl_usdt"], "PnL") > 0),
            ("官方 OKX 公共数据", not metrics["safety_errors"]),
            ("Commit / policy / strategy 已冻结", bool(campaign.get("implementation_sha") and campaign.get("policy_sha256") and campaign.get("strategy_version"))),
            ("无账户、私有 API 或外部执行", campaign.get("account_access") is False and campaign.get("private_api") is False and campaign.get("external_execution") is False),
            ("Live 永久禁止", campaign.get("live") == LIVE and campaign.get("authorizes_live") is False),
        ]
        return [{"name": name, "passed": bool(passed)} for name, passed in checks]

    def _status_unlocked(
        self, campaign_path: Path, campaign: dict[str, Any]
    ) -> dict[str, Any]:
        campaign = self._reconcile_unlocked(campaign_path, campaign)
        metrics = self._metrics(campaign)
        assessments = metrics.pop("segment_assessments")
        for segment, assessment in zip(campaign["segments"], assessments, strict=True):
            if segment["state"] in {"RUNNING", "STARTING", "DEGRADED"}:
                segment["session_id"] = assessment["session_id"]
                segment["last_valid_heartbeat"] = assessment["last_valid_heartbeat"]
                segment["valid_duration_seconds"] = assessment["valid_duration_seconds"]
                segment["valid_cycles"] = assessment["valid_cycles"]
                segment["failures"] = assessment["failures"]
                segment["simulated_fills"] = assessment["simulated_fills"]
        latest_market = metrics["latest_public_market_at"]
        market_age = None
        if latest_market:
            market_age = max(0.0, (_utc_now() - _parse_utc(latest_market)).total_seconds())
        if campaign["state"] in {"RUNNING", "STARTING"}:
            okx_status = (
                "CONNECTED"
                if market_age is not None and market_age <= campaign["targets"]["max_heartbeat_gap_seconds"]
                else "CONNECTING"
            )
        else:
            okx_status = "PAUSED" if latest_market else "NO_DATA"
        conditions = self._conditions(campaign, metrics)
        return {
            "schema_version": SCHEMA_VERSION,
            "campaign_id": campaign["campaign_id"],
            "state": campaign["state"],
            "state_label": {
                "RUNNING": "运行中",
                "STARTING": "正在启动",
                "PAUSING": "正在安全暂停",
                "PAUSED": "已暂停 · 现在可以关机",
                "RECOVERY_REQUIRED": "恢复锁定 · HOLD",
                "FROZEN": "已结束并冻结",
            }.get(campaign["state"], campaign["state"]),
            "resume_available": campaign["state"] == "PAUSED",
            "safe_to_power_off": campaign["safe_to_power_off"],
            "created_at": campaign["created_at"],
            "frozen_at": campaign["frozen_at"],
            "implementation_sha": campaign["implementation_sha"],
            "policy_sha256": campaign["policy_sha256"],
            "strategy_version": campaign["strategy_version"],
            "targets": campaign["targets"],
            "metrics": {**metrics, "okx_connection_status": okx_status, "okx_market_age_seconds": market_age},
            "segments": campaign["segments"],
            "validation_conditions": conditions,
            "all_conditions_passed": all(item["passed"] for item in conditions),
            "message": "继续上次 Campaign" if campaign["state"] == "PAUSED" else "",
            "trade_action": "HOLD",
            "public_data_only": True,
            "account_access": False,
            "private_api": False,
            "external_execution": False,
            "authorizes_live": False,
            "live": LIVE,
        }

    def status(self) -> dict[str, Any]:
        with self._locked():
            path = self._current_path()
            if path is None:
                return {
                    "schema_version": SCHEMA_VERSION,
                    "campaign_id": None,
                    "state": "NONE",
                    "state_label": "尚未创建 Campaign",
                    "resume_available": False,
                    "safe_to_power_off": True,
                    "message": "开始一个新的 Shadow Campaign",
                    "trade_action": "HOLD",
                    "authorizes_live": False,
                    "live": LIVE,
                }
            campaign = _read_json(path, "Campaign state")
            return self._status_unlocked(path, campaign)

    def pause(self, *, timeout_seconds: float = 90.0) -> dict[str, Any]:
        with self._locked():
            path, campaign = self._load_current()
            campaign = self._reconcile_unlocked(path, campaign)
            if campaign["state"] == "PAUSED":
                return self._status_unlocked(path, campaign)
            if campaign["state"] not in {"RUNNING", "STARTING"}:
                raise ShadowCampaignError("Campaign is not pausable")
            segment = campaign["segments"][-1]
            campaign["state"] = "PAUSING"
            campaign["safe_to_power_off"] = False
            campaign["updated_at"] = _utc_text()
            _atomic_json(path, campaign)
            self._stop_requester(segment["receipt_path"])
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                campaign = _read_json(path, "Campaign state")
                campaign = self._reconcile_unlocked(path, campaign)
                if campaign["state"] in {"PAUSED", "RECOVERY_REQUIRED"}:
                    result = self._status_unlocked(path, campaign)
                    result["message"] = "当前 Segment 已安全关闭，现在可以关机"
                    return result
                self._sleep(0.25)
            raise ShadowCampaignError("safe pause is still pending; do not power off yet")

    def freeze(self) -> dict[str, Any]:
        current = self.status()
        if current["state"] in {"RUNNING", "STARTING", "PAUSING"}:
            self.pause()
        with self._locked():
            path, campaign = self._load_current()
            campaign = self._reconcile_unlocked(path, campaign)
            if campaign["state"] == "RECOVERY_REQUIRED":
                raise ShadowCampaignError("Campaign recovery must be resolved before freeze")
            if campaign["state"] == "FROZEN":
                return self._status_unlocked(path, campaign)
            campaign["state"] = "FROZEN"
            campaign["frozen_at"] = _utc_text()
            campaign["safe_to_power_off"] = True
            campaign["updated_at"] = campaign["frozen_at"]
            _atomic_json(path, campaign)
            report = self._status_unlocked(path, campaign)
            evidence_path = path.parent / "campaign_evidence.json"
            manifest_path = path.parent / "campaign_manifest.json"
            sources: list[dict[str, Any]] = []
            for segment in campaign["segments"]:
                _, receipt = self._receipt_paths(segment)
                for field in ("database_path", "ledger_path", "health_path"):
                    source = Path(str(receipt[field]))
                    if source.exists():
                        sources.append(
                            {
                                "segment_id": segment["segment_id"],
                                "kind": field,
                                "path": str(source),
                                "sha256": _sha256_file(source),
                                "size": source.stat().st_size,
                            }
                        )
            evidence = {
                "schema_version": EVIDENCE_SCHEMA_VERSION,
                "frozen_at": campaign["frozen_at"],
                "campaign": report,
                "sources": sources,
                "authorizes_live": False,
                "live": LIVE,
            }
            _exclusive_json(evidence_path, evidence)
            _exclusive_json(
                manifest_path,
                {
                    "schema_version": "shadow_campaign_manifest.v1",
                    "campaign_id": campaign["campaign_id"],
                    "evidence_path": str(evidence_path),
                    "evidence_sha256": _sha256_file(evidence_path),
                    "sources": sources,
                    "authorizes_live": False,
                    "live": LIVE,
                },
            )
            report["evidence_path"] = str(evidence_path)
            report["manifest_path"] = str(manifest_path)
            return report
