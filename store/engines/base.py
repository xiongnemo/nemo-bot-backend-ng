"""
Abstract base class for Key-Value storage engines used by KVStorageDaemon.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any


class BaseKVEngine(ABC):
    @abstractmethod
    def get(self, namespace: str, scope: str, key: str, default: Any = None) -> Any:
        """Retrieve a value from storage, returning `default` if key does not exist."""
        pass

    @abstractmethod
    def set(self, namespace: str, scope: str, key: str, value: Any) -> None:
        """Store or overwrite a value in storage."""
        pass

    @abstractmethod
    def delete(self, namespace: str, scope: str, key: str) -> bool:
        """Delete a key from storage. Returns True if key existed and was deleted."""
        pass

    @abstractmethod
    def list_keys(self, namespace: str, scope: str = "global") -> list[str]:
        """List all keys within a specific namespace and scope."""
        pass

    @abstractmethod
    def list_all(self, namespace: str, scope: str = "global") -> dict[str, Any]:
        """Return all key-value mappings within a specific namespace and scope."""
        pass

    def close(self) -> None:
        """Optional hook for cleaning up database connections/resources on shutdown."""
        pass
