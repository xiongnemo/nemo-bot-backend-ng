"""
TopicStore — mid-term episodic memory (topics table) access layer.
"""

from __future__ import annotations

import time

from .database import Database


class TopicStore:
    def __init__(self, db: Database):
        self.db = db

    def add(self, scope_key: str, summary: str, ts: float | None = None) -> None:
        conn = self.db.get_conn()
        conn.execute(
            "INSERT INTO topics (scope_key, topic_summary, created_at) VALUES (?, ?, ?)",
            (scope_key, summary, ts or time.time()),
        )
        conn.commit()

    def recent(self, scope_key: str, limit: int = 5) -> list[str]:
        conn = self.db.get_conn()
        cur = conn.execute(
            "SELECT topic_summary FROM topics WHERE scope_key = ? ORDER BY created_at DESC LIMIT ?",
            (scope_key, limit),
        )
        return [r[0] for r in cur.fetchall()]

    def prune(self, days: float) -> int:
        if days <= 0:
            return 0
        conn = self.db.get_conn()
        cur = conn.execute(
            "DELETE FROM topics WHERE created_at < ?",
            (time.time() - days * 86400,),
        )
        conn.commit()
        return cur.rowcount
