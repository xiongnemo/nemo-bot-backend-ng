"""
SQLite Key-Value Storage Engine.
Wraps the `kv` table in `store.database.Database`.
"""

from __future__ import annotations
import json
import logging
import time
from typing import Any

from .base import BaseKVEngine
from ..database import Database

logger = logging.getLogger(__name__)


class SqliteKVEngine(BaseKVEngine):
    def __init__(self, db: Database | None = None):
        self.db = db or Database()

    def get(self, namespace: str, scope: str, key: str, default: Any = None) -> Any:
        conn = self.db.get_conn()
        row = conn.execute(
            "SELECT value_json FROM kv WHERE namespace=? AND scope=? AND key=?",
            (namespace, scope, key),
        ).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row[0])
        except Exception:
            return row[0]

    def set(self, namespace: str, scope: str, key: str, value: Any) -> None:
        conn = self.db.get_conn()
        conn.execute(
            """INSERT INTO kv (namespace, scope, key, value_json, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(namespace, scope, key)
               DO UPDATE SET value_json=excluded.value_json,
                             updated_at=excluded.updated_at""",
            (namespace, scope, key, json.dumps(value, ensure_ascii=False), time.time()),
        )
        conn.commit()

    def delete(self, namespace: str, scope: str, key: str) -> bool:
        conn = self.db.get_conn()
        cur = conn.execute(
            "DELETE FROM kv WHERE namespace=? AND scope=? AND key=?",
            (namespace, scope, key),
        )
        conn.commit()
        return cur.rowcount > 0

    def list_keys(self, namespace: str, scope: str = "global") -> list[str]:
        conn = self.db.get_conn()
        rows = conn.execute(
            "SELECT key FROM kv WHERE namespace=? AND scope=? ORDER BY key",
            (namespace, scope),
        ).fetchall()
        return [r[0] for r in rows]

    def list_all(self, namespace: str, scope: str = "global") -> dict[str, Any]:
        conn = self.db.get_conn()
        rows = conn.execute(
            "SELECT key, value_json FROM kv WHERE namespace=? AND scope=?",
            (namespace, scope),
        ).fetchall()
        result = {}
        for r in rows:
            try:
                result[r[0]] = json.loads(r[1])
            except Exception:
                result[r[0]] = r[1]
        return result
