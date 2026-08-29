"""Durable, replay-safe Paper/Shadow execution bridge.

This module connects the strategy-agnostic operating runtime to the existing
RuntimeDatabase, B5 idempotency authority, deterministic paper fill adapter,
and position-accounting lifecycle. It has no network client, account API, API
key, or Live execution path.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal, localcontext
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

from atos.execution import ExecutionResult, PaperExecutor
from atos.execution_idempotency_repository import (
    SqliteExecutionIdempotencyRepository,
)
from atos.execution_idempotency_types import (
    DispatchCommitCommand,
    ExecutionIdempotencyCommand,
    derive_attempt_id,
)
from atos.lifecycle_types import (
    ExecutionStatus,
    OrderSide,
    decimal_text,
    deterministic_id,
    utc_text,
)
from atos.paper_execution_adapter import (
    DeterministicPaperExecutionAdapter,
    PaperExecutionConfig,
    PaperExecutionEnvelope,
    SqlitePaperExecutionCoordinator,
)
from atos.position_accounting import NettingPositionAccountingV1
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import MIGRATION_PLAN, MigrationManager

LIVE = "FORBIDDEN"
_GRAPH_VERSION = "OPERATING_RUNTIME_DURABLE_GRAPH_V1"
_T = TypeVar("_T")


class DurableExecutionError(RuntimeError):
    """A durable simulation invariant could not be proven."""


def _recovery_guard(method: Callable[..., _T]) -> Callable[..., _T]:
    """Refresh and latch durable recovery authority around each execution."""

    @wraps(method)
    def guarded(self: DurableSimulatedExecutor, *args: Any, **kwargs: Any) -> _T:
        self._startup_recovery = self._read_recovery_report()
        if self._startup_recovery["required"]:
            raise DurableExecutionError(
                "recovery is required before new simulated execution"
            )
        try:
            return method(self, *args, **kwargs)
        except Exception:
            # A failure after the decision graph or dispatch claim was
            # committed must block later cycles in this same process.
            self._startup_recovery = self._read_recovery_report()
            raise

    return guarded


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
        raise DurableExecutionError("runtime payload is not canonical JSON") from exc


def _utc_datetime(value: object, field_name: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise DurableExecutionError(f"{field_name} must be ISO-8601 UTC text")
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError as exc:
        raise DurableExecutionError(f"{field_name} is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise DurableExecutionError(f"{field_name} must be timezone-aware")
    normalized = parsed.astimezone(UTC)
    if parsed.utcoffset() != normalized.utcoffset():
        raise DurableExecutionError(f"{field_name} must use UTC offset +00:00")
    return normalized


def _decimal(value: object, field_name: str, *, positive: bool = False) -> Decimal:
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise DurableExecutionError(f"{field_name} is not decimal-compatible") from exc
    if not result.is_finite() or (positive and result <= 0):
        qualifier = "positive and finite" if positive else "finite"
        raise DurableExecutionError(f"{field_name} must be {qualifier}")
    return result


class DurableSimulatedExecutor(PaperExecutor):
    """Persisted Paper/Shadow executor backed by the canonical lifecycle DB."""

    def __init__(
        self,
        *,
        mode: str,
        database_path: str | Path,
        fee_bps: float = 10.0,
        slippage_bps: float = 5.0,
    ) -> None:
        if mode not in {"paper", "shadow"}:
            raise DurableExecutionError("durable executor supports only paper/shadow")
        super().__init__(fee_bps=fee_bps, slippage_bps=slippage_bps)
        self.mode = mode
        self.venue = f"okx_{mode}"
        self.account_scope = "simulated"
        self._db = RuntimeDatabase(database_path)
        self._db.connect()
        MigrationManager(self._db, MIGRATION_PLAN).migrate()
        self._config = PaperExecutionConfig(
            fee_bps=_decimal(fee_bps, "fee_bps"),
            slippage_bps=_decimal(slippage_bps, "slippage_bps"),
        )
        self._builder = DeterministicPaperExecutionAdapter(self._config)
        self._idempotency = SqliteExecutionIdempotencyRepository(self._db)
        self._coordinator = SqlitePaperExecutionCoordinator(
            self._db,
            NettingPositionAccountingV1(),
            self._config,
        )
        self._startup_recovery = self._read_recovery_report()

    @property
    def database(self) -> RuntimeDatabase:
        return self._db

    def _read_recovery_report(self) -> dict[str, Any]:
        cycles = self._db.connection.execute(
            "SELECT cycle_id,session_id,symbol,status,last_completed_stage,last_error "
            "FROM runtime_cycles WHERE status != 'COMPLETED' ORDER BY started_at,cycle_id"
        ).fetchall()
        executions = self._db.connection.execute(
            "SELECT es.execution_intent_id,es.status,c.venue,c.account_scope "
            "FROM execution_states AS es "
            "LEFT JOIN execution_idempotency_claims AS c "
            "ON c.execution_intent_id=es.execution_intent_id "
            "WHERE es.status NOT IN ('FILLED','TERMINAL') "
            "ORDER BY es.execution_intent_id"
        ).fetchall()
        return {
            "required": bool(cycles or executions),
            "classification": "RECOVERY_REQUIRED" if cycles or executions else "CLEAR",
            "cycles": [dict(row) for row in cycles],
            "executions": [dict(row) for row in executions],
            "automatic_external_reconciliation": False,
            "live": LIVE,
        }

    def recovery_report(self) -> dict[str, Any]:
        """Return the latest fail-closed recovery assessment."""
        self._startup_recovery = self._read_recovery_report()
        return json.loads(_canonical_json(self._startup_recovery))

    def risk_state(
        self,
        *,
        symbol: str,
        mark_price: float,
        equity_usdt: float,
    ) -> dict[str, float]:
        """Read a conservative portfolio snapshot from durable authority."""
        mark = _decimal(mark_price, "mark_price", positive=True)
        starting_equity = _decimal(equity_usdt, "equity_usdt", positive=True)
        rows = self._db.connection.execute(
            "SELECT symbol,side,quantity,avg_entry_price,realized_pnl "
            "FROM position_states WHERE venue=? AND account_scope=? "
            "AND status='OPEN'",
            (self.venue, self.account_scope),
        ).fetchall()
        gross = Decimal(0)
        symbol_gross = Decimal(0)
        symbol_long = Decimal(0)
        symbol_short = Decimal(0)
        unrealized = Decimal(0)
        for row in rows:
            quantity = _decimal(row["quantity"], "position.quantity")
            entry = _decimal(
                row["avg_entry_price"], "position.avg_entry_price", positive=True
            )
            position_mark = mark if row["symbol"] == symbol else entry
            notional = abs(quantity * position_mark)
            gross += notional
            if row["symbol"] == symbol:
                symbol_gross += notional
                if row["side"] == "LONG":
                    symbol_long += notional
                    unrealized += quantity * (mark - entry)
                elif row["side"] == "SHORT":
                    symbol_short += notional
                    unrealized += quantity * (entry - mark)
                else:
                    raise DurableExecutionError("persisted position side is invalid")
        realized_row = self._db.connection.execute(
            "SELECT realized_pnl FROM position_states "
            "WHERE venue=? AND account_scope=?",
            (self.venue, self.account_scope),
        ).fetchall()
        realized = sum(
            (
                _decimal(row["realized_pnl"], "position.realized_pnl")
                for row in realized_row
            ),
            Decimal(0),
        )
        fee_rows = self._db.connection.execute(
            "SELECT fee FROM fill_states WHERE venue=? AND account_scope=?",
            (self.venue, self.account_scope),
        ).fetchall()
        fees = sum((_decimal(row["fee"], "fill.fee") for row in fee_rows), Decimal(0))
        net_realized = realized - fees
        pnl = net_realized + unrealized
        drawdown = max(Decimal(0), -pnl / starting_equity * Decimal(100))

        def percentage(value: Decimal) -> float:
            return float(value / starting_equity * Decimal(100))

        return {
            "gross_exposure_pct": percentage(gross),
            "symbol_exposure_pct": percentage(symbol_gross),
            "symbol_long_exposure_pct": percentage(symbol_long),
            "symbol_short_exposure_pct": percentage(symbol_short),
            "realized_pnl_usdt": float(net_realized),
            "unrealized_pnl_usdt": float(unrealized),
            "fees_paid_usdt": float(fees),
            "current_drawdown_pct": float(drawdown),
        }

    @staticmethod
    def _identity(prefix: str, session_id: str, cycle_id: str) -> str:
        return deterministic_id(prefix, (_GRAPH_VERSION, session_id, cycle_id, prefix))

    @staticmethod
    def _row_matches(
        row: Any, columns: tuple[str, ...], values: tuple[Any, ...]
    ) -> bool:
        return tuple(row[column] for column in columns) == values

    def _insert_or_verify(
        self,
        connection: Any,
        *,
        table: str,
        key_column: str,
        key_value: str,
        columns: tuple[str, ...],
        values: tuple[Any, ...],
    ) -> None:
        row = connection.execute(
            f"SELECT {','.join(columns)} FROM {table} WHERE {key_column}=?",
            (key_value,),
        ).fetchone()
        if row is not None:
            if not self._row_matches(row, columns, values):
                raise DurableExecutionError(f"{table} replay payload conflict")
            return
        placeholders = ",".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
            values,
        )

    def _persist_decision_graph(
        self,
        *,
        trade_intent: dict[str, Any],
        risk_decision: dict[str, Any],
        equity_usdt: Decimal,
        context: dict[str, Any],
        observed_at: datetime,
    ) -> dict[str, Any]:
        session_id = str(context.get("session_id", ""))
        cycle_id = str(context.get("cycle_id", ""))
        symbol = str(trade_intent.get("symbol", ""))
        if not session_id or not cycle_id or not symbol:
            raise DurableExecutionError("durable execution context is incomplete")
        if context.get("mode") != self.mode:
            raise DurableExecutionError("durable execution mode drift")

        session_started = _utc_datetime(
            context.get("session_started_at"), "session_started_at"
        )
        created_text = utc_text(observed_at)
        session_text = utc_text(session_started)
        trade_intent_id = self._identity("trade_", session_id, cycle_id)
        risk_decision_id = self._identity("risk_", session_id, cycle_id)
        execution_intent_id = self._identity("execution_", session_id, cycle_id)
        action = str(trade_intent.get("action", ""))
        normalized_hash = hashlib.sha256(
            _canonical_json({"cycle_id": cycle_id, "intent": trade_intent}).encode(
                "utf-8"
            )
        ).hexdigest()
        position_pct = _decimal(
            trade_intent.get("position_size_pct", 0), "position_size_pct"
        )
        notional = equity_usdt * position_pct / Decimal(100)

        session_columns = (
            "session_id",
            "started_at",
            "mode",
            "status",
            "stopped_at",
            "stop_reason",
        )
        session_values = (session_id, session_text, self.mode, "RUNNING", None, None)
        cycle_columns = (
            "cycle_id",
            "session_id",
            "symbol",
            "started_at",
            "completed_at",
            "status",
            "last_completed_stage",
            "last_error",
        )
        cycle_values = (
            cycle_id,
            session_id,
            symbol,
            created_text,
            None,
            "RISK_DECIDED",
            "RISK_DECIDED",
            None,
        )
        trade_columns = (
            "trade_intent_id",
            "symbol",
            "action",
            "confidence",
            "thesis",
            "evidence",
            "position_size_pct",
            "stop_loss_pct",
            "take_profit_pct",
            "invalidation_conditions",
            "selected_strategy_ids",
            "created_at",
        )
        trade_values = (
            trade_intent_id,
            symbol,
            action,
            decimal_text(_decimal(trade_intent.get("confidence", 0), "confidence")),
            str(trade_intent.get("thesis", "")),
            _canonical_json(trade_intent.get("evidence", [])),
            decimal_text(position_pct),
            decimal_text(
                _decimal(trade_intent.get("stop_loss_pct", 0), "stop_loss_pct")
            ),
            decimal_text(
                _decimal(trade_intent.get("take_profit_pct", 0), "take_profit_pct")
            ),
            _canonical_json(trade_intent.get("invalidation_conditions", [])),
            _canonical_json(trade_intent.get("selected_strategy_ids", [])),
            created_text,
        )
        risk_columns = (
            "risk_decision_id",
            "trade_intent_id",
            "decision",
            "reasons",
            "risk_score",
            "checks_json",
            "created_at",
        )
        risk_values = (
            risk_decision_id,
            trade_intent_id,
            str(risk_decision.get("decision", "")),
            _canonical_json(risk_decision.get("reasons", [])),
            decimal_text(_decimal(risk_decision.get("risk_score", 0), "risk_score")),
            _canonical_json(risk_decision.get("checks", {})),
            created_text,
        )

        with self._db.transaction(immediate=True) as connection:
            self._insert_or_verify(
                connection,
                table="runtime_sessions",
                key_column="session_id",
                key_value=session_id,
                columns=session_columns,
                values=session_values,
            )
            cycle_row = connection.execute(
                "SELECT cycle_id,session_id,symbol,started_at FROM runtime_cycles "
                "WHERE cycle_id=?",
                (cycle_id,),
            ).fetchone()
            if cycle_row is None:
                self._insert_or_verify(
                    connection,
                    table="runtime_cycles",
                    key_column="cycle_id",
                    key_value=cycle_id,
                    columns=cycle_columns,
                    values=cycle_values,
                )
            elif tuple(
                cycle_row[column]
                for column in ("cycle_id", "session_id", "symbol", "started_at")
            ) != (cycle_id, session_id, symbol, created_text):
                raise DurableExecutionError("runtime_cycles replay payload conflict")
            self._insert_or_verify(
                connection,
                table="trade_intents",
                key_column="trade_intent_id",
                key_value=trade_intent_id,
                columns=trade_columns,
                values=trade_values,
            )
            self._insert_or_verify(
                connection,
                table="risk_decisions",
                key_column="risk_decision_id",
                key_value=risk_decision_id,
                columns=risk_columns,
                values=risk_values,
            )
            if risk_decision.get("decision") == "APPROVED" and action in {
                "BUY",
                "SELL",
            }:
                if notional <= 0:
                    raise DurableExecutionError(
                        "approved execution notional must be positive"
                    )
                execution_columns = (
                    "execution_intent_id",
                    "trade_intent_id",
                    "risk_decision_id",
                    "cycle_id",
                    "symbol",
                    "action",
                    "notional",
                    "normalized_intent_hash",
                    "created_at",
                )
                execution_values = (
                    execution_intent_id,
                    trade_intent_id,
                    risk_decision_id,
                    cycle_id,
                    symbol,
                    action,
                    decimal_text(notional),
                    normalized_hash,
                    created_text,
                )
                self._insert_or_verify(
                    connection,
                    table="execution_intents",
                    key_column="execution_intent_id",
                    key_value=execution_intent_id,
                    columns=execution_columns,
                    values=execution_values,
                )

        return {
            "session_id": session_id,
            "cycle_id": cycle_id,
            "execution_intent_id": execution_intent_id,
            "symbol": symbol,
            "action": action,
            "normalized_intent_hash": normalized_hash,
            "notional": notional,
            "created_at": observed_at,
        }

    def _complete_cycle(self, cycle_id: str, observed_at: datetime) -> None:
        with self._db.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE runtime_cycles SET status='COMPLETED',"
                "last_completed_stage='COMPLETED',completed_at=?,last_error=NULL "
                "WHERE cycle_id=? AND status IN ('RISK_DECIDED','COMPLETED')",
                (utc_text(observed_at), cycle_id),
            )
            if cursor.rowcount != 1:
                raise DurableExecutionError("runtime cycle completion CAS failed")

    @_recovery_guard
    def execute(
        self,
        trade_intent: dict,
        risk_decision: dict,
        mark_price: float,
        equity_usdt: float,
        *,
        execution_context: dict[str, Any] | None = None,
    ) -> ExecutionResult:
        if execution_context is None:
            raise DurableExecutionError("durable execution context is required")
        observed_at = _utc_datetime(execution_context.get("observed_at"), "observed_at")
        mark = _decimal(mark_price, "mark_price", positive=True)
        equity = _decimal(equity_usdt, "equity_usdt", positive=True)
        graph = self._persist_decision_graph(
            trade_intent=trade_intent,
            risk_decision=risk_decision,
            equity_usdt=equity,
            context=execution_context,
            observed_at=observed_at,
        )

        action = graph["action"]
        if risk_decision.get("decision") != "APPROVED" or action == "HOLD":
            self._complete_cycle(graph["cycle_id"], observed_at)
            status = "NOOP_HOLD" if action == "HOLD" else "BLOCKED_BY_RISK"
            return ExecutionResult(
                order_id=self._identity(
                    "noop_", graph["session_id"], graph["cycle_id"]
                ),
                status=status,
                symbol=graph["symbol"],
                action=action,
                price=float(mark),
                notional=0.0,
                fee=0.0,
                timestamp=utc_text(observed_at),
                mode=self.mode,
                durable_outcome="NO_EXECUTION_INTENT",
            )

        side = OrderSide(action)
        command = ExecutionIdempotencyCommand(
            execution_intent_id=graph["execution_intent_id"],
            venue=self.venue,
            account_scope=self.account_scope,
            symbol=graph["symbol"],
            action=side,
            normalized_intent_hash=graph["normalized_intent_hash"],
            created_at=observed_at,
        )
        claim_result = self._idempotency.claim_execution(command)
        if claim_result.execution_status is ExecutionStatus.PREPARED:
            dispatch = self._idempotency.commit_dispatch(
                DispatchCommitCommand(graph["execution_intent_id"], observed_at)
            )
            attempt_id = dispatch.attempt_id
        else:
            attempt_id = derive_attempt_id(claim_result.claim.idempotency_key, 1)

        with localcontext() as context:
            context.prec = 34
            quantity = (graph["notional"] / mark).quantize(Decimal("0.00000001"))
        if quantity <= 0:
            raise DurableExecutionError("simulated quantity rounded to zero")
        envelope = PaperExecutionEnvelope(
            execution_intent_id=graph["execution_intent_id"],
            idempotency_key=claim_result.claim.idempotency_key,
            attempt_id=attempt_id,
            client_order_id=claim_result.claim.client_order_id,
            venue=self.venue,
            account_scope=self.account_scope,
            symbol=graph["symbol"],
            side=side,
            quantity=quantity,
            mark_price=mark,
            fee_currency="USDT",
            observed_at=observed_at,
        )
        plan = self._builder.build(envelope)
        durable_result = self._coordinator.execute(envelope)
        self._complete_cycle(graph["cycle_id"], observed_at)
        status = "SHADOW_SIMULATED" if self.mode == "shadow" else "FILLED_SIMULATED"
        return ExecutionResult(
            order_id=durable_result.order_id,
            status=status,
            symbol=graph["symbol"],
            action=action,
            price=float(plan.execution_price),
            notional=float(graph["notional"]),
            fee=float(plan.fee),
            timestamp=utc_text(observed_at),
            mode=self.mode,
            execution_intent_id=graph["execution_intent_id"],
            fill_id=durable_result.fill_id,
            durable_outcome=durable_result.outcome.value,
        )
