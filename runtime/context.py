"""Global context to avoid module aliasing issues with __main__ and app."""
from __future__ import annotations
from typing import Any

sender: Any = None
state_store: Any = None
executor: Any = None
agent_runner: Any = None
