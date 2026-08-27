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
        created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        cur = conn.execute(
            """INSERT INTO messages
               (frontend, group_id, user_id, user_name, text,
                message_id, ated, imgs_json, raw_json, timestamp, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                created_at,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]

    def exists(self, message_id: str) -> bool:
        if not message_id:
            return False
        conn = self.db.get_conn()
        row = conn.execute(
            "SELECT 1 FROM messages WHERE message_id = ? LIMIT 1", (message_id,)
        ).fetchone()
        return row is not None

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

    def recent_images(
        self,
        group_id: str = "",
        user_id: str = "",
        limit: int = 5,
        max_age_seconds: float = 1800.0,
    ) -> list[dict]:
        """Fetch recent messages that contain image attachments."""
        conn = self.db.get_conn()
        cutoff = time.time() - max_age_seconds
        if group_id:
            rows = conn.execute(
                """SELECT user_name, user_id, imgs_json, timestamp, text FROM messages
                   WHERE group_id = ? AND imgs_json != '[]' AND timestamp >= ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (group_id, cutoff, limit),
            ).fetchall()
        elif user_id:
            rows = conn.execute(
                """SELECT user_name, user_id, imgs_json, timestamp, text FROM messages
                   WHERE group_id = '' AND user_id = ? AND imgs_json != '[]' AND timestamp >= ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (user_id, cutoff, limit),
            ).fetchall()
        else:
            return []

        results = []
        for r in rows:
            try:
                imgs = json.loads(r["imgs_json"]) if r["imgs_json"] else []
                if imgs:
                    results.append({
                        "user_name": r["user_name"],
                        "user_id": r["user_id"],
                        "imgs": imgs,
                        "timestamp": r["timestamp"],
                        "text": r["text"],
                    })
            except Exception:
                pass
        return results

    def search(
        self,
        query: str = "",
        user: str = "",
        group_id: str = "",
        dm_user_id: str = "",
        limit: int = 20,
    ) -> list[dict]:
        """Search messages with optional FTS5 full-text search, user filtering, and group/DM scoping."""
        conn = self.db.get_conn()
        
        query = (query or "").strip()
        user = (user or "").strip()
        
        conditions = []
        params = []
        
        # Privacy & Scoping: Group vs DM
        if group_id:
            conditions.append("m.group_id = ?")
            params.append(group_id)
        elif dm_user_id:
            conditions.append("m.group_id = '' AND m.user_id = ?")
            params.append(dm_user_id)
            
        # User filter (exact user_id, raw user_id without prefix, OR fuzzy user_name match)
        if user:
            if ":" in user:
                prefix, raw_user = user.split(":", 1)
                # Map platform name (e.g., 'qq', 'wechat') or adapter name (e.g., 'onebot', 'telegram')
                prefix_lower = prefix.lower()
                platform_map = {
                    "qq": ["onebot", "cqhttp", "cqhttp_ws", "botpy", "satori_http"],
                    "wechat": ["ntchat"],
                    "telegram": ["telegram"],
                    "console": ["console"],
                }
                matching_frontends = platform_map.get(prefix_lower, [prefix_lower])
                
                conditions.append("(m.user_id = ? OR m.user_id = ? OR m.user_name LIKE ? OR m.user_name LIKE ?)")
                params.extend([user, raw_user, f"%{user}%", f"%{raw_user}%"])
                
                placeholders = ",".join("?" for _ in matching_frontends)
                conditions.append(f"m.frontend IN ({placeholders})")
                params.extend(matching_frontends)
            else:
                conditions.append("(m.user_id = ? OR m.user_name LIKE ?)")
                params.extend([user, f"%{user}%"])
            
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        # Text search (FTS5) if query is provided and not wildcard
        if query and query != "*":
            escaped_query = query.replace('"', '""')
            fts_query = f'"{escaped_query}"'
            
            sql = f"""SELECT m.* FROM messages m
                      JOIN messages_fts f ON m.id = f.rowid
                      WHERE messages_fts MATCH ? AND {where_clause}
                      ORDER BY m.timestamp DESC LIMIT ?"""
            full_params = [fts_query] + params + [limit]
        else:
            sql = f"""SELECT m.* FROM messages m
                      WHERE {where_clause}
                      ORDER BY m.timestamp DESC LIMIT ?"""
            full_params = params + [limit]

        rows = conn.execute(sql, tuple(full_params)).fetchall()
        return [dict(r) for r in rows]

    def get_by_time_range(
        self,
        start_time: float,
        end_time: float | None = None,
        group_id: str = "",
        limit: int = 100,
    ) -> list[dict]:
        """Get messages within a specific time range."""
        conn = self.db.get_conn()
        
        # If end_time is not provided, default to current time
        if end_time is None:
            end_time = time.time()
            
        if group_id:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE group_id = ? AND timestamp >= ? AND timestamp <= ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (group_id, start_time, end_time, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM messages
                   WHERE timestamp >= ? AND timestamp <= ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (start_time, end_time, limit),
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
