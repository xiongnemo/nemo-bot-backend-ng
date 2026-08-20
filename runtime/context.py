"""Global context to avoid module aliasing issues with __main__ and app."""
from __future__ import annotations
from typing import Any

sender: Any = None
state_store: Any = None
executor: Any = None
agent_runner: Any = None
db: Any = None
affinity_store: Any = None
profile_store: Any = None
topic_store: Any = None
user_thread_store: Any = None
group_digest_store: Any = None
msg_store: Any = None
persona_store: Any = None
