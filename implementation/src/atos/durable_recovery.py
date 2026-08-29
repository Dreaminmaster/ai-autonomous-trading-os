"""Explicit, token-bound recovery for durable Paper/Shadow simulation.

Recovery is deliberately narrower than normal execution.  It never calls a
market, account, private, order, or reconciliation endpoint.  The controller
can only close states whose outcome is already authoritative, or abandon a
pre-dispatch simulated attempt that provably has no order or fill.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from atos.lifecycle_types import utc_text
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MIGRATION_PLAN, MigrationManager

LIVE = "FORBIDDEN"
_CONTRACT = "DURABLE_SIMULATED_RECOVERY_V1"
_ABANDON_ERROR_CLASS = "SIMULATION_ABORTED_BY_OPERATOR"


class DurableRecoveryError(RuntimeError):
    """Recovery cannot be proven safe or the confirmation is invalid."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise DurableRecoveryError("recovery evidence is not canonical JSON") from exc


def _utc_now() -> datetime:
    return datetime.now(tz=UTC)


class DurableSimulatedRecoveryController:
    """Inspect and atomically resolve a frozen simulated recovery snapshot."""

    def __init__(self, *, mode: str, database_path: str | Path) -> None:
        if mode == "live":
            raise DurableRecoveryError("Live recovery is forbidden")
        if mode not in {"paper", "shadow"}:
            raise DurableRecoveryError("recovery supports only paper/shadow")
        self.mode = mode
        self.venue = f"okx_{mode}"
        self.account_scope = "simulated"
        self._db = RuntimeDatabase(database_path)
        self._db.connect()
        MigrationManager(self._db, MIGRATION_PLAN).migrate()

    @property
    def database(self) -> RuntimeDatabase:
        return self._db

    @staticmethod
    def _cycle_rows(connection: Any) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT cycle_id,session_id,symbol,status,last_completed_stage,last_error "
            "FROM runtime_cycles WHERE status != 'COMPLETED' "
            "ORDER BY session_id,started_at,cycle_id"
        ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _execution_rows(connection: Any) -> list[dict[str, Any]]:
        rows = connection.execute(
            "SELECT es.execution_intent_id,es.status AS execution_status,"
            "es.last_attempt_id,es.retry_count,ei.cycle_id,rc.session_id,"
            "c.venue,c.account_scope,da.attempt_id,da.status AS attempt_status,"
            "da.dispatch_started_at,da.response_received_at,"
            "(SELECT COUNT(*) FROM order_states AS o "
            " WHERE o.execution_intent_id=es.execution_intent_id) AS order_count,"
            "(SELECT COUNT(*) FROM fill_states AS f JOIN order_states AS o "
            " ON o.venue=f.venue AND o.account_scope=f.account_scope "
            " AND o.order_id=f.order_id "
            " WHERE o.execution_intent_id=es.execution_intent_id) AS fill_count "
            "FROM execution_states AS es "
            "JOIN execution_intents AS ei "
            " ON ei.execution_intent_id=es.execution_intent_id "
            "JOIN runtime_cycles AS rc ON rc.cycle_id=ei.cycle_id "
            "LEFT JOIN execution_idempotency_claims AS c "
            " ON c.execution_intent_id=es.execution_intent_id "
            "LEFT JOIN dispatch_attempts AS da "
            " ON da.execution_intent_id=es.execution_intent_id "
            "WHERE rc.status != 'COMPLETED' "
            "OR es.status NOT IN ('FILLED','TERMINAL') "
            "ORDER BY rc.session_id,ei.cycle_id,es.execution_intent_id,da.attempt_no"
        ).fetchall()
        return [dict(row) for row in rows]

    def _snapshot(self, connection: Any) -> dict[str, Any]:
        cycles = self._cycle_rows(connection)
        executions = self._execution_rows(connection)
        return {
            "contract": _CONTRACT,
            "mode": self.mode,
            "venue": self.venue,
            "account_scope": self.account_scope,
            "cycles": cycles,
            "executions": executions,
            "live": LIVE,
        }

    def _plan(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        cycles = snapshot["cycles"]
        executions = snapshot["executions"]
        by_cycle: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for execution in executions:
            by_cycle[execution["cycle_id"]].append(execution)

        actions: list[dict[str, Any]] = []
        errors: list[str] = []
        incomplete_cycle_ids = {cycle["cycle_id"] for cycle in cycles}
        for cycle in cycles:
            cycle_id = cycle["cycle_id"]
            linked = by_cycle.get(cycle_id, [])
            if cycle["status"] != "RISK_DECIDED":
                errors.append(f"unsupported_cycle_status:{cycle_id}:{cycle['status']}")
                continue
            if len(linked) != 1:
                errors.append(f"execution_graph_count:{cycle_id}:{len(linked)}")
                continue
            execution = linked[0]
            status = execution["execution_status"]
            attempt = execution["attempt_status"]
            orders = int(execution["order_count"])
            fills = int(execution["fill_count"])
            owner_ok = (
                execution["venue"] == self.venue
                and execution["account_scope"] == self.account_scope
                and execution["attempt_id"] == execution["last_attempt_id"]
                and execution["retry_count"] == 0
            )
            if not owner_ok:
                errors.append(
                    f"execution_owner_mismatch:{execution['execution_intent_id']}"
                )
            elif (
                status == "DISPATCH_COMMITTED"
                and attempt == "PRE_DISPATCH_PROVEN"
                and orders == 0
                and fills == 0
                and execution["dispatch_started_at"] is None
                and execution["response_received_at"] is None
            ):
                actions.append(
                    {
                        "kind": "ABANDON_PRE_DISPATCH_SIMULATION",
                        "session_id": cycle["session_id"],
                        "cycle_id": cycle_id,
                        "execution_intent_id": execution["execution_intent_id"],
                        "attempt_id": execution["last_attempt_id"],
                    }
                )
            elif (
                status == "FILLED"
                and attempt == "ACCEPTED"
                and orders == 1
                and fills >= 1
            ) or (
                status == "TERMINAL"
                and attempt == "REJECTED"
                and orders == 0
                and fills == 0
            ):
                actions.append(
                    {
                        "kind": "COMPLETE_AUTHORITATIVE_CYCLE",
                        "session_id": cycle["session_id"],
                        "cycle_id": cycle_id,
                        "execution_intent_id": execution["execution_intent_id"],
                        "attempt_id": execution["last_attempt_id"],
                    }
                )
            else:
                errors.append(
                    "unsupported_execution_state:"
                    f"{execution['execution_intent_id']}:{status}:{attempt}:"
                    f"orders={orders}:fills={fills}"
                )

        for execution in executions:
            if (
                execution["execution_status"] not in {"FILLED", "TERMINAL"}
                and execution["cycle_id"] not in incomplete_cycle_ids
            ):
                errors.append(
                    "nonterminal_execution_without_incomplete_cycle:"
                    + execution["execution_intent_id"]
                )

        required = bool(cycles) or any(
            execution["execution_status"] not in {"FILLED", "TERMINAL"}
            for execution in executions
        )
        return {
            "required": required,
            "classification": "RECOVERY_REQUIRED" if required else "CLEAR",
            "resolvable": required and not errors and len(actions) == len(cycles),
            "actions": actions,
            "errors": sorted(set(errors)),
        }

    @staticmethod
    def _token(snapshot: dict[str, Any], plan: dict[str, Any]) -> str:
        material = _canonical_json(
            {"contract": _CONTRACT, "snapshot": snapshot, "plan": plan}
        ).encode("utf-8")
        return hashlib.sha256(material).hexdigest()

    def inspect(self) -> dict[str, Any]:
        connection = self._db.connection
        snapshot = self._snapshot(connection)
        plan = self._plan(snapshot)
        token = self._token(snapshot, plan) if plan["required"] else ""
        return {
            **plan,
            "confirmation_token": token,
            "snapshot": snapshot,
            "mutated": False,
            "automatic_recovery": False,
            "external_reconciliation": False,
            "live": LIVE,
        }

    @staticmethod
    def _validate_reason(reason: str) -> str:
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or len(reason.strip()) > 200
            or any(ord(character) < 32 for character in reason.strip())
        ):
            raise DurableRecoveryError(
                "operator reason must be 1-200 printable characters"
            )
        normalized = reason.strip()
        prohibited = (
            "api_key",
            "apikey",
            "secret",
            "password",
            "passphrase",
            "authorization",
            "bearer ",
            "ok-access-",
        )
        if any(marker in normalized.lower() for marker in prohibited):
            raise DurableRecoveryError(
                "operator reason contains forbidden secret markers"
            )
        return normalized

    def resolve(self, *, confirmation_token: str, reason: str) -> dict[str, Any]:
        if (
            not isinstance(confirmation_token, str)
            or len(confirmation_token) != 64
            or any(
                character not in "0123456789abcdef" for character in confirmation_token
            )
        ):
            raise DurableRecoveryError(
                "a lowercase SHA-256 confirmation token is required"
            )
        operator_reason = self._validate_reason(reason)
        now = utc_text(_utc_now())
        with self._db.transaction(immediate=True) as connection:
            snapshot = self._snapshot(connection)
            plan = self._plan(snapshot)
            current_token = self._token(snapshot, plan) if plan["required"] else ""
            if confirmation_token != current_token:
                raise DurableRecoveryError(
                    "recovery snapshot changed or token is invalid"
                )
            if not plan["required"]:
                raise DurableRecoveryError("no recovery is required")
            if not plan["resolvable"]:
                raise DurableRecoveryError(
                    "recovery remains locked: " + ";".join(plan["errors"])
                )

            actions_by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
            for action in plan["actions"]:
                actions_by_session[action["session_id"]].append(action)
            recovery_ids: list[str] = []
            for session_id, actions in sorted(actions_by_session.items()):
                recovery_id = (
                    "recovery_"
                    + hashlib.sha256(
                        f"{_CONTRACT}:{current_token}:{session_id}".encode()
                    ).hexdigest()[:32]
                )
                recovery_ids.append(recovery_id)
                connection.execute(
                    "INSERT INTO recovery_states "
                    "(recovery_id,session_id,status,unresolved_items,started_at) "
                    "VALUES (?,?,?,?,?)",
                    (
                        recovery_id,
                        session_id,
                        "PENDING",
                        _canonical_json(actions),
                        now,
                    ),
                )
                cursor = connection.execute(
                    "UPDATE recovery_states SET status='IN_PROGRESS' "
                    "WHERE recovery_id=? AND status='PENDING'",
                    (recovery_id,),
                )
                if cursor.rowcount != 1:
                    raise DurableRecoveryError("recovery start CAS failed")

            for action in plan["actions"]:
                if action["kind"] == "ABANDON_PRE_DISPATCH_SIMULATION":
                    cursor = connection.execute(
                        "UPDATE dispatch_attempts SET status='REJECTED',"
                        "response_received_at=?,error_class=? "
                        "WHERE execution_intent_id=? AND attempt_id=? "
                        "AND status='PRE_DISPATCH_PROVEN' "
                        "AND dispatch_started_at IS NULL AND response_received_at IS NULL",
                        (
                            now,
                            _ABANDON_ERROR_CLASS,
                            action["execution_intent_id"],
                            action["attempt_id"],
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise DurableRecoveryError("attempt recovery CAS failed")
                    cursor = connection.execute(
                        "UPDATE execution_states SET status='TERMINAL',"
                        "state_started_at=?,updated_at=? "
                        "WHERE execution_intent_id=? AND last_attempt_id=? "
                        "AND status='DISPATCH_COMMITTED' AND retry_count=0",
                        (
                            now,
                            now,
                            action["execution_intent_id"],
                            action["attempt_id"],
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise DurableRecoveryError("execution recovery CAS failed")

                cursor = connection.execute(
                    "UPDATE runtime_cycles SET status='COMPLETED',"
                    "last_completed_stage='COMPLETED',completed_at=?,last_error=? "
                    "WHERE cycle_id=? AND status='RISK_DECIDED'",
                    (
                        now,
                        "RECOVERED_BY_OPERATOR:" + operator_reason,
                        action["cycle_id"],
                    ),
                )
                if cursor.rowcount != 1:
                    raise DurableRecoveryError("cycle recovery CAS failed")
                connection.execute(
                    "INSERT INTO cycle_journal "
                    "(cycle_id,from_state,to_state,recorded_at) VALUES (?,?,?,?)",
                    (action["cycle_id"], "RISK_DECIDED", "COMPLETED", now),
                )

            for recovery_id in recovery_ids:
                cursor = connection.execute(
                    "UPDATE recovery_states SET status='RESOLVED',recovered_at=? "
                    "WHERE recovery_id=? AND status='IN_PROGRESS'",
                    (now, recovery_id),
                )
                if cursor.rowcount != 1:
                    raise DurableRecoveryError("recovery completion CAS failed")

        final = self.inspect()
        if final["required"]:
            raise DurableRecoveryError("recovery transaction did not clear the lock")
        return {
            "status": "RESOLVED",
            "classification": "CLEAR",
            "recovery_ids": recovery_ids,
            "resolved_actions": plan["actions"],
            "operator_reason": operator_reason,
            "confirmation_token": confirmation_token,
            "mutated": True,
            "automatic_recovery": False,
            "external_reconciliation": False,
            "live": LIVE,
        }
