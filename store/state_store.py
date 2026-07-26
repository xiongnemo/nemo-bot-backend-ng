"""
StateStore — generic key-value store backed by SQLite.

Used for: alias management, plugin runtime config, scheduler cursors,
and any other persistent state that used to live in config.json.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from .database import Database

logger = logging.getLogger(__name__)


class StateStore:
    def __init__(self, db: Database):
        self.db = db

    # ------------------------------------------------------------------
    # Core CRUD
    # ------------------------------------------------------------------

    def get(
        self,
        namespace: str,
        scope: str,
        key: str,
        default: Any = None,
    ) -> Any:
        conn = self.db.get_conn()
        row = conn.execute(
            "SELECT value_json FROM kv WHERE namespace=? AND scope=? AND key=?",
            (namespace, scope, key),
        ).fetchone()
        if row is None:
            return default
        return json.loads(row[0])

    def set(
        self,
        namespace: str,
        scope: str,
        key: str,
        value: Any,
    ) -> None:
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

    def delete(
        self,
        namespace: str,
        scope: str,
        key: str,
    ) -> bool:
        conn = self.db.get_conn()
        cur = conn.execute(
            "DELETE FROM kv WHERE namespace=? AND scope=? AND key=?",
            (namespace, scope, key),
        )
        conn.commit()
        return cur.rowcount > 0

    def list_keys(
        self,
        namespace: str,
        scope: str = "global",
    ) -> list[str]:
        conn = self.db.get_conn()
        rows = conn.execute(
            "SELECT key FROM kv WHERE namespace=? AND scope=? ORDER BY key",
            (namespace, scope),
        ).fetchall()
        return [r[0] for r in rows]

    def list_all(
        self,
        namespace: str,
        scope: str = "global",
    ) -> dict[str, Any]:
        conn = self.db.get_conn()
        rows = conn.execute(
            "SELECT key, value_json FROM kv WHERE namespace=? AND scope=?",
            (namespace, scope),
        ).fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}

    # ------------------------------------------------------------------
    # Convenience: plugin config
    # ------------------------------------------------------------------

    def get_plugin_config(self, plugin_name: str) -> dict:
        """Get the runtime config dict for a plugin (mutable copy)."""
        return self.get("plugin_config", plugin_name, "_all", default={})

    def set_plugin_config(self, plugin_name: str, config: dict) -> None:
        self.set("plugin_config", plugin_name, "_all", config)

    # ------------------------------------------------------------------
    # Convenience: alias
    # ------------------------------------------------------------------

    def get_alias(self, source: str) -> str | None:
        return self.get("alias", "global", source)

    def set_alias(self, source: str, target: str) -> None:
        self.set("alias", "global", source, target)

    def delete_alias(self, source: str) -> bool:
        return self.delete("alias", "global", source)

    def list_aliases(self) -> dict[str, str]:
        return self.list_all("alias", "global")
