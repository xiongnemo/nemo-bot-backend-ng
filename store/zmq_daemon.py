"""
ZeroMQ Storage Daemon (CQRS Pattern).

Centralizes all key-value state store reads and writes into a single-threaded daemon
accessed via ZeroMQ IPC/TCP. Prevents database lock contention across multiple
worker processes and provides an in-memory LRU cache layer for hot reads.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import OrderedDict
from typing import Any
import zmq

from .database import Database

logger = logging.getLogger(__name__)


class KVStorageDaemon:
    def __init__(
        self,
        endpoint: str = "inproc://nemo-kv",
        db: Database | None = None,
        max_cache_size: int = 1000,
    ):
        self.endpoint = endpoint
        self.db = db or Database()
        self.max_cache_size = max_cache_size
        self._cache: OrderedDict[tuple[str, str, str], Any] = OrderedDict()
        self._running = False
        self._thread: threading.Thread | None = None
        self._context: zmq.Context | None = None
        self._socket: zmq.Socket | None = None
        self._lock = threading.Lock()

    def start(self, background: bool = True) -> None:
        """Start the storage daemon loop."""
        if self._running:
            return
        self._running = True
        if background:
            self._thread = threading.Thread(target=self._run_loop, name="KVStorageDaemon", daemon=True)
            self._thread.start()
        else:
            self._run_loop()

    def stop(self) -> None:
        """Stop the storage daemon loop and clean up ZMQ resources."""
        if not self._running:
            return
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        logger.info("KVStorageDaemon stopped.")

    def _run_loop(self) -> None:
        logger.info("KVStorageDaemon starting on endpoint: %s", self.endpoint)
        self._context = zmq.Context.instance()
        self._socket = self._context.socket(zmq.REP)
        self._socket.bind(self.endpoint)

        while self._running:
            try:
                if self._socket.poll(200):  # 200 ms timeout to allow checking self._running
                    msg_bytes = self._socket.recv()
                    req = json.loads(msg_bytes.decode("utf-8"))
                    resp = self._handle_request(req)
                    self._socket.send(json.dumps(resp, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                if not self._running:
                    break
                logger.error("Error in KVStorageDaemon request loop: %s", e, exc_info=True)
                try:
                    err_resp = {"status": "error", "message": str(e)}
                    self._socket.send(json.dumps(err_resp, ensure_ascii=False).encode("utf-8"))
                except Exception:
                    pass

        # Cleanup
        try:
            if self._socket:
                self._socket.close(linger=0)
        except Exception as e:
            logger.warning("Error during ZMQ cleanup: %s", e)

    def _handle_request(self, req: dict[str, Any]) -> dict[str, Any]:
        cmd = req.get("cmd")
        if cmd == "PING":
            return {"status": "PONG"}

        ns = req.get("namespace")
        scope = req.get("scope", "global")
        key = req.get("key")

        if cmd == "GET":
            default = req.get("default")
            val = self._get(ns, scope, key, default)
            return {"status": "ok", "value": val}
        elif cmd == "SET":
            val = req.get("value")
            self._set(ns, scope, key, val)
            return {"status": "ok"}
        elif cmd == "DELETE":
            deleted = self._delete(ns, scope, key)
            return {"status": "ok", "deleted": deleted}
        elif cmd == "LIST_KEYS":
            keys = self._list_keys(ns, scope)
            return {"status": "ok", "keys": keys}
        elif cmd == "LIST_ALL":
            data = self._list_all(ns, scope)
            return {"status": "ok", "data": data}
        else:
            return {"status": "error", "message": f"Unknown command: {cmd}"}

    # ------------------------------------------------------------------
    # Internal CRUD with LRU Cache & SQLite Backend
    # ------------------------------------------------------------------

    def _get(self, namespace: str, scope: str, key: str, default: Any = None) -> Any:
        cache_key = (namespace, scope, key)
        with self._lock:
            if cache_key in self._cache:
                self._cache.move_to_end(cache_key)
                return self._cache[cache_key]

        conn = self.db.get_conn()
        row = conn.execute(
            "SELECT value_json FROM kv WHERE namespace=? AND scope=? AND key=?",
            (namespace, scope, key),
        ).fetchone()

        if row is None:
            return default

        val = json.loads(row[0])
        with self._lock:
            self._cache[cache_key] = val
            self._cache.move_to_end(cache_key)
            if len(self._cache) > self.max_cache_size:
                self._cache.popitem(last=False)
        return val

    def _set(self, namespace: str, scope: str, key: str, value: Any) -> None:
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

        cache_key = (namespace, scope, key)
        with self._lock:
            self._cache[cache_key] = value
            self._cache.move_to_end(cache_key)
            if len(self._cache) > self.max_cache_size:
                self._cache.popitem(last=False)

    def _delete(self, namespace: str, scope: str, key: str) -> bool:
        conn = self.db.get_conn()
        cur = conn.execute(
            "DELETE FROM kv WHERE namespace=? AND scope=? AND key=?",
            (namespace, scope, key),
        )
        conn.commit()

        cache_key = (namespace, scope, key)
        with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]

        return cur.rowcount > 0

    def _list_keys(self, namespace: str, scope: str = "global") -> list[str]:
        conn = self.db.get_conn()
        rows = conn.execute(
            "SELECT key FROM kv WHERE namespace=? AND scope=? ORDER BY key",
            (namespace, scope),
        ).fetchall()
        return [r[0] for r in rows]

    def _list_all(self, namespace: str, scope: str = "global") -> dict[str, Any]:
        conn = self.db.get_conn()
        rows = conn.execute(
            "SELECT key, value_json FROM kv WHERE namespace=? AND scope=?",
            (namespace, scope),
        ).fetchall()
        return {r[0]: json.loads(r[1]) for r in rows}
