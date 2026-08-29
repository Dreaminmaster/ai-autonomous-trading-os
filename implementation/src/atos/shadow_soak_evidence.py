"""Read-only, tamper-evident assessment of a completed Shadow soak.

The evaluator consumes the public-only supervisor health snapshot, its audit
ledger, and the canonical durable runtime database.  It never constructs a
market/account client and never mutates either source database.  A successful
assessment means only that the retained Shadow observation met its frozen
operational thresholds; it can never authorize Live trading.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import urllib.parse
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from itertools import pairwise
from pathlib import Path
from typing import Any

from atos.core import utc_now
from atos.runtime_migrations import MIGRATION_PLAN

SCHEMA_VERSION = "shadow_soak_evidence.v1"
LIVE = "FORBIDDEN"
SAFE_STOP_REASONS = frozenset({"OPERATOR_STOP", "BOUNDED_COMPLETE"})
EXPECTED_LEDGER_COLUMNS = ("id", "created_at", "kind", "payload_json")


class ShadowSoakEvidenceError(RuntimeError):
    """A source or evidence-package invariant could not be proven."""


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
        raise ShadowSoakEvidenceError("value is not canonical JSON") from exc


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_regular_file(path: str | Path, label: str) -> tuple[bytes, Path]:
    candidate = Path(path)
    if candidate.is_symlink():
        raise ShadowSoakEvidenceError(f"{label} must not be a symbolic link")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise ShadowSoakEvidenceError(f"{label} is unavailable") from exc
    if not resolved.is_file():
        raise ShadowSoakEvidenceError(f"{label} must be a regular file")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
        with os.fdopen(descriptor, "rb") as handle:
            return handle.read(), resolved
    except OSError as exc:
        raise ShadowSoakEvidenceError(f"{label} cannot be read safely") from exc


def _json_object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowSoakEvidenceError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ShadowSoakEvidenceError(f"{label} must contain an object")
    return value


def _utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ShadowSoakEvidenceError(f"{label} must be UTC timestamp text")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise ShadowSoakEvidenceError(f"{label} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ShadowSoakEvidenceError(f"{label} must be timezone-aware")
    normalized = parsed.astimezone(UTC)
    if parsed.utcoffset() != normalized.utcoffset():
        raise ShadowSoakEvidenceError(f"{label} must use UTC")
    return normalized


def _decimal(value: object, label: str, *, non_negative: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ShadowSoakEvidenceError(f"{label} must be numeric")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ShadowSoakEvidenceError(f"{label} must be decimal-compatible") from exc
    if not result.is_finite() or (non_negative and result < 0):
        raise ShadowSoakEvidenceError(f"{label} must be finite")
    return result


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    return format(value.normalize(), "f")


def _exact_int(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ShadowSoakEvidenceError(f"{label} must be an integer >= {minimum}")
    return value


def _finite_number(value: object, label: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ShadowSoakEvidenceError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result) or result < minimum:
        raise ShadowSoakEvidenceError(f"{label} must be finite and >= {minimum}")
    return result


def _thresholds(policy: Mapping[str, Any]) -> dict[str, Any]:
    raw = policy.get("shadow_evidence")
    if not isinstance(raw, Mapping):
        raise ShadowSoakEvidenceError("policy.shadow_evidence is required")
    result = {
        "minimum_duration_seconds": _exact_int(
            raw.get("minimum_duration_seconds"),
            "minimum_duration_seconds",
        ),
        "minimum_cycles": _exact_int(raw.get("minimum_cycles"), "minimum_cycles"),
        "minimum_simulated_fills": _exact_int(
            raw.get("minimum_simulated_fills"),
            "minimum_simulated_fills",
        ),
        "max_failure_rate": _finite_number(
            raw.get("max_failure_rate"), "max_failure_rate"
        ),
        "max_heartbeat_gap_seconds": _finite_number(
            raw.get("max_heartbeat_gap_seconds"),
            "max_heartbeat_gap_seconds",
        ),
        "max_equity_drawdown_pct": _finite_number(
            raw.get("max_equity_drawdown_pct"),
            "max_equity_drawdown_pct",
        ),
        "require_positive_net_pnl": raw.get("require_positive_net_pnl"),
    }
    if result["max_failure_rate"] > 1:
        raise ShadowSoakEvidenceError("max_failure_rate must be <= 1")
    if result["max_equity_drawdown_pct"] > 100:
        raise ShadowSoakEvidenceError("max_equity_drawdown_pct must be <= 100")
    if type(result["require_positive_net_pnl"]) is not bool:
        raise ShadowSoakEvidenceError("require_positive_net_pnl must be boolean")
    return result


def _readonly_connection(path: Path) -> sqlite3.Connection:
    encoded = urllib.parse.quote(str(path), safe="/")
    try:
        connection = sqlite3.connect(f"file:{encoded}?mode=ro", uri=True, timeout=5.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        if connection.execute("PRAGMA query_only").fetchone()[0] != 1:
            raise ShadowSoakEvidenceError("SQLite query_only could not be proven")
        return connection
    except sqlite3.Error as exc:
        raise ShadowSoakEvidenceError("read-only SQLite open failed") from exc


def _ledger_rows(path: Path, session_id: str) -> tuple[list[dict[str, Any]], str]:
    connection = _readonly_connection(path)
    try:
        columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(events)")
        )
        if columns != EXPECTED_LEDGER_COLUMNS:
            raise ShadowSoakEvidenceError("ledger events schema drift")
        connection.execute("BEGIN")
        raw_rows = connection.execute(
            "SELECT id,created_at,kind,payload_json FROM events ORDER BY id"
        ).fetchall()
        rows: list[dict[str, Any]] = []
        for row in raw_rows:
            try:
                payload = json.loads(row["payload_json"])
            except (TypeError, json.JSONDecodeError) as exc:
                raise ShadowSoakEvidenceError("ledger payload is invalid JSON") from exc
            if not isinstance(payload, dict):
                raise ShadowSoakEvidenceError("ledger payload must be an object")
            if payload.get("session_id") == session_id:
                rows.append(
                    {
                        "id": row["id"],
                        "created_at": row["created_at"],
                        "kind": row["kind"],
                        "payload": payload,
                    }
                )
        connection.rollback()
    except sqlite3.Error as exc:
        raise ShadowSoakEvidenceError("ledger query failed") from exc
    finally:
        connection.close()
    if not rows:
        raise ShadowSoakEvidenceError("ledger has no events for the Shadow session")
    return rows, _sha256(_canonical_bytes(rows))


def _runtime_snapshot(
    path: Path, *, session_id: str, started_at: str, stopped_at: str
) -> tuple[dict[str, Any], str]:
    connection = _readonly_connection(path)
    try:
        connection.execute("BEGIN")
        migrations = [
            dict(row)
            for row in connection.execute(
                "SELECT version,name,checksum FROM schema_migrations ORDER BY version"
            )
        ]
        expected_migrations = [
            {"version": item.version, "name": item.name, "checksum": item.checksum}
            for item in MIGRATION_PLAN
        ]
        if migrations != expected_migrations:
            raise ShadowSoakEvidenceError("runtime migration authority drift")
        session_row = connection.execute(
            "SELECT session_id,started_at,mode,status,stopped_at,stop_reason "
            "FROM runtime_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if session_row is None:
            raise ShadowSoakEvidenceError("runtime session is missing")
        cycles = [
            dict(row)
            for row in connection.execute(
                "SELECT cycle_id,symbol,started_at,completed_at,status,"
                "last_completed_stage,last_error FROM runtime_cycles "
                "WHERE session_id=? ORDER BY started_at,cycle_id",
                (session_id,),
            )
        ]
        overlaps = connection.execute(
            "SELECT COUNT(*) FROM runtime_sessions WHERE session_id != ? "
            "AND started_at <= ? AND COALESCE(stopped_at, ?) >= ?",
            (session_id, stopped_at, stopped_at, started_at),
        ).fetchone()[0]
        trade_count = connection.execute(
            "SELECT COUNT(*) FROM trade_intents WHERE created_at>=? AND created_at<=?",
            (started_at, stopped_at),
        ).fetchone()[0]
        risk_count = connection.execute(
            "SELECT COUNT(*) FROM risk_decisions WHERE created_at>=? AND created_at<=?",
            (started_at, stopped_at),
        ).fetchone()[0]
        executions = [
            dict(row)
            for row in connection.execute(
                "SELECT ei.execution_intent_id,ei.cycle_id,ei.symbol,ei.action,"
                "ei.notional,es.status FROM execution_intents AS ei "
                "JOIN execution_states AS es USING(execution_intent_id) "
                "JOIN runtime_cycles AS rc USING(cycle_id) "
                "WHERE rc.session_id=? ORDER BY ei.created_at,ei.execution_intent_id",
                (session_id,),
            )
        ]
        orders = [
            dict(row)
            for row in connection.execute(
                "SELECT os.order_id,os.execution_intent_id,os.venue,os.account_scope,"
                "os.symbol,os.side,os.quantity,os.price,os.status FROM order_states AS os "
                "JOIN execution_intents AS ei USING(execution_intent_id) "
                "JOIN runtime_cycles AS rc USING(cycle_id) WHERE rc.session_id=? "
                "ORDER BY os.created_at,os.order_id",
                (session_id,),
            )
        ]
        fills = [
            dict(row)
            for row in connection.execute(
                "SELECT fs.fill_id,fs.order_id,fs.venue,fs.account_scope,fs.symbol,"
                "fs.quantity,fs.price,fs.fee,fs.timestamp,os.side,ei.cycle_id "
                "FROM fill_states AS fs "
                "JOIN order_states AS os ON os.venue=fs.venue "
                "AND os.account_scope=fs.account_scope AND os.order_id=fs.order_id "
                "JOIN execution_intents AS ei USING(execution_intent_id) "
                "JOIN runtime_cycles AS rc USING(cycle_id) WHERE rc.session_id=? "
                "ORDER BY fs.timestamp,fs.fill_id",
                (session_id,),
            )
        ]
        recovery_count = connection.execute(
            "SELECT COUNT(*) FROM recovery_states WHERE session_id=? "
            "AND status != 'RESOLVED'",
            (session_id,),
        ).fetchone()[0]
        connection.rollback()
    except sqlite3.Error as exc:
        raise ShadowSoakEvidenceError("runtime database query failed") from exc
    finally:
        connection.close()
    snapshot = {
        "migrations": migrations,
        "session": dict(session_row),
        "cycles": cycles,
        "overlapping_sessions": overlaps,
        "trade_intent_count": trade_count,
        "risk_decision_count": risk_count,
        "executions": executions,
        "orders": orders,
        "fills": fills,
        "unresolved_recovery_count": recovery_count,
    }
    return snapshot, _sha256(_canonical_bytes(snapshot))


def _ledger_assessment(
    rows: Sequence[Mapping[str, Any]],
    health: Mapping[str, Any],
    *,
    starting_equity_usdt: Decimal,
) -> dict[str, Any]:
    heartbeats: list[Mapping[str, Any]] = []
    supervisor_starts: list[Mapping[str, Any]] = []
    supervisor_stops: list[Mapping[str, Any]] = []
    market_by_cycle: dict[str, Mapping[str, Any]] = {}
    execution_by_cycle: dict[str, Mapping[str, Any]] = {}
    counts: dict[str, int] = {}
    safety_errors: list[str] = []
    for row in rows:
        kind = str(row["kind"])
        payload = row["payload"]
        counts[kind] = counts.get(kind, 0) + 1
        if kind == "shadow_supervisor_heartbeat":
            heartbeats.append(payload)
        if kind == "shadow_supervisor_started":
            supervisor_starts.append(payload)
        if kind == "shadow_supervisor_stopped":
            supervisor_stops.append(payload)
        if kind.startswith("shadow_supervisor_") and (
            payload.get("mode") != "shadow"
            or payload.get("public_data_only") is not True
            or payload.get("account_access") is not False
            or payload.get("private_api") is not False
            or payload.get("external_execution") is not False
            or payload.get("automatic_restart") is not False
            or payload.get("live") != LIVE
        ):
            safety_errors.append("supervisor event safety boundary drift")
        cycle_id = payload.get("cycle_id")
        if kind == "market_snapshot" and isinstance(cycle_id, str):
            if cycle_id in market_by_cycle:
                raise ShadowSoakEvidenceError("duplicate market snapshot cycle")
            market_by_cycle[cycle_id] = payload
            if (
                payload.get("source") != "OKX_OFFICIAL_PUBLIC"
                or payload.get("public_only") is not True
                or payload.get("account_access") is not False
            ):
                safety_errors.append("non-public market snapshot observed")
        if kind == "execution" and isinstance(cycle_id, str):
            if cycle_id in execution_by_cycle:
                raise ShadowSoakEvidenceError("duplicate execution cycle")
            execution_by_cycle[cycle_id] = payload

    expected_sequences = list(range(1, len(heartbeats) + 1))
    observed_sequences = [item.get("heartbeat_sequence") for item in heartbeats]
    heartbeat_times = [
        _utc(item.get("updated_at"), "heartbeat.updated_at") for item in heartbeats
    ]
    gaps = [(right - left).total_seconds() for left, right in pairwise(heartbeat_times)]
    failure_count = counts.get("shadow_supervisor_failure", 0)
    cycle_count = counts.get("runtime_cycle_completed", 0)
    if health.get("cycles_completed") != cycle_count:
        safety_errors.append("health and ledger cycle counts differ")
    if health.get("total_failures") != failure_count:
        safety_errors.append("health and ledger failure counts differ")
    if observed_sequences != expected_sequences:
        safety_errors.append("heartbeat sequence is not contiguous")
    if len(heartbeats) != health.get("heartbeat_sequence"):
        safety_errors.append("health heartbeat count differs from ledger")
    if any(gap < 0 for gap in gaps):
        safety_errors.append("heartbeat timestamps are not ordered")
    if len(supervisor_starts) != 1 or len(supervisor_stops) != 1:
        safety_errors.append("supervisor lifecycle event cardinality mismatch")
    elif supervisor_stops[0] != health:
        safety_errors.append("final supervisor event differs from health snapshot")
    if counts.get("execution", 0) != cycle_count:
        safety_errors.append("execution event count differs from completed cycles")

    positions: dict[str, Decimal] = {}
    last_marks: dict[str, Decimal] = {}
    cash = Decimal(0)
    fees = Decimal(0)
    simulated_fills = 0
    simulated_fill_rows: list[dict[str, str]] = []
    curve: list[Decimal] = [Decimal(0)]
    for row in rows:
        kind = row["kind"]
        payload = row["payload"]
        cycle_id = payload.get("cycle_id")
        if kind == "market_snapshot" and isinstance(cycle_id, str):
            mark = _decimal(payload.get("mark_price"), "market mark")
            if mark <= 0:
                raise ShadowSoakEvidenceError("market mark must be positive")
            last_marks[str(payload.get("symbol"))] = mark
        if kind != "execution" or not isinstance(cycle_id, str):
            continue
        if payload.get("mode") != "shadow":
            safety_errors.append("non-Shadow execution event observed")
            continue
        if payload.get("status") != "SHADOW_SIMULATED":
            continue
        market = market_by_cycle.get(cycle_id)
        if market is None:
            raise ShadowSoakEvidenceError("simulated fill lacks public market snapshot")
        symbol = str(payload.get("symbol"))
        action = payload.get("action")
        if action not in {"BUY", "SELL"}:
            raise ShadowSoakEvidenceError("simulated fill action is invalid")
        mark = _decimal(market.get("mark_price"), "execution mark")
        notional = _decimal(
            payload.get("notional"), "execution notional", non_negative=True
        )
        price = _decimal(payload.get("price"), "execution price")
        fee = _decimal(payload.get("fee"), "execution fee", non_negative=True)
        if mark <= 0 or price <= 0 or notional <= 0:
            raise ShadowSoakEvidenceError("simulated fill values must be positive")
        quantity = (notional / mark).quantize(Decimal("0.00000001"))
        signed_quantity = quantity if action == "BUY" else -quantity
        positions[symbol] = positions.get(symbol, Decimal(0)) + signed_quantity
        cash -= signed_quantity * price
        cash -= fee
        fees += fee
        simulated_fills += 1
        simulated_fill_rows.append(
            {
                "cycle_id": cycle_id,
                "symbol": symbol,
                "action": action,
                "quantity": _decimal_text(quantity),
                "execution_price": _decimal_text(price),
                "fee": _decimal_text(fee),
                "public_mark": _decimal_text(mark),
            }
        )
        missing_marks = set(positions).difference(last_marks)
        if not missing_marks:
            marked_value = sum(
                (
                    quantity_value * last_marks[symbol_value]
                    for symbol_value, quantity_value in positions.items()
                ),
                Decimal(0),
            )
            curve.append(cash + marked_value)

    missing_final_marks = sorted(set(positions).difference(last_marks))
    if missing_final_marks:
        safety_errors.append("open simulated inventory lacks a final public mark")
    marked_value = sum(
        (
            quantity_value * last_marks.get(symbol_value, Decimal(0))
            for symbol_value, quantity_value in positions.items()
        ),
        Decimal(0),
    )
    net_pnl = cash + marked_value
    equity = starting_equity_usdt
    equity_curve = [equity + value for value in curve]
    peak = equity_curve[0] if equity_curve else equity
    max_drawdown = Decimal(0)
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - value) / peak * Decimal(100))
    return {
        "event_counts": dict(sorted(counts.items())),
        "heartbeat_count": len(heartbeats),
        "heartbeat_sequences_contiguous": observed_sequences == expected_sequences,
        "max_heartbeat_gap_seconds": max(gaps, default=0.0),
        "cycle_count": cycle_count,
        "failure_count": failure_count,
        "failure_rate": failure_count / cycle_count if cycle_count else 1.0,
        "public_market_snapshot_count": len(market_by_cycle),
        "simulated_fill_count": simulated_fills,
        "simulated_fills": simulated_fill_rows,
        "fees_usdt": _decimal_text(fees),
        "net_pnl_usdt": _decimal_text(net_pnl),
        "ending_inventory": {
            symbol: _decimal_text(value) for symbol, value in sorted(positions.items())
        },
        "latest_public_marks": {
            symbol: _decimal_text(value) for symbol, value in sorted(last_marks.items())
        },
        "max_marked_equity_drawdown_pct": _decimal_text(max_drawdown),
        "safety_errors": sorted(set(safety_errors)),
    }


def _gate(
    *,
    health: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    ledger: Mapping[str, Any],
    runtime: Mapping[str, Any],
    duration_seconds: float,
) -> dict[str, Any]:
    failures: list[str] = []
    safety_fields = {
        "mode": "shadow",
        "public_data_only": True,
        "account_access": False,
        "private_api": False,
        "external_execution": False,
        "automatic_restart": False,
        "single_process_lock": True,
        "live": LIVE,
    }
    for key, expected in safety_fields.items():
        if health.get(key) != expected:
            failures.append(f"health.{key} safety invariant failed")
    if health.get("schema_version") != "shadow_supervisor.v1":
        failures.append("health schema version drift")
    if health.get("recovery_required") is not False:
        failures.append("health reports recovery required")
    if (
        health.get("state") != "STOPPED"
        or health.get("reason") not in SAFE_STOP_REASONS
    ):
        failures.append("Shadow session did not end in a safe completed stop")
    session = runtime["session"]
    if (
        session.get("mode") != "shadow"
        or session.get("status") != "STOPPED"
        or _utc(session.get("stopped_at"), "runtime session stopped_at")
        != _utc(health.get("stopped_at"), "health stopped_at")
        or session.get("stop_reason") != health.get("reason")
    ):
        failures.append("durable Shadow session closure mismatch")
    cycles = runtime["cycles"]
    if len(cycles) != ledger["cycle_count"] or any(
        row.get("status") != "COMPLETED" or row.get("last_error") is not None
        for row in cycles
    ):
        failures.append("durable cycle completion mismatch")
    if runtime["overlapping_sessions"] != 0:
        failures.append("another durable session overlaps the evidence window")
    if runtime["trade_intent_count"] != ledger["cycle_count"]:
        failures.append("trade-intent count does not match completed cycles")
    if runtime["risk_decision_count"] != ledger["cycle_count"]:
        failures.append("risk-decision count does not match completed cycles")
    if runtime["unresolved_recovery_count"] != 0:
        failures.append("unresolved durable recovery state exists")
    if any(
        row.get("status") not in {"FILLED", "TERMINAL"} for row in runtime["executions"]
    ):
        failures.append("non-terminal simulated execution exists")
    if len(runtime["orders"]) != len(runtime["fills"]):
        failures.append("simulated order/fill cardinality mismatch")
    if len(runtime["executions"]) != len(runtime["orders"]):
        failures.append("execution-intent/order cardinality mismatch")
    if ledger["simulated_fill_count"] != len(runtime["fills"]):
        failures.append("ledger/runtime simulated fill count mismatch")
    ledger_fills = {
        row.get("cycle_id"): row for row in ledger.get("simulated_fills", [])
    }
    runtime_fills = {row.get("cycle_id"): row for row in runtime["fills"]}
    if (
        len(ledger_fills) != len(ledger.get("simulated_fills", []))
        or len(runtime_fills) != len(runtime["fills"])
        or set(ledger_fills) != set(runtime_fills)
    ):
        failures.append("ledger/runtime fill cycle identity mismatch")
    else:
        tolerance = Decimal("0.000000000001")
        for cycle_id, ledger_fill in ledger_fills.items():
            runtime_fill = runtime_fills[cycle_id]
            if (
                ledger_fill.get("symbol") != runtime_fill.get("symbol")
                or ledger_fill.get("action") != runtime_fill.get("side")
                or abs(
                    _decimal(ledger_fill.get("quantity"), "ledger fill quantity")
                    - _decimal(runtime_fill.get("quantity"), "runtime fill quantity")
                )
                > tolerance
                or abs(
                    _decimal(ledger_fill.get("execution_price"), "ledger fill price")
                    - _decimal(runtime_fill.get("price"), "runtime fill price")
                )
                > tolerance
                or abs(
                    _decimal(ledger_fill.get("fee"), "ledger fill fee")
                    - _decimal(runtime_fill.get("fee"), "runtime fill fee")
                )
                > tolerance
            ):
                failures.append("ledger/runtime simulated fill payload mismatch")
                break
    if any(
        row.get("venue") != "okx_shadow" or row.get("account_scope") != "simulated"
        for row in [*runtime["orders"], *runtime["fills"]]
    ):
        failures.append("non-Shadow execution scope observed")
    failures.extend(ledger["safety_errors"])
    if duration_seconds < thresholds["minimum_duration_seconds"]:
        failures.append("minimum Shadow duration not reached")
    if ledger["cycle_count"] < thresholds["minimum_cycles"]:
        failures.append("minimum completed cycle count not reached")
    if ledger["simulated_fill_count"] < thresholds["minimum_simulated_fills"]:
        failures.append("minimum simulated fill count not reached")
    if ledger["failure_rate"] > thresholds["max_failure_rate"]:
        failures.append("Shadow failure rate exceeds limit")
    if ledger["max_heartbeat_gap_seconds"] > thresholds["max_heartbeat_gap_seconds"]:
        failures.append("Shadow heartbeat gap exceeds limit")
    drawdown = _decimal(
        ledger["max_marked_equity_drawdown_pct"], "marked equity drawdown"
    )
    if drawdown > Decimal(str(thresholds["max_equity_drawdown_pct"])):
        failures.append("marked equity drawdown exceeds limit")
    if (
        thresholds["require_positive_net_pnl"]
        and _decimal(ledger["net_pnl_usdt"], "net PnL") <= 0
    ):
        failures.append("net simulated PnL is not positive after costs")
    return {
        "status": "SOAK_PASS" if not failures else "SOAK_FAIL",
        "failures": sorted(set(failures)),
        "next_action": "INDEPENDENT_REVIEW" if not failures else "HOLD",
        "authorizes_live": False,
        "live": LIVE,
    }


def build_shadow_soak_evidence(
    output_root: str | Path,
    *,
    policy_path: str | Path,
    health_path: str | Path,
    ledger_path: str | Path,
    database_path: str | Path,
    implementation_sha: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build one exclusive evidence package from stable, read-only sources."""
    if (
        not isinstance(implementation_sha, str)
        or len(implementation_sha) != 40
        or any(character not in "0123456789abcdef" for character in implementation_sha)
    ):
        raise ShadowSoakEvidenceError("implementation_sha must be exact lowercase SHA")
    policy_raw, policy_resolved = _read_regular_file(policy_path, "policy")
    health_raw, health_resolved = _read_regular_file(health_path, "health")
    _, ledger_resolved = _read_regular_file(ledger_path, "ledger")
    _, database_resolved = _read_regular_file(database_path, "runtime database")
    if len({policy_resolved, health_resolved, ledger_resolved, database_resolved}) != 4:
        raise ShadowSoakEvidenceError("evidence source paths must be distinct")
    policy = _json_object(policy_raw, "policy")
    health = _json_object(health_raw, "health")
    thresholds = _thresholds(policy)
    if (
        policy.get("live_enabled") is not False
        or policy.get("public_data_only") is not True
    ):
        raise ShadowSoakEvidenceError("policy safety boundary is invalid")
    symbols = health.get("symbols")
    allowed_symbols = policy.get("allowed_symbols")
    if (
        not isinstance(symbols, list)
        or not symbols
        or any(not isinstance(symbol, str) or not symbol for symbol in symbols)
        or len(set(symbols)) != len(symbols)
        or not isinstance(allowed_symbols, list)
        or not set(symbols).issubset(set(allowed_symbols))
    ):
        raise ShadowSoakEvidenceError("health symbols are not policy-allowlisted")
    session_id = health.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        raise ShadowSoakEvidenceError("health session_id is required")
    started = _utc(health.get("started_at"), "health.started_at")
    stopped = _utc(health.get("stopped_at"), "health.stopped_at")
    if stopped < started:
        raise ShadowSoakEvidenceError("health stop precedes start")
    ledger_rows, ledger_digest = _ledger_rows(ledger_resolved, session_id)
    runtime, runtime_digest = _runtime_snapshot(
        database_resolved,
        session_id=session_id,
        started_at=health["started_at"],
        stopped_at=health["stopped_at"],
    )
    paper_policy = policy.get("paper")
    if not isinstance(paper_policy, Mapping):
        raise ShadowSoakEvidenceError("policy.paper is required")
    starting_equity = _decimal(
        paper_policy.get("equity_usdt"), "policy paper equity", non_negative=True
    )
    if starting_equity <= 0:
        raise ShadowSoakEvidenceError("policy paper equity must be positive")
    ledger = _ledger_assessment(
        ledger_rows,
        health,
        starting_equity_usdt=starting_equity,
    )
    duration = (stopped - started).total_seconds()
    gate = _gate(
        health=health,
        thresholds=thresholds,
        ledger=ledger,
        runtime=runtime,
        duration_seconds=duration,
    )
    health_after, _ = _read_regular_file(health_path, "health")
    if health_after != health_raw:
        raise ShadowSoakEvidenceError("health changed during evidence collection")
    report = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now(),
        "implementation_sha": implementation_sha,
        "session_id": session_id,
        "observation": {
            "started_at": health["started_at"],
            "stopped_at": health["stopped_at"],
            "duration_seconds": duration,
            "symbols": health.get("symbols"),
            "bar": health.get("bar"),
            "terminal_state": health.get("state"),
            "terminal_reason": health.get("reason"),
        },
        "thresholds": thresholds,
        "ledger_recompute": ledger,
        "runtime_cross_check": {
            "session": runtime["session"],
            "cycle_count": len(runtime["cycles"]),
            "trade_intent_count": runtime["trade_intent_count"],
            "risk_decision_count": runtime["risk_decision_count"],
            "execution_intent_count": len(runtime["executions"]),
            "simulated_order_count": len(runtime["orders"]),
            "simulated_fill_count": len(runtime["fills"]),
            "overlapping_sessions": runtime["overlapping_sessions"],
            "unresolved_recovery_count": runtime["unresolved_recovery_count"],
        },
        "source_custody": {
            "policy_sha256": _sha256(policy_raw),
            "health_sha256": _sha256(health_raw),
            "ledger_rows_sha256": ledger_digest,
            "runtime_snapshot_sha256": runtime_digest,
            "runtime_migration_count": len(runtime["migrations"]),
        },
        "safety": {
            "public_data_only": True,
            "account_access": False,
            "private_api": False,
            "external_execution": False,
            "paper_side_effect": False,
            "shadow_simulation_only": True,
            "automatic_activation": False,
            "authorizes_live": False,
            "live": LIVE,
        },
        "gate": gate,
    }
    root = Path(output_root)
    if root.exists() or root.is_symlink():
        raise ShadowSoakEvidenceError("evidence output already exists")
    root.mkdir(parents=True, mode=0o700)
    evidence_bytes = _canonical_bytes(report)
    evidence_path = root / "shadow_soak_evidence.json"
    with evidence_path.open("xb") as handle:
        handle.write(evidence_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    manifest = {
        "schema_version": 1,
        "stage": "SHADOW_SOAK_EVIDENCE_V1",
        "implementation_sha": implementation_sha,
        "session_id": session_id,
        "files": [
            {
                "path": evidence_path.name,
                "size": len(evidence_bytes),
                "sha256": _sha256(evidence_bytes),
            }
        ],
        "file_count": 1,
        "authorizes_live": False,
        "live": LIVE,
    }
    manifest_path = root / "manifest.json"
    manifest_bytes = _canonical_bytes(manifest)
    with manifest_path.open("xb") as handle:
        handle.write(manifest_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    directory = os.open(root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    return report, manifest


def verify_shadow_soak_package(root: str | Path) -> dict[str, Any]:
    """Independently verify package inventory and byte hashes."""
    package = Path(root)
    if package.is_symlink() or not package.is_dir():
        raise ShadowSoakEvidenceError("evidence package is not a safe directory")
    if any(path.is_symlink() for path in package.rglob("*")):
        raise ShadowSoakEvidenceError("evidence package contains a symbolic link")
    manifest = _json_object((package / "manifest.json").read_bytes(), "manifest")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("stage") != "SHADOW_SOAK_EVIDENCE_V1"
    ):
        raise ShadowSoakEvidenceError("manifest identity drift")
    declared = manifest.get("files")
    if not isinstance(declared, list) or manifest.get("file_count") != len(declared):
        raise ShadowSoakEvidenceError("manifest inventory is invalid")
    observed = {
        path.relative_to(package).as_posix()
        for path in package.rglob("*")
        if path.is_file() and path.name != "manifest.json"
    }
    expected: set[str] = set()
    for item in declared:
        if not isinstance(item, Mapping):
            raise ShadowSoakEvidenceError("manifest entry is invalid")
        relative = item.get("path")
        if (
            not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
        ):
            raise ShadowSoakEvidenceError("manifest path is unsafe")
        if relative in expected:
            raise ShadowSoakEvidenceError("manifest path is duplicated")
        expected.add(relative)
        data = (package / relative).read_bytes()
        if len(data) != item.get("size") or _sha256(data) != item.get("sha256"):
            raise ShadowSoakEvidenceError("evidence package hash mismatch")
    if observed != expected:
        raise ShadowSoakEvidenceError("manifest inventory is incomplete")
    if manifest.get("authorizes_live") is not False or manifest.get("live") != LIVE:
        raise ShadowSoakEvidenceError("manifest Live safety boundary drift")
    if expected != {"shadow_soak_evidence.json"}:
        raise ShadowSoakEvidenceError("manifest evidence path drift")
    report = _json_object(
        (package / "shadow_soak_evidence.json").read_bytes(), "Shadow evidence"
    )
    safety = report.get("safety")
    gate = report.get("gate")
    if (
        report.get("schema_version") != SCHEMA_VERSION
        or report.get("implementation_sha") != manifest.get("implementation_sha")
        or report.get("session_id") != manifest.get("session_id")
        or not isinstance(safety, Mapping)
        or safety.get("authorizes_live") is not False
        or safety.get("live") != LIVE
        or not isinstance(gate, Mapping)
        or gate.get("authorizes_live") is not False
        or gate.get("live") != LIVE
    ):
        raise ShadowSoakEvidenceError("evidence identity or Live boundary drift")
    return manifest
