from __future__ import annotations

import sqlite3
import json
from pathlib import Path

from atos_core import utc_now


class LedgerStore:
    def __init__(self, path: str = 'runtime/ledger.sqlite'):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self._init_db()

    def _init_db(self) -> None:
        self.conn.execute('''
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload_json TEXT NOT NULL
        )
        ''')
        self.conn.commit()

    def record(self, kind: str, payload: dict) -> None:
        self.conn.execute(
            'INSERT INTO events(created_at, kind, payload_json) VALUES (?, ?, ?)',
            (utc_now(), kind, json.dumps(payload, ensure_ascii=False, sort_keys=True)),
        )
        self.conn.commit()

    def count(self) -> int:
        row = self.conn.execute('SELECT COUNT(*) FROM events').fetchone()
        return int(row[0])
