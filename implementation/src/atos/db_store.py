from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from atos.core import utc_now


class DatabaseStore:
    def __init__(self, path: str = "runtime/atos_store.sqlite"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.init_db()

    def init_db(self) -> None:
        self.conn.execute("CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, kind TEXT NOT NULL, payload_json TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, symbol TEXT NOT NULL, payload_json TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS candidates (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, symbol TEXT NOT NULL, strategy_id TEXT NOT NULL, payload_json TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS decisions (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, symbol TEXT NOT NULL, action TEXT NOT NULL, payload_json TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS assessments (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS outcomes (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, symbol TEXT NOT NULL, action TEXT NOT NULL, status TEXT NOT NULL, payload_json TEXT NOT NULL)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS scores (strategy_id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, trades INTEGER NOT NULL, wins INTEGER NOT NULL, losses INTEGER NOT NULL, avg_pnl_pct REAL NOT NULL, weight REAL NOT NULL, status TEXT NOT NULL)")
        self.conn.commit()

    def insert_json(self, table: str, columns: dict[str, Any], payload: dict[str, Any]) -> None:
        data = {**columns, "created_at": utc_now(), "payload_json": json.dumps(payload, ensure_ascii=False, sort_keys=True)}
        keys = list(data.keys())
        values = [data[k] for k in keys]
        placeholders = ", ".join(["?"] * len(keys))
        sql = f"INSERT INTO {table}({', '.join(keys)}) VALUES ({placeholders})"
        self.conn.execute(sql, values)
        self.conn.commit()
