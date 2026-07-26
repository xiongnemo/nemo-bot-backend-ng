"""
MessageStore — full-message ingest + FTS5 search.

Every message that enters /ingest gets stored here so the agent can
explore chat context (recent messages, keyword search).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .database import Database

logger = logging.getLogger(__name__)


class MessageStore:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def ingest(
        self,
        *,
        frontend: str,
        group_id: str,
        user_id: str,
        user_name: str = "",
        text: str,
        message_id: str = "",
        ated: bool = False,
        imgs: list[str] | None = None,
        raw_message: Any = "",
        timestamp: float | None = None,
    ) -> int:
        """Store a message and return its row id."""
        conn = self.db.get_conn()
        ts = timestamp or time.time()
        cur = conn.execute(
            """INSERT INTO messages
               (frontend, group_id, user_id, user_name, text,
                message_id, ated, imgs_json, raw_json, timestamp)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                frontend,
                group_id,
                user_id,
                user_name,
                text,
                message_id,
                int(ated),
                json.dumps(imgs or [], ensure_ascii=False),
                json.dumps(raw_message, ensure_ascii=False, default=str)
                    if raw_message else "",
                ts,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def recent(
        self,
        group_id: str = "",
        user_id: str = "",
        limit: int = 50,
    ) -> list[dict]:
        """Get the most recent messages for a group or user."""
        conn = self.db.get_conn()
        if group_id:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE group_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (group_id, limit),
            ).fetchall()
        elif user_id:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE user_id = ? AND group_id = ''
                   ORDER BY timestamp DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]  # oldest-first

    def search(
        self,
        query: str,
        group_id: str = "",
        limit: int = 20,
    ) -> list[dict]:
        """Full-text search via FTS5."""
        conn = self.db.get_conn()
        if group_id:
            rows = conn.execute(
                """SELECT m.* FROM messages m
                   JOIN messages_fts f ON m.id = f.rowid
                   WHERE messages_fts MATCH ? AND m.group_id = ?
                   ORDER BY m.timestamp DESC LIMIT ?""",
                (query, group_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT m.* FROM messages m
                   JOIN messages_fts f ON m.id = f.rowid
                   WHERE messages_fts MATCH ?
                   ORDER BY m.timestamp DESC LIMIT ?""",
                (query, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    def count(self, group_id: str = "") -> int:
        conn = self.db.get_conn()
        if group_id:
            row = conn.execute(
                "SELECT COUNT(*) FROM messages WHERE group_id = ?",
                (group_id,),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
        return row[0] if row else 0
