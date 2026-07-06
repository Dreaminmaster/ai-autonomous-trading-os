"""Tests for RuntimeDatabase — persistence foundation."""
import sqlite3
import tempfile
from pathlib import Path
import pytest
from atos.runtime_db import RuntimeDatabase, RuntimePersistenceError, DEFAULT_RUNTIME_DB_PATH


def test_default_path_is_expected():
    assert DEFAULT_RUNTIME_DB_PATH == "runtime/atos_runtime.sqlite"


def test_connect_creates_file():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    assert path.exists()
    db.close()


def test_foreign_keys_enabled():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    conn = db.connect()
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
    db.close()


def test_wal_enabled():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    conn = db.connect()
    wal = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert wal.lower() == "wal"
    db.close()


def test_synchronous_full():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    conn = db.connect()
    sync = conn.execute("PRAGMA synchronous").fetchone()[0]
    assert sync == 2  # FULL
    db.close()


def test_busy_timeout():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    conn = db.connect()
    timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert timeout == 5000
    db.close()


def test_transaction_commits():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    with db.transaction() as conn:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")
        conn.execute("INSERT INTO t VALUES (1)")
    row = db.connection.execute("SELECT id FROM t").fetchone()
    assert row[0] == 1
    db.close()


def test_transaction_rolls_back_on_exception():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    db.connect()
    try:
        with db.transaction() as conn:
            conn.execute("CREATE TABLE t1 (id INTEGER PRIMARY KEY)")
            conn.execute("INSERT INTO t1 VALUES (1)")
            raise ValueError("simulated crash")
    except ValueError:
        pass
    # Table should NOT exist
    rows = db.connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='t1'"
    ).fetchall()
    assert len(rows) == 0, f"Table t1 should not exist after rollback: {rows}"
    db.close()


def test_context_manager():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    with RuntimeDatabase(path) as db:
        assert db.conn is not None
    assert db.conn is None


def test_connection_property_auto_connects():
    d = tempfile.mkdtemp()
    path = Path(d) / "test.db"
    db = RuntimeDatabase(path)
    assert db.conn is None
    _ = db.connection
    assert db.conn is not None
    db.close()
