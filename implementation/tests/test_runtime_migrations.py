"""Tests for MigrationManager — fail-closed migration engine."""
import tempfile
from pathlib import Path
import pytest
from atos.runtime_db import RuntimeDatabase
from atos.runtime_migrations import (
    Migration, MigrationManager, MIGRATION_PLAN,
    MigrationDefinitionError, MigrationDriftError,
    SchemaCompatibilityError, MigrationApplyError,
)


def _make_db():
    d = tempfile.mkdtemp()
    path = Path(d) / f"test_{id(object())}.db"
    db = RuntimeDatabase(path)
    db.connect()
    return db


def test_migration_0001_creates_all_tables():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    applied = mm.migrate()
    assert applied >= 1

    tables = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    table_names = {r[0] for r in tables}
    assert "schema_migrations" in table_names
    assert "runtime_sessions" in table_names
    assert "runtime_cycles" in table_names
    assert "recovery_states" in table_names
    db.close()


def test_migrate_twice_is_noop():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    assert mm.migrate() >= 1
    assert mm.migrate() == 0
    count = db.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count >= 1
    db.close()


def test_cycle_rejects_missing_session_fk():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    mm.migrate()
    with pytest.raises(Exception):
        db.connection.execute(
            "INSERT INTO runtime_cycles (cycle_id, session_id, symbol, started_at, status) "
            "VALUES ('c1', 'nonexistent', 'BTC/USDT', datetime('now'), 'CREATED')"
        )
    db.close()


def test_recovery_rejects_missing_session_fk():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    mm.migrate()
    with pytest.raises(Exception):
        db.connection.execute(
            "INSERT INTO recovery_states (recovery_id, session_id, status, started_at) "
            "VALUES ('r1', 'nonexistent', 'PENDING', datetime('now'))"
        )
    db.close()


def test_invalid_session_mode_rejected():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    mm.migrate()
    with pytest.raises(Exception):
        db.connection.execute(
            "INSERT INTO runtime_sessions (session_id, started_at, mode, status) "
            "VALUES ('s1', datetime('now'), 'INVALID_MODE', 'STARTING')"
        )
    db.close()


def test_invalid_session_status_rejected():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    mm.migrate()
    with pytest.raises(Exception):
        db.connection.execute(
            "INSERT INTO runtime_sessions (session_id, started_at, mode, status) "
            "VALUES ('s1', datetime('now'), 'paper', 'INVALID_STATUS')"
        )
    db.close()


def test_invalid_cycle_status_rejected():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    mm.migrate()
    db.connection.execute(
        "INSERT INTO runtime_sessions (session_id, started_at, mode, status) "
        "VALUES ('s1', datetime('now'), 'paper', 'READY')"
    )
    with pytest.raises(Exception):
        db.connection.execute(
            "INSERT INTO runtime_cycles (cycle_id, session_id, symbol, started_at, status) "
            "VALUES ('c1', 's1', 'BTC/USDT', datetime('now'), 'INVALID_STATUS')"
        )
    db.close()


def test_invalid_recovery_status_rejected():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    mm.migrate()
    db.connection.execute(
        "INSERT INTO runtime_sessions (session_id, started_at, mode, status) "
        "VALUES ('s1', datetime('now'), 'paper', 'READY')"
    )
    with pytest.raises(Exception):
        db.connection.execute(
            "INSERT INTO recovery_states (recovery_id, session_id, status, started_at) "
            "VALUES ('r1', 's1', 'INVALID_STATUS', datetime('now'))"
        )
    db.close()


def test_migration_checksum_drift_fails_closed():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    mm.migrate()
    db.connection.execute("UPDATE schema_migrations SET checksum = 'bad' WHERE version = 1")
    db.connection.commit()
    with pytest.raises(MigrationDriftError):
        mm.validate_plan()
    db.close()


def test_future_db_version_fails_closed():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    mm.bootstrap()
    db.connection.execute(
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
        "VALUES (999, 'future', 'abc', datetime('now'))"
    )
    db.connection.commit()
    with pytest.raises(SchemaCompatibilityError):
        mm.validate_plan()
    db.close()


def test_migration_plan_must_be_contiguous():
    bad_plan = (Migration(version=1, name="a", sql="SELECT 1"), Migration(version=3, name="c", sql="SELECT 2"))
    with pytest.raises(MigrationDefinitionError):
        MigrationManager(None, bad_plan)


