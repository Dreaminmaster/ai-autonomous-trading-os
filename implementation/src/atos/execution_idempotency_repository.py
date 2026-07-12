"""Atomic SQLite B5 execution claim and pre-dispatch persistence.

This module owns only durable claim and dispatch-commit boundaries. It performs
no executor, network, exchange, or filesystem I/O. Each public mutation uses a
single injected RuntimeDatabase connection and one BEGIN IMMEDIATE transaction.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime

from atos.execution_idempotency_types import (
    ConcurrentExecutionTransitionError,
    DispatchCommitCommand,
    DispatchCommitResult,
    ExecutionClaimResult,
    ExecutionIdempotencyClaim,
    ExecutionIdempotencyCommand,
    ExecutionIdempotencyConflictError,
    ExecutionIdempotencyInvariantError,
    ExecutionIdempotencyOutcome,
    ExecutionIdempotencyPreconditionError,
    ExecutionIdempotencyValidationError,
    derive_attempt_id,
    derive_client_order_id,
    derive_idempotency_key,
)
from atos.lifecycle_types import (
    DispatchAttemptStatus,
    ExecutionStatus,
    OrderSide,
    require_utc_datetime,
    utc_text,
)
from atos.runtime_db import RuntimeDatabase

LIVE = "FORBIDDEN"


class SqliteExecutionIdempotencyRepository:
    """Fail-closed B5 claim and dispatch-commit repository."""

    def __init__(self, db: RuntimeDatabase) -> None:
        if not isinstance(db, RuntimeDatabase):
            raise ExecutionIdempotencyValidationError("db must be RuntimeDatabase")
        if db.conn is None:
            raise ExecutionIdempotencyValidationError(
                "db must be connected before repository construction"
            )
        self._db = db
        self._connection = db.conn

    def _after_mutation(
        self,
        boundary: str,
        connection: sqlite3.Connection,
    ) -> None:
        """Injected-crash test seam; production implementation is a no-op."""
        del boundary, connection

    def _require_connection(self) -> sqlite3.Connection:
        if self._db.conn is not self._connection:
            raise ExecutionIdempotencyPreconditionError(
                "injected RuntimeDatabase connection was closed or replaced"
            )
        return self._connection

    def _ensure_connection_stable(self, connection: sqlite3.Connection) -> None:
        if connection is not self._connection or self._db.conn is not self._connection:
            raise ExecutionIdempotencyInvariantError(
                "RuntimeDatabase connection changed inside idempotency operation"
            )

    def _mutate(
        self,
        connection: sqlite3.Connection,
        boundary: str,
        sql: str,
        parameters: tuple[object, ...],
    ) -> sqlite3.Cursor:
        cursor = connection.execute(sql, parameters)
        self._after_mutation(boundary, connection)
        self._ensure_connection_stable(connection)
        return cursor

    @staticmethod
    def _parse_utc_text(value: object, field_name: str) -> datetime:
        if not isinstance(value, str):
            raise ExecutionIdempotencyInvariantError(
                f"{field_name} must be persisted as TEXT"
            )
        candidate = value[:-1] + "+00:00" if value.endswith("Z") else value
        try:
            parsed = datetime.fromisoformat(candidate)
            require_utc_datetime(parsed, field_name)
        except Exception as exc:
            raise ExecutionIdempotencyInvariantError(
                f"{field_name} is not valid UTC timestamp text"
            ) from exc
        return parsed

    @classmethod
    def _claim_from_row(cls, row: sqlite3.Row) -> ExecutionIdempotencyClaim:
        try:
            action = OrderSide(row["action"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ExecutionIdempotencyInvariantError(
                "persisted claim action is invalid"
            ) from exc
        return ExecutionIdempotencyClaim(
            idempotency_key=row["idempotency_key"],
            execution_intent_id=row["execution_intent_id"],
            venue=row["venue"],
            account_scope=row["account_scope"],
            symbol=row["symbol"],
            action=action,
            normalized_intent_hash=row["normalized_intent_hash"],
            client_order_id=row["client_order_id"],
            created_at=cls._parse_utc_text(row["created_at"], "claim.created_at"),
        )

    @staticmethod
    def _select_claims(
        connection: sqlite3.Connection,
        *,
        idempotency_key: str,
        execution_intent_id: str,
        venue: str,
        account_scope: str,
        client_order_id: str,
    ) -> tuple[sqlite3.Row | None, sqlite3.Row | None, sqlite3.Row | None]:
        columns = (
            "idempotency_key,execution_intent_id,venue,account_scope,symbol,"
            "action,normalized_intent_hash,client_order_id,created_at"
        )
        by_key = connection.execute(
            f"SELECT {columns} FROM execution_idempotency_claims "
            "WHERE idempotency_key=?",
            (idempotency_key,),
        ).fetchone()
        by_execution = connection.execute(
            f"SELECT {columns} FROM execution_idempotency_claims "
            "WHERE execution_intent_id=?",
            (execution_intent_id,),
        ).fetchone()
        by_client = connection.execute(
            f"SELECT {columns} FROM execution_idempotency_claims "
            "WHERE venue=? AND account_scope=? AND client_order_id=?",
            (venue, account_scope, client_order_id),
        ).fetchone()
        return by_key, by_execution, by_client

    @staticmethod
    def _state_row(
        connection: sqlite3.Connection,
        execution_intent_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT execution_intent_id,status,last_attempt_id,retry_count,"
            "state_started_at,updated_at FROM execution_states "
            "WHERE execution_intent_id=?",
            (execution_intent_id,),
        ).fetchone()

    @staticmethod
    def _attempt_rows(
        connection: sqlite3.Connection,
        execution_intent_id: str,
    ) -> list[sqlite3.Row]:
        return list(
            connection.execute(
                "SELECT attempt_id,execution_intent_id,client_order_id,venue,"
                "account_scope,status,attempt_no,created_at,dispatch_started_at,"
                "response_received_at,error_class FROM dispatch_attempts "
                "WHERE execution_intent_id=? ORDER BY attempt_no",
                (execution_intent_id,),
            ).fetchall()
        )

    @classmethod
    def _execution_status(cls, state: sqlite3.Row) -> ExecutionStatus:
        try:
            status = ExecutionStatus(state["status"])
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ExecutionIdempotencyInvariantError(
                "persisted execution status is invalid"
            ) from exc
        if type(state["retry_count"]) is not int or state["retry_count"] != 0:
            raise ExecutionIdempotencyInvariantError(
                "B5 V1 execution retry_count must remain exactly zero"
            )
        cls._parse_utc_text(state["state_started_at"], "state.state_started_at")
        cls._parse_utc_text(state["updated_at"], "state.updated_at")
        return status

    @classmethod
    def _validate_graph(
        cls,
        claim: ExecutionIdempotencyClaim,
        state: sqlite3.Row,
        attempts: list[sqlite3.Row],
    ) -> ExecutionStatus:
        status = cls._execution_status(state)
        last_attempt_id = state["last_attempt_id"]
        if status is ExecutionStatus.PREPARED:
            if last_attempt_id is not None or attempts:
                raise ExecutionIdempotencyInvariantError(
                    "PREPARED execution must have no dispatch attempt"
                )
            return status

        if len(attempts) != 1:
            raise ExecutionIdempotencyInvariantError(
                "post-dispatch B5 V1 execution must have exactly one attempt"
            )
        attempt = attempts[0]
        expected_attempt_id = derive_attempt_id(claim.idempotency_key, 1)
        if (
            attempt["attempt_id"] != expected_attempt_id
            or attempt["execution_intent_id"] != claim.execution_intent_id
            or attempt["client_order_id"] != claim.client_order_id
            or attempt["venue"] != claim.venue
            or attempt["account_scope"] != claim.account_scope
            or attempt["attempt_no"] != 1
            or last_attempt_id != expected_attempt_id
        ):
            raise ExecutionIdempotencyInvariantError(
                "dispatch attempt ownership does not match idempotency claim"
            )
        try:
            DispatchAttemptStatus(attempt["status"])
        except (TypeError, ValueError) as exc:
            raise ExecutionIdempotencyInvariantError(
                "persisted dispatch attempt status is invalid"
            ) from exc
        cls._parse_utc_text(attempt["created_at"], "attempt.created_at")
        return status

    @staticmethod
    def _claim_outcome(status: ExecutionStatus) -> ExecutionIdempotencyOutcome:
        if status is ExecutionStatus.PREPARED:
            return ExecutionIdempotencyOutcome.REPLAY_PREPARED
        if status in {
            ExecutionStatus.DISPATCH_COMMITTED,
            ExecutionStatus.DISPATCHED,
            ExecutionStatus.ACKNOWLEDGED,
            ExecutionStatus.AMBIGUOUS,
        }:
            return ExecutionIdempotencyOutcome.RECONCILE_REQUIRED
        if status in {ExecutionStatus.FILLED, ExecutionStatus.TERMINAL}:
            return ExecutionIdempotencyOutcome.TERMINAL_NOOP
        raise ExecutionIdempotencyInvariantError(
            f"unsupported execution status {status.value}"
        )

    @staticmethod
    def _raise_sqlite_error(operation: str, exc: sqlite3.Error) -> None:
        message = str(exc).lower()
        if isinstance(exc, sqlite3.OperationalError) and (
            "locked" in message or "busy" in message
        ):
            raise ExecutionIdempotencyPreconditionError(
                f"{operation} could not acquire SQLite write authority"
            ) from exc
        if isinstance(exc, sqlite3.IntegrityError):
            raise ExecutionIdempotencyConflictError(
                f"{operation} violated durable idempotency ownership"
            ) from exc
        raise ExecutionIdempotencyInvariantError(
            f"{operation} failed due to SQLite persistence error"
        ) from exc

    def claim_execution(
        self,
        command: ExecutionIdempotencyCommand,
    ) -> ExecutionClaimResult:
        if type(command) is not ExecutionIdempotencyCommand:
            raise ExecutionIdempotencyValidationError(
                "command must be ExecutionIdempotencyCommand"
            )
        self._require_connection()
        try:
            with self._db.transaction(immediate=True) as connection:
                self._ensure_connection_stable(connection)
                parent = connection.execute(
                    "SELECT ei.execution_intent_id,ei.symbol,ei.action,"
                    "ei.normalized_intent_hash,rd.decision "
                    "FROM execution_intents AS ei "
                    "JOIN risk_decisions AS rd "
                    "ON rd.risk_decision_id=ei.risk_decision_id "
                    "AND rd.trade_intent_id=ei.trade_intent_id "
                    "WHERE ei.execution_intent_id=?",
                    (command.execution_intent_id,),
                ).fetchone()
                if parent is None:
                    raise ExecutionIdempotencyPreconditionError(
                        f"execution intent {command.execution_intent_id} does not exist"
                    )
                if parent["decision"] != "APPROVED":
                    raise ExecutionIdempotencyPreconditionError(
                        "execution intent risk decision is not APPROVED"
                    )
                expected_parent = (
                    command.symbol,
                    command.action.value,
                    command.normalized_intent_hash,
                )
                actual_parent = (
                    parent["symbol"],
                    parent["action"],
                    parent["normalized_intent_hash"],
                )
                if actual_parent != expected_parent:
                    raise ExecutionIdempotencyConflictError(
                        "command semantic components do not match execution intent"
                    )

                idempotency_key = derive_idempotency_key(
                    venue=command.venue,
                    account_scope=command.account_scope,
                    symbol=command.symbol,
                    action=command.action,
                    normalized_intent_hash=command.normalized_intent_hash,
                )
                client_order_id = derive_client_order_id(idempotency_key)
                by_key, by_execution, by_client = self._select_claims(
                    connection,
                    idempotency_key=idempotency_key,
                    execution_intent_id=command.execution_intent_id,
                    venue=command.venue,
                    account_scope=command.account_scope,
                    client_order_id=client_order_id,
                )
                present = [row for row in (by_key, by_execution, by_client) if row]
                if present:
                    owner_pairs = {
                        (row["idempotency_key"], row["execution_intent_id"])
                        for row in present
                    }
                    if owner_pairs != {(idempotency_key, command.execution_intent_id)}:
                        raise ExecutionIdempotencyConflictError(
                            "semantic key, execution intent, or client order ID has "
                            "conflicting durable ownership"
                        )
                    claim_row = by_key or by_execution or by_client
                    assert claim_row is not None
                    claim = self._claim_from_row(claim_row)
                    state = self._state_row(connection, command.execution_intent_id)
                    if state is None:
                        raise ExecutionIdempotencyInvariantError(
                            "idempotency claim exists without execution state"
                        )
                    attempts = self._attempt_rows(
                        connection, command.execution_intent_id
                    )
                    status = self._validate_graph(claim, state, attempts)
                    return ExecutionClaimResult(
                        outcome=self._claim_outcome(status),
                        claim=claim,
                        execution_status=status,
                    )

                state = self._state_row(connection, command.execution_intent_id)
                attempts = self._attempt_rows(connection, command.execution_intent_id)
                if state is not None or attempts:
                    raise ExecutionIdempotencyInvariantError(
                        "execution state or dispatch attempt exists without B5 claim"
                    )

                created_at = utc_text(command.created_at)
                self._mutate(
                    connection,
                    "claim_inserted",
                    "INSERT INTO execution_idempotency_claims "
                    "(idempotency_key,execution_intent_id,venue,account_scope,"
                    "symbol,action,normalized_intent_hash,client_order_id,created_at) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (
                        idempotency_key,
                        command.execution_intent_id,
                        command.venue,
                        command.account_scope,
                        command.symbol,
                        command.action.value,
                        command.normalized_intent_hash,
                        client_order_id,
                        created_at,
                    ),
                )
                self._mutate(
                    connection,
                    "prepared_state_inserted",
                    "INSERT INTO execution_states "
                    "(execution_intent_id,status,last_attempt_id,retry_count,"
                    "state_started_at,updated_at) VALUES (?,?,NULL,0,?,?)",
                    (
                        command.execution_intent_id,
                        ExecutionStatus.PREPARED.value,
                        created_at,
                        created_at,
                    ),
                )
                reread_claim_row = connection.execute(
                    "SELECT idempotency_key,execution_intent_id,venue,account_scope,"
                    "symbol,action,normalized_intent_hash,client_order_id,created_at "
                    "FROM execution_idempotency_claims WHERE idempotency_key=?",
                    (idempotency_key,),
                ).fetchone()
                reread_state = self._state_row(
                    connection, command.execution_intent_id
                )
                if reread_claim_row is None or reread_state is None:
                    raise ExecutionIdempotencyInvariantError(
                        "claim or PREPARED state re-read failed"
                    )
                claim = self._claim_from_row(reread_claim_row)
                status = self._validate_graph(claim, reread_state, [])
                if status is not ExecutionStatus.PREPARED:
                    raise ExecutionIdempotencyInvariantError(
                        "first claim did not persist PREPARED state"
                    )
                return ExecutionClaimResult(
                    outcome=ExecutionIdempotencyOutcome.CLAIMED,
                    claim=claim,
                    execution_status=status,
                )
        except sqlite3.Error as exc:
            self._raise_sqlite_error("claim_execution", exc)
            raise AssertionError("unreachable")

    def commit_dispatch(
        self,
        command: DispatchCommitCommand,
    ) -> DispatchCommitResult:
        if type(command) is not DispatchCommitCommand:
            raise ExecutionIdempotencyValidationError(
                "command must be DispatchCommitCommand"
            )
        self._require_connection()
        try:
            with self._db.transaction(immediate=True) as connection:
                self._ensure_connection_stable(connection)
                claim_row = connection.execute(
                    "SELECT idempotency_key,execution_intent_id,venue,account_scope,"
                    "symbol,action,normalized_intent_hash,client_order_id,created_at "
                    "FROM execution_idempotency_claims WHERE execution_intent_id=?",
                    (command.execution_intent_id,),
                ).fetchone()
                state = self._state_row(connection, command.execution_intent_id)
                attempts = self._attempt_rows(connection, command.execution_intent_id)
                if claim_row is None:
                    if state is not None or attempts:
                        raise ExecutionIdempotencyInvariantError(
                            "execution graph exists without idempotency claim"
                        )
                    raise ExecutionIdempotencyPreconditionError(
                        "execution must be claimed before dispatch commit"
                    )
                if state is None:
                    raise ExecutionIdempotencyInvariantError(
                        "idempotency claim exists without execution state"
                    )
                claim = self._claim_from_row(claim_row)
                status = self._validate_graph(claim, state, attempts)
                if status is not ExecutionStatus.PREPARED:
                    raise ExecutionIdempotencyPreconditionError(
                        f"execution status {status.value} is not safely dispatchable"
                    )

                attempt_no = 1
                attempt_id = derive_attempt_id(claim.idempotency_key, attempt_no)
                committed_at = utc_text(command.committed_at)
                self._mutate(
                    connection,
                    "dispatch_attempt_inserted",
                    "INSERT INTO dispatch_attempts "
                    "(attempt_id,execution_intent_id,client_order_id,venue,"
                    "account_scope,status,attempt_no,created_at,dispatch_started_at,"
                    "response_received_at,error_class) "
                    "VALUES (?,?,?,?,?,?,?,?,NULL,NULL,NULL)",
                    (
                        attempt_id,
                        claim.execution_intent_id,
                        claim.client_order_id,
                        claim.venue,
                        claim.account_scope,
                        DispatchAttemptStatus.PRE_DISPATCH_PROVEN.value,
                        attempt_no,
                        committed_at,
                    ),
                )
                cursor = self._mutate(
                    connection,
                    "dispatch_state_committed",
                    "UPDATE execution_states SET status=?,last_attempt_id=?,"
                    "state_started_at=?,updated_at=? "
                    "WHERE execution_intent_id=? AND status=? "
                    "AND last_attempt_id IS NULL AND retry_count=0",
                    (
                        ExecutionStatus.DISPATCH_COMMITTED.value,
                        attempt_id,
                        committed_at,
                        committed_at,
                        claim.execution_intent_id,
                        ExecutionStatus.PREPARED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ConcurrentExecutionTransitionError(
                        "PREPARED to DISPATCH_COMMITTED compare-and-swap lost"
                    )

                reread_state = self._state_row(connection, claim.execution_intent_id)
                reread_attempts = self._attempt_rows(
                    connection, claim.execution_intent_id
                )
                if reread_state is None:
                    raise ExecutionIdempotencyInvariantError(
                        "DISPATCH_COMMITTED state re-read failed"
                    )
                reread_status = self._validate_graph(
                    claim, reread_state, reread_attempts
                )
                if reread_status is not ExecutionStatus.DISPATCH_COMMITTED:
                    raise ExecutionIdempotencyInvariantError(
                        "dispatch commit did not persist DISPATCH_COMMITTED"
                    )
                attempt = reread_attempts[0]
                if attempt["status"] != DispatchAttemptStatus.PRE_DISPATCH_PROVEN.value:
                    raise ExecutionIdempotencyInvariantError(
                        "dispatch attempt did not persist PRE_DISPATCH_PROVEN"
                    )
                return DispatchCommitResult(
                    execution_intent_id=claim.execution_intent_id,
                    idempotency_key=claim.idempotency_key,
                    attempt_id=attempt_id,
                    client_order_id=claim.client_order_id,
                    attempt_no=attempt_no,
                    attempt_status=DispatchAttemptStatus.PRE_DISPATCH_PROVEN,
                    execution_status=ExecutionStatus.DISPATCH_COMMITTED,
                )
        except sqlite3.Error as exc:
            self._raise_sqlite_error("commit_dispatch", exc)
            raise AssertionError("unreachable")
