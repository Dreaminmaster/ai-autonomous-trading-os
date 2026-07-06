"""Fail-closed migration engine — no partial state, no drift, no gaps."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Sequence

from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError


class MigrationDefinitionError(Exception):
    """Migration plan is malformed."""


class MigrationDriftError(Exception):
    """Already-applied migration checksum does not match code definition."""


class SchemaCompatibilityError(Exception):
    """DB schema is not compatible with the current code."""


class MigrationApplyError(Exception):
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


MIGRATION_PLAN: tuple[Migration, ...] = (
    Migration(version=1, name="runtime_session_cycle_recovery", sql=_MIGRATION_0001_SQL),
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
            version    INTEGER PRIMARY KEY,
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
            if db_ver < 1 or db_ver > code_max:
                continue
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
                    for stmt in m.sql.strip().split(";"):
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
