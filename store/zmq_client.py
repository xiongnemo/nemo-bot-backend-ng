"""
ZeroMQ StateStore Client.

Provides a thread-safe client implementing the exact public interface of `StateStore`,
communicating with `KVStorageDaemon` over ZeroMQ IPC/TCP. Uses thread-local REQ
sockets with automatic timeout recovery and reconnection.
"""

from __future__ import annotations

import json
import logging
import threading
from typing import Any
import zmq

logger = logging.getLogger(__name__)


class ZmqStateStore:
    def __init__(self, endpoint: str = "inproc://nemo-kv"):
        self.endpoint = endpoint
        self._context = zmq.Context.instance()
        self._local = threading.local()

    def _get_socket(self) -> zmq.Socket:
        if not hasattr(self._local, "socket") or self._local.socket is None:
            sock = self._context.socket(zmq.REQ)
            sock.connect(self.endpoint)
            self._local.socket = sock
        return self._local.socket

    def _reset_socket(self) -> None:
        if hasattr(self._local, "socket") and self._local.socket is not None:
            try:
                self._local.socket.close(linger=0)
            except Exception:
                pass
            self._local.socket = None

    def close(self) -> None:
        """Close the thread-local ZMQ socket."""
        self._reset_socket()

    def __del__(self) -> None:
        self.close()

    def _send_req(self, req: dict[str, Any], timeout_ms: int = 3000) -> dict[str, Any]:
        sock = self._get_socket()
        try:
            sock.send(json.dumps(req, ensure_ascii=False).encode("utf-8"))
            if sock.poll(timeout_ms):
                resp_bytes = sock.recv()
                resp = json.loads(resp_bytes.decode("utf-8"))
                if resp.get("status") == "error":
                    raise RuntimeError(f"ZMQ Storage Daemon Error: {resp.get('message')}")
                return resp
            else:
                self._reset_socket()
                raise TimeoutError(f"ZMQ request timed out after {timeout_ms}ms to endpoint: {self.endpoint}")
        except Exception:
            self._reset_socket()
            raise

    def ping(self) -> bool:
        """Handshake check with the daemon."""
        try:
            resp = self._send_req({"cmd": "PING"}, timeout_ms=1000)
            return resp.get("status") == "PONG"
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Core CRUD Interface (Matching StateStore exactly)
    # ------------------------------------------------------------------

    def get(
        self,
        namespace: str,
        scope: str,
        key: str,
        default: Any = None,
    ) -> Any:
        resp = self._send_req(
            {
                "cmd": "GET",
                "namespace": namespace,
                "scope": scope,
                "key": key,
                "default": default,
            }
        )
        return resp.get("value", default)

    def set(
        self,
        namespace: str,
        scope: str,
        key: str,
        value: Any,
    ) -> None:
        self._send_req(
            {
                "cmd": "SET",
                "namespace": namespace,
                "scope": scope,
                "key": key,
                "value": value,
            }
        )

    def delete(
        self,
        namespace: str,
        scope: str,
        key: str,
    ) -> bool:
        resp = self._send_req(
            {
                "cmd": "DELETE",
                "namespace": namespace,
                "scope": scope,
                "key": key,
            }
        )
        return bool(resp.get("deleted", False))

    def list_keys(
        self,
        namespace: str,
        scope: str = "global",
    ) -> list[str]:
        resp = self._send_req(
            {
                "cmd": "LIST_KEYS",
                "namespace": namespace,
                "scope": scope,
            }
        )
        return resp.get("keys", [])

    def list_all(
        self,
        namespace: str,
        scope: str = "global",
    ) -> dict[str, Any]:
        resp = self._send_req(
            {
                "cmd": "LIST_ALL",
                "namespace": namespace,
                "scope": scope,
            }
        )
        return resp.get("data", {})

    # ------------------------------------------------------------------
    # Convenience Wrappers (Matching StateStore exactly)
    # ------------------------------------------------------------------

    def get_plugin_config(self, plugin_name: str) -> dict:
        return self.get("plugin_config", plugin_name, "_all", default={})

    def set_plugin_config(self, plugin_name: str, config: dict) -> None:
        self.set("plugin_config", plugin_name, "_all", config)

    def get_alias(self, source: str) -> str | None:
        return self.get("alias", "global", source)

    def set_alias(self, source: str, target: str) -> None:
        self.set("alias", "global", source, target)

    def delete_alias(self, source: str) -> bool:
        return self.delete("alias", "global", source)

    def list_aliases(self) -> dict[str, str]:
        return self.list_all("alias", "global")
