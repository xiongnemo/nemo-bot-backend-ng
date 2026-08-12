"""
GroupDigestStore — L1 group ambient rolling digest (群体氛围层).

Design: the messages table (message_store) is already the buffer, so this
store keeps only an in-memory per-group counter. When enough messages have
accumulated (or the window is old enough), a cheap model compresses the
increment into a one-line digest; the rolling digest keeps the last few
lines and is injected into the system prompt as ambient group context.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime

from .database import Database
from .state_store import StateStore

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled": True,
    "trigger_count": 80,
    "min_count": 10,
    "max_age_seconds": 900.0,
    "max_lines": 5,
    "fetch_limit": 200,
    "msg_head_chars": 60,
}

DIGEST_PROMPT = """你是一个群聊观察员。下面是一段 QQ 群的聊天记录。
请用一句话（不超过 60 字）概括这段时间群里主要在聊什么、发生了什么值得注意的事。
直接输出这一句话，不要任何前缀、引号或 Markdown。如果全是无意义的灌水，输出：日常闲聊灌水。
"""


class GroupDigestStore:
    def __init__(self, state_store: StateStore, db: Database):
        self.state_store = state_store
        self.db = db
        self._lock = threading.Lock()
        self._counters: dict[str, int] = {}
        self._inflight: set[str] = set()

    def _cfg(self) -> dict:
        cfg = dict(DEFAULTS)
        try:
            from config import get_context_config
            static = get_context_config().get("group_digest", {})
            if isinstance(static, dict):
                cfg.update({k: v for k, v in static.items() if k in DEFAULTS})
        except Exception:
            pass
        return cfg

    @staticmethod
    def _scope(gid: str) -> str:
        return f"group_{gid}"

    def record(self, gid: str, now: float | None = None) -> bool:
        """Count one group message; returns True when a compression should be scheduled."""
        cfg = self._cfg()
        if not cfg["enabled"] or not gid:
            return False
        now = now or time.time()
        with self._lock:
            count = self._counters.get(gid, 0) + 1
            self._counters[gid] = count
            if gid in self._inflight:
                return False
        if count >= int(cfg["trigger_count"]):
            return True
        if count >= int(cfg["min_count"]):
            state = self.state_store.get("group_digest", self._scope(gid), "state", default={})
            last_ts = state.get("last_ts", 0)
            if not last_ts:
                # First run: anchor to now so age is measured from service start
                state["last_ts"] = now
                self.state_store.set("group_digest", self._scope(gid), "state", state)
                return False
            if now - last_ts >= float(cfg["max_age_seconds"]):
                return True
        return False

    def compress(self, gid: str, now: float | None = None) -> bool:
        """Summarize messages since last digest. Safe to call in a background thread."""
        cfg = self._cfg()
        now = now or time.time()
        with self._lock:
            if gid in self._inflight:
                return False
            self._inflight.add(gid)
        try:
            state = self.state_store.get("group_digest", self._scope(gid), "state", default={})
            last_ts = state.get("last_ts") or (now - float(cfg["max_age_seconds"]))

            conn = self.db.get_conn()
            rows = conn.execute(
                """SELECT user_name, user_id, text, timestamp FROM messages
                   WHERE group_id = ? AND timestamp > ? AND timestamp <= ?
                   ORDER BY timestamp ASC LIMIT ?""",
                (gid, last_ts, now, int(cfg["fetch_limit"])),
            ).fetchall()

            head = int(cfg["msg_head_chars"])
            log_lines = []
            for r in rows:
                text = (r["text"] or "").strip()
                if not text:
                    continue
                name = r["user_name"] or r["user_id"] or "?"
                hm = datetime.fromtimestamp(r["timestamp"]).strftime("%H:%M")
                log_lines.append(f"{hm} {name}: {text[:head]}")

            if len(log_lines) < int(cfg["min_count"]):
                # Not enough substance; advance the window anyway to avoid re-fetching
                state["last_ts"] = now
                self.state_store.set("group_digest", self._scope(gid), "state", state)
                return False

            from agent.compress_llm import call_cheap_model
            summary = call_cheap_model(DIGEST_PROMPT, "\n".join(log_lines))
            if not summary:
                return False
            summary = summary.strip().splitlines()[0][:80]

            start_hm = datetime.fromtimestamp(rows[0]["timestamp"]).strftime("%H:%M")
            end_hm = datetime.fromtimestamp(rows[-1]["timestamp"]).strftime("%H:%M")
            day = datetime.fromtimestamp(rows[-1]["timestamp"]).strftime("%m-%d")
            line = f"[{day} {start_hm}~{end_hm}] {summary}"

            lines = state.get("lines", [])
            lines.append(line)
            state["lines"] = lines[-int(cfg["max_lines"]):]
            state["last_ts"] = now
            state["updated_at"] = now
            self.state_store.set("group_digest", self._scope(gid), "state", state)
            with self._lock:
                self._counters[gid] = 0
            return True
        except Exception:
            logger.exception("[group_digest] compress failed for group %s", gid)
            return False
        finally:
            self._inflight.discard(gid)

    def get_lines(self, gid: str, max_age_hours: float = 24.0) -> list[str]:
        """Digest lines for prompt injection; stale digests (idle group) are omitted."""
        state = self.state_store.get("group_digest", self._scope(gid), "state", default={})
        if not state.get("lines"):
            return []
        if time.time() - state.get("updated_at", 0) > max_age_hours * 3600:
            return []
        return list(state["lines"])
