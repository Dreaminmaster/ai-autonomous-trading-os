from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from atos.core import utc_now


class Ledger:
    def __init__(self, path: str = "runtime/atos.sqlite"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.init_db()

    def init_db(self) -> None:
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        """)
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS strategy_scores (
            strategy_id TEXT PRIMARY KEY,
            updated_at TEXT NOT NULL,
            trades INTEGER NOT NULL,
            wins INTEGER NOT NULL,
            losses INTEGER NOT NULL,
            avg_pnl_pct REAL NOT NULL,
            weight REAL NOT NULL,
            status TEXT NOT NULL
        )
        """)
        self.conn.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            side TEXT NOT NULL,
            qty REAL NOT NULL,
            avg_price REAL NOT NULL,
            status TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            closed_at TEXT
        )
        """)
        self.conn.commit()

    def record(self, kind: str, payload: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO events(created_at, kind, payload_json) VALUES (?, ?, ?)",
            (utc_now(), kind, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()

    def list_events(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT created_at, kind, payload_json FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [{"created_at": r[0], "kind": r[1], "payload": json.loads(r[2])} for r in rows]

    def count(self) -> int:
        row = self.conn.execute("SELECT COUNT(*) FROM events").fetchone()
        return int(row[0])
