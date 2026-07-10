"""Fail-closed migration engine — no partial state, no drift, no gaps."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Sequence

from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError
import sqlite3


class MigrationDefinitionError(RuntimePersistenceError):
    """Migration plan is malformed."""


class MigrationDriftError(RuntimePersistenceError):
    """Already-applied migration checksum does not match code definition."""


class SchemaCompatibilityError(RuntimePersistenceError):
    """DB schema is not compatible with the current code."""


class MigrationApplyError(RuntimePersistenceError):
    """Migration failed to apply — DB is unchanged."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str

    @property
    def checksum(self) -> str:
        return sha256(self.sql.encode("utf-8")).hexdigest()


_MIGRATION_0001_SQL = """
CREATE TABLE runtime_sessions (
    session_id   TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,
    mode         TEXT NOT NULL CHECK (mode IN ('paper','shadow','guarded')),
    status       TEXT NOT NULL CHECK (status IN (
        'STARTING','RECOVERING','READY','RUNNING',
        'PAUSED','PAUSED_RECOVERY_REQUIRED','STOPPED'
    )),
    stopped_at   TEXT NULL,
    stop_reason  TEXT NULL
);

CREATE TABLE runtime_cycles (
    cycle_id              TEXT PRIMARY KEY,
    session_id            TEXT NOT NULL REFERENCES runtime_sessions(session_id)
                          ON DELETE RESTRICT,
    symbol                TEXT NOT NULL,
    started_at            TEXT NOT NULL,
    completed_at          TEXT NULL,
    status                TEXT NOT NULL CHECK (status IN (
        'CREATED','MARKET_ACCEPTED','ACCOUNT_ACCEPTED',
        'CANDIDATES_READY','PROVIDER_DECIDED','RISK_DECIDED',
        'EXECUTION_INTENT_CREATED','EXECUTED','RECONCILED','COMPLETED'
    )),
    last_completed_stage  TEXT NULL,
    last_error            TEXT NULL
);

CREATE INDEX idx_cycles_session_status ON runtime_cycles(session_id, status);
CREATE INDEX idx_cycles_symbol_time ON runtime_cycles(symbol, started_at);

CREATE TABLE recovery_states (
    recovery_id      TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL REFERENCES runtime_sessions(session_id)
                     ON DELETE RESTRICT,
    status           TEXT NOT NULL CHECK (status IN (
        'PENDING','IN_PROGRESS','RESOLVED','FAILED'
    )),
    unresolved_items TEXT NOT NULL DEFAULT '[]',
    started_at       TEXT NOT NULL,
    recovered_at     TEXT NULL
);

CREATE INDEX idx_recovery_session_status ON recovery_states(session_id, status);
"""




_MIGRATION_0002_SQL = """
CREATE TABLE cycle_journal (
    journal_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id     TEXT NOT NULL REFERENCES runtime_cycles(cycle_id) ON DELETE RESTRICT,
    from_state   TEXT NOT NULL,
    to_state     TEXT NOT NULL,
    recorded_at  TEXT NOT NULL
);
CREATE INDEX idx_cycle_journal_cycle ON cycle_journal(cycle_id, journal_id);
"""

