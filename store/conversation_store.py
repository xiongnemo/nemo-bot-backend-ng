"""
ConversationStore — per-scope LLM conversation history in SQLite.

Each "scope" is a string like:
    "chat_gemini:satori_http:group_485541033:user_3240295516"
that uniquely identifies a conversation thread.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .database import Database

logger = logging.getLogger(__name__)


class ConversationStore:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get_history(
        self,
        scope_key: str,
        max_turns: int = 30,
    ) -> list[dict]:
        """
        Return the last *max_turns* messages for *scope_key*,
        oldest-first.  Each dict has: role, content, metadata_json.
        """
        conn = self.db.get_conn()
        rows = conn.execute(
            """SELECT role, content, metadata_json FROM conversations
               WHERE scope_key = ?
               ORDER BY created_at DESC LIMIT ?""",
            (scope_key, max_turns),
        ).fetchall()
        result = []
        for r in reversed(rows):
            entry: dict[str, Any] = {"role": r[0], "content": r[1]}
            if r[2]:
                try:
                    entry["metadata"] = json.loads(r[2])
                except json.JSONDecodeError:
                    pass
            result.append(entry)
        return result

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def append(
        self,
        scope_key: str,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> None:
        conn = self.db.get_conn()
        conn.execute(
            """INSERT INTO conversations
               (scope_key, role, content, metadata_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                scope_key,
                role,
                content,
                json.dumps(metadata, ensure_ascii=False) if metadata else "",
                time.time(),
            ),
        )
        conn.commit()

    def append_pair(
        self,
        scope_key: str,
        user_content: str,
        assistant_content: str,
    ) -> None:
        """Convenience: append a user + assistant turn pair."""
        now = time.time()
        conn = self.db.get_conn()
        conn.executemany(
            """INSERT INTO conversations
               (scope_key, role, content, metadata_json, created_at)
               VALUES (?, ?, ?, '', ?)""",
            [
                (scope_key, "user", user_content, now),
                (scope_key, "assistant", assistant_content, now + 0.001),
            ],
        )
        conn.commit()

    # ------------------------------------------------------------------
    # Clear
    # ------------------------------------------------------------------

    def clear(self, scope_key: str) -> int:
        conn = self.db.get_conn()
        cur = conn.execute(
            "DELETE FROM conversations WHERE scope_key = ?",
            (scope_key,),
        )
        conn.commit()
        return cur.rowcount

    def clear_all(self) -> int:
        conn = self.db.get_conn()
        cur = conn.execute("DELETE FROM conversations")
        conn.commit()
        return cur.rowcount
