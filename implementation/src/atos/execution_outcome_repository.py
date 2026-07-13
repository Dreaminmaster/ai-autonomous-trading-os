"""Atomic B5D execution outcome persistence.

This repository bridges B5C DISPATCH_COMMITTED evidence to the frozen B4.3
order/fill lifecycle writer. It performs no executor, network, exchange, or
filesystem I/O.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from atos.execution_idempotency_types import (
    ExecutionIdempotencyClaim,
    ExecutionIdempotencyConflictError,
    ExecutionIdempotencyInvariantError,
    ExecutionIdempotencyPreconditionError,
    ExecutionIdempotencyValidationError,
    derive_attempt_id,
)
from atos.execution_recovery import ExecutionRecoverySnapshot
from atos.lifecycle_types import (
    DispatchAttemptStatus,
    ExecutionStatus,
    OrderSide,
    PersistenceOutcome,
    require_identity,
    require_utc_datetime,
    utc_text,
)
from atos.runtime_db import RuntimeDatabase

LIVE = "FORBIDDEN"


def _identity(value: str, field_name: str) -> str:
    try:
        return require_identity(value, field_name)
    except Exception as exc:
        raise ExecutionIdempotencyValidationError(str(exc)) from exc


def _utc(value: datetime, field_name: str) -> datetime:
    try:
        return require_utc_datetime(value, field_name)
    except Exception as exc:
        raise ExecutionIdempotencyValidationError(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class DispatchSubmittedCommand:
    execution_intent_id: str
    attempt_id: str
    submitted_at: datetime

    def __post_init__(self) -> None:
        _identity(self.execution_intent_id, "execution_intent_id")
        _identity(self.attempt_id, "attempt_id")
        _utc(self.submitted_at, "submitted_at")


@dataclass(frozen=True, slots=True)
class DispatchAmbiguousCommand:
    execution_intent_id: str
    attempt_id: str
    attempt_status: DispatchAttemptStatus
    observed_at: datetime
    error_class: str

    def __post_init__(self) -> None:
        _identity(self.execution_intent_id, "execution_intent_id")
        _identity(self.attempt_id, "attempt_id")
        if type(self.attempt_status) is not DispatchAttemptStatus or self.attempt_status not in {
            DispatchAttemptStatus.TIMEOUT,
            DispatchAttemptStatus.AMBIGUOUS,
        }:
            raise ExecutionIdempotencyValidationError(
                "attempt_status must be TIMEOUT or AMBIGUOUS"
            )
        _utc(self.observed_at, "observed_at")
        _identity(self.error_class, "error_class")


@dataclass(frozen=True, slots=True)
class DispatchRejectedCommand:
    execution_intent_id: str
    attempt_id: str
    observed_at: datetime
    error_class: str

    def __post_init__(self) -> None:
        _identity(self.execution_intent_id, "execution_intent_id")
        _identity(self.attempt_id, "attempt_id")
        _utc(self.observed_at, "observed_at")
        _identity(self.error_class, "error_class")


@dataclass(frozen=True, slots=True)
class ExecutionFilledCommand:
    execution_intent_id: str
    attempt_id: str
    order_id: str
    fill_id: str
    observed_at: datetime

    def __post_init__(self) -> None:
        for name in ("execution_intent_id", "attempt_id", "order_id", "fill_id"):
            _identity(getattr(self, name), name)
        _utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class ExecutionOutcomeResult:
    outcome: PersistenceOutcome
    execution_status: ExecutionStatus
    attempt_status: DispatchAttemptStatus

    def __post_init__(self) -> None:
        if type(self.outcome) is not PersistenceOutcome:
            raise ExecutionIdempotencyValidationError(
                "outcome must be PersistenceOutcome"
            )
        if type(self.execution_status) is not ExecutionStatus:
            raise ExecutionIdempotencyValidationError(
                "execution_status must be ExecutionStatus"
            )
        if type(self.attempt_status) is not DispatchAttemptStatus:
            raise ExecutionIdempotencyValidationError(
                "attempt_status must be DispatchAttemptStatus"
            )


class SqliteExecutionOutcomeRepository:
    """Fail-closed authority for post-B5C execution state transitions."""

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
        self, boundary: str, connection: sqlite3.Connection
    ) -> None:
        """Injected-crash test seam; production implementation is a no-op."""
        del boundary, connection

    def _require_connection(self) -> sqlite3.Connection:
        if self._db.conn is not self._connection:
            raise ExecutionIdempotencyPreconditionError(
                "injected RuntimeDatabase connection was closed or replaced"
            )
        if self._connection.in_transaction:
            raise ExecutionIdempotencyPreconditionError(
                "nested execution outcome transaction is forbidden"
            )
        return self._connection

    def _ensure_connection_stable(self, connection: sqlite3.Connection) -> None:
        if connection is not self._connection or self._db.conn is not self._connection:
            raise ExecutionIdempotencyInvariantError(
                "RuntimeDatabase connection changed inside outcome operation"
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
            side = OrderSide(row["action"])
        except (TypeError, ValueError) as exc:
            raise ExecutionIdempotencyInvariantError(
                "persisted claim action is invalid"
            ) from exc
        return ExecutionIdempotencyClaim(
            idempotency_key=row["idempotency_key"],
            execution_intent_id=row["execution_intent_id"],
            venue=row["venue"],
            account_scope=row["account_scope"],
            symbol=row["symbol"],
            action=side,
            normalized_intent_hash=row["normalized_intent_hash"],
            client_order_id=row["client_order_id"],
            created_at=cls._parse_utc_text(row["created_at"], "claim.created_at"),
        )

    @staticmethod
    def _claim_row(
        connection: sqlite3.Connection, execution_intent_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT idempotency_key,execution_intent_id,venue,account_scope,"
            "symbol,action,normalized_intent_hash,client_order_id,created_at "
            "FROM execution_idempotency_claims WHERE execution_intent_id=?",
            (execution_intent_id,),
        ).fetchone()

    @staticmethod
    def _state_row(
        connection: sqlite3.Connection, execution_intent_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT execution_intent_id,status,last_attempt_id,retry_count,"
            "state_started_at,updated_at FROM execution_states "
            "WHERE execution_intent_id=?",
            (execution_intent_id,),
        ).fetchone()

    @staticmethod
    def _attempt_rows(
        connection: sqlite3.Connection, execution_intent_id: str
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
    def _require_graph(
        cls,
        connection: sqlite3.Connection,
        execution_intent_id: str,
        attempt_id: str,
    ) -> tuple[ExecutionIdempotencyClaim, sqlite3.Row, sqlite3.Row]:
        claim_row = cls._claim_row(connection, execution_intent_id)
        state = cls._state_row(connection, execution_intent_id)
        attempts = cls._attempt_rows(connection, execution_intent_id)
        if claim_row is None or state is None:
            raise ExecutionIdempotencyPreconditionError(
                "claimed execution state is required before outcome persistence"
            )
        if len(attempts) != 1:
            raise ExecutionIdempotencyInvariantError(
                "B5 V1 outcome persistence requires exactly one attempt"
            )
        claim = cls._claim_from_row(claim_row)
        attempt = attempts[0]
        expected_attempt_id = derive_attempt_id(claim.idempotency_key, 1)
        if (
            attempt["attempt_id"] != attempt_id
            or attempt["attempt_id"] != expected_attempt_id
            or attempt["execution_intent_id"] != claim.execution_intent_id
            or attempt["client_order_id"] != claim.client_order_id
            or attempt["venue"] != claim.venue
            or attempt["account_scope"] != claim.account_scope
            or attempt["attempt_no"] != 1
            or state["last_attempt_id"] != attempt_id
            or state["retry_count"] != 0
        ):
            raise ExecutionIdempotencyInvariantError(
                "outcome graph does not match immutable claim ownership"
            )
        cls._parse_utc_text(attempt["created_at"], "attempt.created_at")
        cls._parse_utc_text(state["state_started_at"], "state.state_started_at")
        cls._parse_utc_text(state["updated_at"], "state.updated_at")
        return claim, state, attempt

    @staticmethod
    def _status(value: object, enum_type, field_name: str):
        try:
            return enum_type(value)
        except (TypeError, ValueError) as exc:
            raise ExecutionIdempotencyInvariantError(
                f"{field_name} contains an unknown enum value"
            ) from exc

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
                f"{operation} violated durable outcome ownership"
            ) from exc
        raise ExecutionIdempotencyInvariantError(
            f"{operation} failed due to SQLite persistence error"
        ) from exc

    def mark_dispatched(
        self, command: DispatchSubmittedCommand
    ) -> ExecutionOutcomeResult:
        if type(command) is not DispatchSubmittedCommand:
            raise ExecutionIdempotencyValidationError(
                "command must be DispatchSubmittedCommand"
            )
        self._require_connection()
        try:
            with self._db.transaction(immediate=True) as connection:
                claim, state, attempt = self._require_graph(
                    connection, command.execution_intent_id, command.attempt_id
                )
                del claim
                state_status = self._status(
                    state["status"], ExecutionStatus, "execution status"
                )
                attempt_status = self._status(
                    attempt["status"], DispatchAttemptStatus, "attempt status"
                )
                if (
                    state_status is ExecutionStatus.DISPATCHED
                    and attempt_status is DispatchAttemptStatus.SUBMITTED
                ):
                    self._parse_utc_text(
                        attempt["dispatch_started_at"],
                        "attempt.dispatch_started_at",
                    )
                    return ExecutionOutcomeResult(
                        PersistenceOutcome.REPLAY_NOOP,
                        state_status,
                        attempt_status,
                    )
                if (
                    state_status is not ExecutionStatus.DISPATCH_COMMITTED
                    or attempt_status
                    is not DispatchAttemptStatus.PRE_DISPATCH_PROVEN
                ):
                    raise ExecutionIdempotencyPreconditionError(
                        "execution is not the exact pre-dispatch owner"
                    )
                timestamp = utc_text(command.submitted_at)
                cursor = self._mutate(
                    connection,
                    "dispatch.attempt_submitted",
                    "UPDATE dispatch_attempts SET status=?,dispatch_started_at=? "
                    "WHERE execution_intent_id=? AND attempt_id=? AND status=? "
                    "AND dispatch_started_at IS NULL",
                    (
                        DispatchAttemptStatus.SUBMITTED.value,
                        timestamp,
                        command.execution_intent_id,
                        command.attempt_id,
                        DispatchAttemptStatus.PRE_DISPATCH_PROVEN.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExecutionIdempotencyConflictError(
                        "dispatch attempt submission compare-and-swap lost"
                    )
                cursor = self._mutate(
                    connection,
                    "dispatch.execution_dispatched",
                    "UPDATE execution_states SET status=?,state_started_at=?,updated_at=? "
                    "WHERE execution_intent_id=? AND last_attempt_id=? "
                    "AND status=? AND retry_count=0",
                    (
                        ExecutionStatus.DISPATCHED.value,
                        timestamp,
                        timestamp,
                        command.execution_intent_id,
                        command.attempt_id,
                        ExecutionStatus.DISPATCH_COMMITTED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExecutionIdempotencyConflictError(
                        "DISPATCH_COMMITTED to DISPATCHED compare-and-swap lost"
                    )
                _, reread_state, reread_attempt = self._require_graph(
                    connection, command.execution_intent_id, command.attempt_id
                )
                if (
                    reread_state["status"] != ExecutionStatus.DISPATCHED.value
                    or reread_attempt["status"]
                    != DispatchAttemptStatus.SUBMITTED.value
                    or reread_attempt["dispatch_started_at"] != timestamp
                ):
                    raise ExecutionIdempotencyInvariantError(
                        "dispatched outcome re-read failed"
                    )
                return ExecutionOutcomeResult(
                    PersistenceOutcome.APPLIED,
                    ExecutionStatus.DISPATCHED,
                    DispatchAttemptStatus.SUBMITTED,
                )
        except sqlite3.Error as exc:
            self._raise_sqlite_error("mark_dispatched", exc)
            raise AssertionError("unreachable")

    def mark_ambiguous(
        self, command: DispatchAmbiguousCommand
    ) -> ExecutionOutcomeResult:
        if type(command) is not DispatchAmbiguousCommand:
            raise ExecutionIdempotencyValidationError(
                "command must be DispatchAmbiguousCommand"
            )
        self._require_connection()
        try:
            with self._db.transaction(immediate=True) as connection:
                _, state, attempt = self._require_graph(
                    connection, command.execution_intent_id, command.attempt_id
                )
                state_status = self._status(
                    state["status"], ExecutionStatus, "execution status"
                )
                attempt_status = self._status(
                    attempt["status"], DispatchAttemptStatus, "attempt status"
                )
                if (
                    state_status is ExecutionStatus.AMBIGUOUS
                    and attempt_status is command.attempt_status
                    and attempt["error_class"] == command.error_class
                ):
                    self._parse_utc_text(
                        attempt["response_received_at"],
                        "attempt.response_received_at",
                    )
                    return ExecutionOutcomeResult(
                        PersistenceOutcome.REPLAY_NOOP,
                        state_status,
                        attempt_status,
                    )
                allowed = {
                    (
                        ExecutionStatus.DISPATCH_COMMITTED,
                        DispatchAttemptStatus.PRE_DISPATCH_PROVEN,
                    ),
                    (
                        ExecutionStatus.DISPATCHED,
                        DispatchAttemptStatus.SUBMITTED,
                    ),
                    (
                        ExecutionStatus.DISPATCHED,
                        DispatchAttemptStatus.DISPATCH_INITIATED,
                    ),
                }
                if (state_status, attempt_status) not in allowed:
                    raise ExecutionIdempotencyPreconditionError(
                        "execution is not eligible for ambiguous outcome"
                    )
                timestamp = utc_text(command.observed_at)
                cursor = self._mutate(
                    connection,
                    "ambiguous.attempt_update",
                    "UPDATE dispatch_attempts SET status=?,response_received_at=?,"
                    "error_class=? WHERE execution_intent_id=? AND attempt_id=? "
                    "AND status=?",
                    (
                        command.attempt_status.value,
                        timestamp,
                        command.error_class,
                        command.execution_intent_id,
                        command.attempt_id,
                        attempt_status.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExecutionIdempotencyConflictError(
                        "attempt ambiguous compare-and-swap lost"
                    )
                cursor = self._mutate(
                    connection,
                    "ambiguous.execution_update",
                    "UPDATE execution_states SET status=?,state_started_at=?,updated_at=? "
                    "WHERE execution_intent_id=? AND last_attempt_id=? AND status=?",
                    (
                        ExecutionStatus.AMBIGUOUS.value,
                        timestamp,
                        timestamp,
                        command.execution_intent_id,
                        command.attempt_id,
                        state_status.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExecutionIdempotencyConflictError(
                        "execution ambiguous compare-and-swap lost"
                    )
                return ExecutionOutcomeResult(
                    PersistenceOutcome.APPLIED,
                    ExecutionStatus.AMBIGUOUS,
                    command.attempt_status,
                )
        except sqlite3.Error as exc:
            self._raise_sqlite_error("mark_ambiguous", exc)
            raise AssertionError("unreachable")

    def mark_terminal_rejection(
        self, command: DispatchRejectedCommand
    ) -> ExecutionOutcomeResult:
        if type(command) is not DispatchRejectedCommand:
            raise ExecutionIdempotencyValidationError(
                "command must be DispatchRejectedCommand"
            )
        self._require_connection()
        try:
            with self._db.transaction(immediate=True) as connection:
                _, state, attempt = self._require_graph(
                    connection, command.execution_intent_id, command.attempt_id
                )
                state_status = self._status(
                    state["status"], ExecutionStatus, "execution status"
                )
                attempt_status = self._status(
                    attempt["status"], DispatchAttemptStatus, "attempt status"
                )
                order_count = connection.execute(
                    "SELECT COUNT(*) FROM order_states WHERE execution_intent_id=?",
                    (command.execution_intent_id,),
                ).fetchone()[0]
                fill_count = connection.execute(
                    "SELECT COUNT(*) FROM fill_states AS f "
                    "JOIN order_states AS o ON o.venue=f.venue "
                    "AND o.account_scope=f.account_scope AND o.order_id=f.order_id "
                    "WHERE o.execution_intent_id=?",
                    (command.execution_intent_id,),
                ).fetchone()[0]
                if (
                    state_status is ExecutionStatus.TERMINAL
                    and attempt_status is DispatchAttemptStatus.REJECTED
                    and attempt["error_class"] == command.error_class
                    and order_count == 0
                    and fill_count == 0
                ):
                    self._parse_utc_text(
                        attempt["response_received_at"],
                        "attempt.response_received_at",
                    )
                    return ExecutionOutcomeResult(
                        PersistenceOutcome.REPLAY_NOOP,
                        state_status,
                        attempt_status,
                    )
                if (
                    state_status is not ExecutionStatus.DISPATCHED
                    or attempt_status is not DispatchAttemptStatus.SUBMITTED
                    or order_count != 0
                    or fill_count != 0
                ):
                    raise ExecutionIdempotencyPreconditionError(
                        "execution is not eligible for terminal rejection"
                    )
                timestamp = utc_text(command.observed_at)
                cursor = self._mutate(
                    connection,
                    "rejection.attempt_update",
                    "UPDATE dispatch_attempts SET status=?,response_received_at=?,"
                    "error_class=? WHERE execution_intent_id=? AND attempt_id=? "
                    "AND status=?",
                    (
                        DispatchAttemptStatus.REJECTED.value,
                        timestamp,
                        command.error_class,
                        command.execution_intent_id,
                        command.attempt_id,
                        DispatchAttemptStatus.SUBMITTED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExecutionIdempotencyConflictError(
                        "attempt rejection compare-and-swap lost"
                    )
                cursor = self._mutate(
                    connection,
                    "rejection.execution_update",
                    "UPDATE execution_states SET status=?,state_started_at=?,updated_at=? "
                    "WHERE execution_intent_id=? AND last_attempt_id=? AND status=?",
                    (
                        ExecutionStatus.TERMINAL.value,
                        timestamp,
                        timestamp,
                        command.execution_intent_id,
                        command.attempt_id,
                        ExecutionStatus.DISPATCHED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExecutionIdempotencyConflictError(
                        "execution terminal compare-and-swap lost"
                    )
                return ExecutionOutcomeResult(
                    PersistenceOutcome.APPLIED,
                    ExecutionStatus.TERMINAL,
                    DispatchAttemptStatus.REJECTED,
                )
        except sqlite3.Error as exc:
            self._raise_sqlite_error("mark_terminal_rejection", exc)
            raise AssertionError("unreachable")

    def mark_filled(
        self, command: ExecutionFilledCommand
    ) -> ExecutionOutcomeResult:
        if type(command) is not ExecutionFilledCommand:
            raise ExecutionIdempotencyValidationError(
                "command must be ExecutionFilledCommand"
            )
        self._require_connection()
        try:
            with self._db.transaction(immediate=True) as connection:
                claim, state, attempt = self._require_graph(
                    connection, command.execution_intent_id, command.attempt_id
                )
                state_status = self._status(
                    state["status"], ExecutionStatus, "execution status"
                )
                attempt_status = self._status(
                    attempt["status"], DispatchAttemptStatus, "attempt status"
                )
                order = connection.execute(
                    "SELECT venue,account_scope,order_id,execution_intent_id,"
                    "attempt_id,client_order_id,status FROM order_states "
                    "WHERE venue=? AND account_scope=? AND order_id=?",
                    (claim.venue, claim.account_scope, command.order_id),
                ).fetchone()
                fill = connection.execute(
                    "SELECT venue,account_scope,fill_id,order_id FROM fill_states "
                    "WHERE venue=? AND account_scope=? AND fill_id=?",
                    (claim.venue, claim.account_scope, command.fill_id),
                ).fetchone()
                if order is None or fill is None:
                    raise ExecutionIdempotencyPreconditionError(
                        "authoritative deterministic order and fill are required"
                    )
                if (
                    order["execution_intent_id"] != command.execution_intent_id
                    or order["attempt_id"] != command.attempt_id
                    or order["client_order_id"] != claim.client_order_id
                    or order["status"] != "FILLED"
                    or fill["order_id"] != command.order_id
                ):
                    raise ExecutionIdempotencyInvariantError(
                        "order/fill authority does not match execution claim"
                    )
                if (
                    state_status is ExecutionStatus.FILLED
                    and attempt_status is DispatchAttemptStatus.ACCEPTED
                ):
                    return ExecutionOutcomeResult(
                        PersistenceOutcome.REPLAY_NOOP,
                        state_status,
                        attempt_status,
                    )
                if (
                    state_status is not ExecutionStatus.ACKNOWLEDGED
                    or attempt_status is not DispatchAttemptStatus.ACCEPTED
                ):
                    raise ExecutionIdempotencyPreconditionError(
                        "execution is not ACKNOWLEDGED with an accepted attempt"
                    )
                timestamp = utc_text(command.observed_at)
                cursor = self._mutate(
                    connection,
                    "filled.execution_update",
                    "UPDATE execution_states SET status=?,state_started_at=?,updated_at=? "
                    "WHERE execution_intent_id=? AND last_attempt_id=? AND status=?",
                    (
                        ExecutionStatus.FILLED.value,
                        timestamp,
                        timestamp,
                        command.execution_intent_id,
                        command.attempt_id,
                        ExecutionStatus.ACKNOWLEDGED.value,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ExecutionIdempotencyConflictError(
                        "ACKNOWLEDGED to FILLED compare-and-swap lost"
                    )
                return ExecutionOutcomeResult(
                    PersistenceOutcome.APPLIED,
                    ExecutionStatus.FILLED,
                    DispatchAttemptStatus.ACCEPTED,
                )
        except sqlite3.Error as exc:
            self._raise_sqlite_error("mark_filled", exc)
            raise AssertionError("unreachable")

    def read_recovery_snapshot(
        self,
        execution_intent_id: str,
        *,
        reconciliation_available: bool,
    ) -> ExecutionRecoverySnapshot:
        _identity(execution_intent_id, "execution_intent_id")
        if type(reconciliation_available) is not bool:
            raise ExecutionIdempotencyValidationError(
                "reconciliation_available must be bool"
            )
        connection = self._require_connection()
        claim_row = self._claim_row(connection, execution_intent_id)
        state = self._state_row(connection, execution_intent_id)
        attempts = self._attempt_rows(connection, execution_intent_id)
        if claim_row is None or state is None:
            raise ExecutionIdempotencyPreconditionError(
                "claimed execution state is required for recovery"
            )
        claim = self._claim_from_row(claim_row)
        if len(attempts) > 1:
            raise ExecutionIdempotencyInvariantError(
                "B5 V1 recovery found more than one attempt"
            )
        attempt_status = None
        if attempts:
            attempt = attempts[0]
            expected_attempt_id = derive_attempt_id(claim.idempotency_key, 1)
            if (
                attempt["attempt_id"] != expected_attempt_id
                or attempt["execution_intent_id"] != claim.execution_intent_id
                or attempt["client_order_id"] != claim.client_order_id
                or attempt["venue"] != claim.venue
                or attempt["account_scope"] != claim.account_scope
                or attempt["attempt_no"] != 1
                or state["last_attempt_id"] != expected_attempt_id
                or state["retry_count"] != 0
            ):
                raise ExecutionIdempotencyInvariantError(
                    "recovery attempt authority is corrupt"
                )
            self._parse_utc_text(attempt["created_at"], "attempt.created_at")
            attempt_status = self._status(
                attempt["status"], DispatchAttemptStatus, "attempt status"
            )
        elif state["last_attempt_id"] is not None:
            raise ExecutionIdempotencyInvariantError(
                "execution references a missing attempt"
            )
        if state["retry_count"] != 0:
            raise ExecutionIdempotencyInvariantError(
                "B5 V1 recovery retry_count must remain exactly zero"
            )
        self._parse_utc_text(state["state_started_at"], "state.state_started_at")
        self._parse_utc_text(state["updated_at"], "state.updated_at")
        execution_status = self._status(
            state["status"], ExecutionStatus, "execution status"
        )
        orders = connection.execute(
            "SELECT order_id FROM order_states WHERE execution_intent_id=?",
            (execution_intent_id,),
        ).fetchall()
        if len(orders) > 1:
            raise ExecutionIdempotencyInvariantError(
                "paper recovery found more than one authoritative order"
            )
        fills: list[sqlite3.Row] = []
        if orders:
            fills = list(
                connection.execute(
                    "SELECT fill_id FROM fill_states WHERE venue=? "
                    "AND account_scope=? AND order_id=?",
                    (claim.venue, claim.account_scope, orders[0]["order_id"]),
                ).fetchall()
            )
            if len(fills) > 1:
                raise ExecutionIdempotencyInvariantError(
                    "paper recovery found more than one authoritative fill"
                )
        return ExecutionRecoverySnapshot(
            execution_status=execution_status,
            attempt_count=len(attempts),
            attempt_status=attempt_status,
            reconciliation_available=reconciliation_available,
            order_present=bool(orders),
            fill_present=bool(fills),
        )