_MIGRATION_0003_SQL = """
CREATE TABLE trade_intents (
    trade_intent_id          TEXT PRIMARY KEY,
    symbol                   TEXT NOT NULL,
    action                   TEXT NOT NULL CHECK (action IN ('BUY','SELL','HOLD')),
    confidence               TEXT NOT NULL,
    thesis                   TEXT NOT NULL,
    evidence                 TEXT NOT NULL,
    position_size_pct        TEXT NOT NULL,
    stop_loss_pct            TEXT NOT NULL,
    take_profit_pct          TEXT NOT NULL,
    invalidation_conditions  TEXT NOT NULL,
    selected_strategy_ids    TEXT NOT NULL,
    created_at               TEXT NOT NULL
);
CREATE TRIGGER trg_trade_intents_no_update BEFORE UPDATE ON trade_intents BEGIN SELECT RAISE(ABORT,'trade_intents are immutable'); END;
CREATE TRIGGER trg_trade_intents_no_delete BEFORE DELETE ON trade_intents BEGIN SELECT RAISE(ABORT,'trade_intents are immutable'); END;

CREATE TABLE risk_decisions (
    risk_decision_id  TEXT PRIMARY KEY,
    trade_intent_id   TEXT NOT NULL REFERENCES trade_intents(trade_intent_id) ON DELETE RESTRICT,
    decision          TEXT NOT NULL CHECK (decision IN ('APPROVED','REJECTED','KILL_SWITCH_ACTIVE','PAUSED')),
    reasons           TEXT NOT NULL,
    risk_score        TEXT NOT NULL,
    checks_json       TEXT NOT NULL,
    created_at        TEXT NOT NULL,
    UNIQUE(risk_decision_id, trade_intent_id)
);
CREATE INDEX idx_risk_decisions_trade_intent ON risk_decisions(trade_intent_id);
CREATE TRIGGER trg_risk_decisions_no_update BEFORE UPDATE ON risk_decisions BEGIN SELECT RAISE(ABORT,'risk_decisions are immutable'); END;
CREATE TRIGGER trg_risk_decisions_no_delete BEFORE DELETE ON risk_decisions BEGIN SELECT RAISE(ABORT,'risk_decisions are immutable'); END;

CREATE TABLE execution_intents (
    execution_intent_id      TEXT PRIMARY KEY,
    trade_intent_id          TEXT NOT NULL REFERENCES trade_intents(trade_intent_id) ON DELETE RESTRICT,
    risk_decision_id         TEXT NOT NULL,
    cycle_id                 TEXT NOT NULL REFERENCES runtime_cycles(cycle_id) ON DELETE RESTRICT,
    symbol                   TEXT NOT NULL,
    action                   TEXT NOT NULL CHECK (action IN ('BUY','SELL')),
    notional                 TEXT NOT NULL,
    normalized_intent_hash   TEXT NOT NULL CHECK (length(normalized_intent_hash) = 64 AND normalized_intent_hash NOT GLOB "*[^0-9a-f]*" AND normalized_intent_hash = lower(normalized_intent_hash)),
    created_at               TEXT NOT NULL,
    FOREIGN KEY (risk_decision_id, trade_intent_id) REFERENCES risk_decisions(risk_decision_id, trade_intent_id) ON DELETE RESTRICT
);
CREATE INDEX idx_execution_intents_cycle ON execution_intents(cycle_id);
CREATE INDEX idx_execution_intents_trade_intent ON execution_intents(trade_intent_id);
CREATE TRIGGER trg_execution_intents_no_update BEFORE UPDATE ON execution_intents BEGIN SELECT RAISE(ABORT,'execution_intents are immutable'); END;
CREATE TRIGGER trg_execution_intents_no_delete BEFORE DELETE ON execution_intents BEGIN SELECT RAISE(ABORT,'execution_intents are immutable'); END;

CREATE TABLE dispatch_attempts (
    attempt_id           TEXT PRIMARY KEY,
    execution_intent_id  TEXT NOT NULL REFERENCES execution_intents(execution_intent_id) ON DELETE RESTRICT,
    client_order_id      TEXT NOT NULL,
    venue                TEXT NOT NULL,
    account_scope        TEXT NOT NULL,
    status               TEXT NOT NULL CHECK (status IN ('PRE_DISPATCH_PROVEN','DISPATCH_INITIATED','SUBMITTED','ACCEPTED','REJECTED','TIMEOUT','AMBIGUOUS')),
    attempt_no           INTEGER NOT NULL CHECK (attempt_no >= 1),
    created_at           TEXT NOT NULL,
    dispatch_started_at  TEXT NULL,
    response_received_at TEXT NULL,
    error_class          TEXT NULL,
    UNIQUE(execution_intent_id, attempt_no),
    UNIQUE(execution_intent_id, attempt_id)
);
CREATE INDEX idx_dispatch_attempts_execution ON dispatch_attempts(execution_intent_id);
CREATE INDEX idx_dispatch_attempts_client_order ON dispatch_attempts(client_order_id);

CREATE TABLE execution_states (
    execution_intent_id  TEXT PRIMARY KEY REFERENCES execution_intents(execution_intent_id) ON DELETE RESTRICT,
    status               TEXT NOT NULL CHECK (status IN ('PREPARED','DISPATCH_COMMITTED','DISPATCHED','ACKNOWLEDGED','AMBIGUOUS','FILLED','TERMINAL')),
    last_attempt_id      TEXT NULL,
    retry_count          INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    state_started_at     TEXT NOT NULL,
    updated_at           TEXT NOT NULL,
    FOREIGN KEY (execution_intent_id, last_attempt_id) REFERENCES dispatch_attempts(execution_intent_id, attempt_id) ON DELETE RESTRICT
);
CREATE INDEX idx_execution_states_status ON execution_states(status);
"""