def test_failed_migration_rolls_back_schema_and_history():
    db = _make_db()
    bad_migration = Migration(
        version=1,
        name="bad",
        sql="CREATE TABLE partial_x (id INTEGER PRIMARY KEY);\nINVALID_SQL_HERE;",
    )
    mm = MigrationManager(db, [bad_migration])
    mm.bootstrap()
    with pytest.raises(MigrationApplyError):
        mm.migrate()
    tables = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='partial_x'"
    ).fetchall()
    assert len(tables) == 0
    migrations = db.connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert len(migrations) == 0
    db.close()


# ═══════════════════════════════════════════════════════════════
# P1: Real migration gap in DB history
# ═══════════════════════════════════════════════════════════════

def test_migration_gap_fails_closed():
    """DB has only version 2 applied (name+checksum correct), missing v1 → fail."""
    db = _make_db()
    plan = (
        Migration(version=1, name="first", sql="SELECT 1"),
        Migration(version=2, name="second", sql="SELECT 2"),
    )
    mm = MigrationManager(db, plan)
    mm.bootstrap()
    # Insert version 2 directly — simulate v1 never applied
    m2 = plan[1]
    db.connection.execute(
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
        "VALUES (?, ?, ?, datetime('now'))",
        (m2.version, m2.name, m2.checksum),
    )
    db.connection.commit()
    with pytest.raises(SchemaCompatibilityError):
        mm.validate_plan()
    db.close()


# ═══════════════════════════════════════════════════════════════
# P2: Non-positive applied versions
# ═══════════════════════════════════════════════════════════════

def test_applied_version_zero_fails_closed():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    mm.bootstrap()
    db.connection.execute("ALTER TABLE schema_migrations RENAME TO sm_old")
    db.connection.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, checksum TEXT, applied_at TEXT)"
    )
    db.connection.execute(
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
        "VALUES (0, 'bad', 'abc', datetime('now'))"
    )
    db.connection.commit()
    with pytest.raises(SchemaCompatibilityError):
        mm.validate_plan()
    db.close()


def test_applied_negative_version_fails_closed():
    db = _make_db()
    mm = MigrationManager(db, MIGRATION_PLAN)
    mm.bootstrap()
    db.connection.execute("ALTER TABLE schema_migrations RENAME TO sm_old")
    db.connection.execute(
        "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, name TEXT, checksum TEXT, applied_at TEXT)"
    )
    db.connection.execute(
        "INSERT INTO schema_migrations (version, name, checksum, applied_at) "
        "VALUES (-1, 'bad', 'abc', datetime('now'))"
    )
    db.connection.commit()
    with pytest.raises(SchemaCompatibilityError):
        mm.validate_plan()
    db.close()


# ═══════════════════════════════════════════════════════════════
# P3: Semicolon inside SQL literal — safe parsing
# ═══════════════════════════════════════════════════════════════

def test_migration_sql_semicolon_inside_string():
    """_iter_sql_statements must handle semicolons within string literals."""
    from atos.runtime_migrations import _iter_sql_statements
    sql = (
        "CREATE TABLE x (v TEXT);\n"
        "INSERT INTO x(v) VALUES ('a;b');\n"
    )
    stmts = list(_iter_sql_statements(sql))
    assert len(stmts) == 2
    assert stmts[0] == "CREATE TABLE x (v TEXT);"
    assert "INSERT" in stmts[1]
    assert "a;b" in stmts[1]


# ═══════════════════════════════════════════════════════════════
# P4: Deferred transaction is explicit
# ═══════════════════════════════════════════════════════════════

def test_deferred_transaction_is_explicit():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    try:
        with db.transaction(immediate=False) as conn:
            conn.execute("CREATE TABLE t1 (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO t1 VALUES (1)")
            raise ValueError("simulated")
    except ValueError:
        pass
    rows = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='t1'"
    ).fetchall()
    assert len(rows) == 0
    db.close()


# ═══════════════════════════════════════════════════════════════
# P5: connect() idempotency
# ═══════════════════════════════════════════════════════════════

def test_connect_twice_returns_same_connection():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    c1 = db.connect()
    c2 = db.connect()
    assert c1 is c2
    db.close()
