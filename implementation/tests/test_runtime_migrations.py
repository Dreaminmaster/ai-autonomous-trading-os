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
    assert applied == 1

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
    assert mm.migrate() == 1
    assert mm.migrate() == 0
    # schema_migrations should have exactly 1 row
    count = db.connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    assert count == 1
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
    # Tamper with the schema_migrations checksum
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
    # Create a bad migration that will fail after creating a table
    bad_migration = Migration(
        version=1,
        name="bad",
        sql="CREATE TABLE partial_x (id INTEGER PRIMARY KEY); INVALID_SQL_HERE;",
    )
    mm = MigrationManager(db, [bad_migration])
    mm.bootstrap()
    with pytest.raises(MigrationApplyError):
        mm.migrate()
    # partial_x must not exist
    tables = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='partial_x'"
    ).fetchall()
    assert len(tables) == 0
    # migration row must not exist
    migrations = db.connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert len(migrations) == 0
    db.close()