MIGRATION_PLAN: tuple[Migration, ...] = (
    Migration(version=1, name="runtime_session_cycle_recovery", sql=_MIGRATION_0001_SQL),
    Migration(version=2, name="cycle_journal", sql=_MIGRATION_0002_SQL),
    Migration(version=3, name="execution_transaction_persistence", sql=_MIGRATION_0003_SQL),
)


def _iter_sql_statements(sql):
    """Yield complete SQL statements using sqlite3.complete_statement."""
    buffer = ""
    for line in sql.splitlines():
        buffer += line + "\n"
        if buffer.strip() and sqlite3.complete_statement(buffer):
            stmt = buffer.strip()
            if stmt:
                yield stmt
            buffer = ""
    if buffer.strip():
        raise MigrationDefinitionError(
            f"Incomplete SQL statement at end of migration: {buffer[:100]}"
        )


class MigrationManager:
    """Manage database schema migrations.

    Invariants:
      - Versions must be contiguous starting from 1.
      - Already-applied migrations must match checksum exactly.
      - DB with version > code max version is rejected.
      - Each migration runs in a single atomic transaction.
    """

    BOOTSTRAP_SQL = """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version    INTEGER PRIMARY KEY CHECK (version >= 1),
            name       TEXT NOT NULL,
            checksum   TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
    """

    def __init__(self, db: RuntimeDatabase, plan: Sequence[Migration]):
        self.db = db
        self.plan = tuple(plan)
        self._validate_plan()

    def _validate_plan(self) -> None:
        versions = [m.version for m in self.plan]
        if versions != list(range(1, len(versions) + 1)):
            raise MigrationDefinitionError(
                f"Migration versions must be contiguous starting from 1, got {versions}"
            )

    def bootstrap(self) -> None:
        """Ensure schema_migrations table exists. Idempotent."""
        self.db.connection.execute(self.BOOTSTRAP_SQL)
        self.db.connection.commit()

    def applied_migrations(self):
        """Return tuples of (version, name, checksum) from DB."""
        return self.db.connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
        ).fetchall()

    def current_version(self) -> int:
        row = self.db.connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()
        return row[0] or 0

    def validate_plan(self) -> None:
        """Fail closed if DB is incompatible with the migration plan."""
        applied = self.applied_migrations()
        code_max = len(self.plan)

        applied_versions: set[int] = set()
        for a in applied:
            db_ver = a["version"]
            db_name = a["name"]
            db_csum = a["checksum"]
            applied_versions.add(db_ver)

            if db_ver > code_max:
                raise SchemaCompatibilityError(
                    f"DB has migration version {db_ver} > code max version {code_max}"
                )
            if db_ver < 1:
                raise SchemaCompatibilityError(
                    f"DB has migration version {db_ver} < 1 — not allowed"
                )
            code_m = self.plan[db_ver - 1]
            if db_name != code_m.name or db_csum != code_m.checksum:
                raise MigrationDriftError(
                    f"Migration {db_ver} '{db_name}' checksum {db_csum[:12]} "
                    f"does not match code {code_m.checksum[:12]}"
                )

        # Check for gaps
        if applied_versions:
            max_applied = max(applied_versions)
            for v in range(1, max_applied + 1):
                if v not in applied_versions and v <= code_max:
                    raise SchemaCompatibilityError(
                        f"Migration gap: version {v} is missing from schema_migrations"
                    )

    def migrate(self) -> int:
        """Apply all unapplied migrations. Returns number applied."""
        self.bootstrap()
        self.validate_plan()
        current = self.current_version()
        count = 0

        for m in self.plan:
            if m.version <= current:
                continue
            with self.db.transaction(immediate=True) as conn:
                try:
                    # executescript() issues implicit commits — not safe for transactions.
                    # Execute each statement separately so a failure rolls back the full transaction.
                    for stmt in _iter_sql_statements(m.sql):
                        stmt = stmt.strip()
                        if stmt:
                            conn.execute(stmt)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
                        "VALUES (?, ?, ?, datetime('now'))",
                        (m.version, m.name, m.checksum),
                    )
                except Exception as e:
                    raise MigrationApplyError(
                        f"Migration {m.version} '{m.name}' failed: {e}"
                    ) from e
            count += 1

        return count
