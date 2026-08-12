"""
Plugin-worker KV access — fixes the storage split-brain.

Plugins run in worker processes. When the main process enables the ZMQ
storage daemon (storage.enabled), all canonical writes go through the
daemon (possibly into RocksDB), so a worker that opens SQLite directly
reads a *different*, usually empty store — queries then return fresh
default values forever while main-process writes look fine.

This helper picks the correct store for the current topology:
- storage disabled            -> direct SQLite (canonical)
- storage sqlite backend      -> direct SQLite (same table the daemon writes)
- storage rocksdb + tcp/ipc   -> ZMQ client to the daemon (canonical)
- storage rocksdb + inproc    -> unreachable from workers: return a store
                                 plus a warning so plugins fail loudly
                                 instead of serving wrong numbers

It also never consults runtime.context for delegation (a forked worker may
inherit a broken inproc ZMQ client from the parent).
"""

from __future__ import annotations

import logging

from .database import Database
from .state_store import StateStore

logger = logging.getLogger(__name__)

MISCONFIG_WARNING = (
    "存储配置问题：storage.backend 为 rocksdb 且 endpoint 为 inproc（仅主进程可达），"
    "插件子进程无法读取真实数据。请把 config.yml 的 storage.endpoint 改为 "
    "tcp://127.0.0.1:<端口>（如 tcp://127.0.0.1:5556）后重启。"
)


class WorkerStateStore(StateStore):
    """StateStore that never delegates to runtime.context (worker-safe)."""

    def _get_delegate(self):
        return None


def get_plugin_state_store() -> tuple[object, str | None]:
    """Returns (store, warning). warning != None means reads may be wrong
    and the plugin should surface the message instead of trusting values."""
    from config import backend_config

    db_path = backend_config.get("database", {}).get("path", "data/nemo.sqlite")
    storage = backend_config.get("storage", {}) or {}

    if not storage.get("enabled", False):
        return WorkerStateStore(Database(db_path)), None

    endpoint = str(storage.get("endpoint", "inproc://nemo-kv"))
    backend = str(storage.get("backend", "sqlite"))

    if endpoint.startswith(("tcp://", "ipc://")):
        try:
            from .zmq_client import ZmqStateStore
            client = ZmqStateStore(endpoint)
            if client.ping():
                return client, None
            logger.warning("[plugin_store] daemon at %s not answering ping", endpoint)
        except Exception as e:
            logger.warning("[plugin_store] ZMQ client failed for %s: %s", endpoint, e)
        return WorkerStateStore(Database(db_path)), (
            f"存储守护进程（{endpoint}）无响应，插件读到的数据可能是过期的。"
        )

    # inproc endpoint: unreachable from a worker process
    if backend == "sqlite":
        # daemon writes into the same SQLite kv table; direct reads are fine
        return WorkerStateStore(Database(db_path)), None
    return WorkerStateStore(Database(db_path)), MISCONFIG_WARNING
