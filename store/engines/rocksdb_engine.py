"""
RocksDB Key-Value Storage Engine.
Uses `rocksdict.Rdict` (Rust-backed RocksDB binding) for high-speed LSM-tree persistence.
"""

from __future__ import annotations
import json
import logging
import os
from typing import Any

from rocksdict import Rdict, Options

from .base import BaseKVEngine

logger = logging.getLogger(__name__)


class RocksDBEngine(BaseKVEngine):
    def __init__(self, path: str = "data/nemo_rocksdb"):
        self.path = path
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        opts = Options()
        opts.create_if_missing(True)
        self.db = Rdict(self.path, opts)
        logger.info("RocksDBEngine initialized at path: %s", self.path)

    def _make_key(self, namespace: str, scope: str, key: str) -> str:
        return f"{namespace}:{scope}:{key}"

    def get(self, namespace: str, scope: str, key: str, default: Any = None) -> Any:
        full_key = self._make_key(namespace, scope, key)
        if full_key not in self.db:
            return default
        try:
            val_str = self.db[full_key]
            return json.loads(val_str)
        except Exception:
            return self.db.get(full_key, default)

    def set(self, namespace: str, scope: str, key: str, value: Any) -> None:
        full_key = self._make_key(namespace, scope, key)
        val_str = json.dumps(value, ensure_ascii=False)
        self.db[full_key] = val_str

    def delete(self, namespace: str, scope: str, key: str) -> bool:
        full_key = self._make_key(namespace, scope, key)
        if full_key in self.db:
            del self.db[full_key]
            return True
        return False

    def list_keys(self, namespace: str, scope: str = "global") -> list[str]:
        prefix = f"{namespace}:{scope}:"
        keys = []
        it = self.db.iter()
        it.seek(prefix)
        while it.valid() and str(it.key()).startswith(prefix):
            k_str = str(it.key())
            short_key = k_str[len(prefix):]
            keys.append(short_key)
            it.next()
        return keys

    def list_all(self, namespace: str, scope: str = "global") -> dict[str, Any]:
        prefix = f"{namespace}:{scope}:"
        result = {}
        it = self.db.iter()
        it.seek(prefix)
        while it.valid() and str(it.key()).startswith(prefix):
            k_str = str(it.key())
            short_key = k_str[len(prefix):]
            val_str = it.value()
            try:
                result[short_key] = json.loads(val_str)
            except Exception:
                result[short_key] = val_str
            it.next()
        return result

    def close(self) -> None:
        if hasattr(self, "db") and self.db is not None:
            try:
                self.db.close()
            except Exception:
                pass
            self.db = None

    def destroy(self) -> None:
        self.close()
        try:
            Rdict.destroy(self.path)
        except Exception as e:
            logger.warning("Error destroying RocksDB at %s: %s", self.path, e)
