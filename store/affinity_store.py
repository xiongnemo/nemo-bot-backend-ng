"""
AffinityStore — per-user affinity (好感度) state with lazy half-life decay.

State lives at ("affinity", f"user_{primary_uid}", "state"). All writes happen
in the main process (ingest hook, builtin tool, reflection job); plugin worker
processes only read, so a process-local lock is enough to serialize writers.
"""

from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Any

from .state_store import StateStore

DEFAULTS: dict[str, float] = {
    "base_score": 10.0,
    "min_score": -20.0,
    "max_score": 100.0,
    "half_life_days": 30.0,
    "gain_engaged": 1.0,
    "gain_passive": 0.2,
    "cooldown_seconds": 60.0,
    "daily_chat_cap": 10.0,
    "llm_single_cap": 5.0,
    "llm_daily_cap": 10.0,
    "reflection_daily_cap": 3.0,
}

# (upper_bound_exclusive, level_name, tone_guideline)
LEVELS: list[tuple[float, str, str]] = [
    (0, "反感", "对该用户态度冷淡、阴阳怪气，惜字如金，不主动搭话。"),
    (10, "陌生", "礼貌但疏离，像对待陌生人一样保持客气的距离感。"),
    (30, "认识", "正常友好，像普通朋友一样自然交流。"),
    (60, "熟悉", "放松随意，可以互相开玩笑、用轻松的语气聊天。"),
    (90, "朋友", "热情主动，会关心对方的近况和心情，乐于多聊几句。"),
    (float("inf"), "亲密", "亲昵撒娇式语气，记挂着对方，像最好的朋友一样毫无保留。"),
]

HISTORY_LIMIT = 50


class AffinityStore:
    def __init__(self, state_store: StateStore):
        self.state_store = state_store
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Config / helpers
    # ------------------------------------------------------------------

    def _cfg(self) -> dict[str, float]:
        cfg = dict(DEFAULTS)
        try:
            from config import get_affinity_config
            static = get_affinity_config()
            if isinstance(static, dict):
                cfg.update({k: float(v) for k, v in static.items() if k in DEFAULTS})
        except Exception:
            pass
        try:
            hot = self.state_store.get_plugin_config("affinity")
            if isinstance(hot, dict):
                cfg.update({k: float(v) for k, v in hot.items() if k in DEFAULTS})
        except Exception:
            pass
        return cfg

    @staticmethod
    def get_level(score: float) -> tuple[str, str]:
        for upper, name, tone in LEVELS:
            if score < upper:
                return name, tone
        return LEVELS[-1][1], LEVELS[-1][2]

    @staticmethod
    def _clamp(score: float, cfg: dict) -> float:
        return max(cfg["min_score"], min(cfg["max_score"], score))

    def _load(self, uid: str, cfg: dict, now: float) -> dict[str, Any]:
        state = self.state_store.get("affinity", f"user_{uid}", "state")
        if not isinstance(state, dict):
            state = {
                "score": cfg["base_score"],
                "last_interaction": None,
                "last_gain_ts": 0.0,
                "daily": {},
                "total_interactions": 0,
                "history": [],
            }
        self._roll_daily(state, now)
        return state

    def _save(self, uid: str, state: dict) -> None:
        self.state_store.set("affinity", f"user_{uid}", "state", state)

    @staticmethod
    def _roll_daily(state: dict, now: float) -> dict:
        today = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        daily = state.get("daily") or {}
        if daily.get("date") != today:
            daily = {"date": today, "chat_gain": 0.0, "llm_delta": 0.0, "reflection_delta": 0.0}
            state["daily"] = daily
        return daily

    @staticmethod
    def _apply_decay(state: dict, now: float, cfg: dict) -> None:
        last = state.get("last_interaction")
        if not last:
            return
        delta_days = max(0.0, (now - last) / 86400.0)
        if delta_days <= 0:
            return
        base = cfg["base_score"]
        state["score"] = base + (state["score"] - base) * (0.5 ** (delta_days / cfg["half_life_days"]))

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_state(self, uid: str, now: float | None = None) -> dict[str, Any]:
        """Read-only view with lazy decay applied. Never persists (safe in worker processes)."""
        now = now or time.time()
        cfg = self._cfg()
        state = self._load(uid, cfg, now)
        self._apply_decay(state, now, cfg)
        state["score"] = self._clamp(state["score"], cfg)
        name, tone = self.get_level(state["score"])
        state["level"] = name
        state["tone"] = tone
        return state

    def record_message(self, uid: str, engaged: bool, now: float | None = None) -> float:
        """Count one interaction; returns the affinity actually gained."""
        now = now or time.time()
        with self._lock:
            cfg = self._cfg()
            state = self._load(uid, cfg, now)
            self._apply_decay(state, now, cfg)
            daily = state["daily"]
            state["total_interactions"] = int(state.get("total_interactions", 0)) + 1
            gained = 0.0
            if now - float(state.get("last_gain_ts", 0)) >= cfg["cooldown_seconds"]:
                gain = cfg["gain_engaged"] if engaged else cfg["gain_passive"]
                room = cfg["daily_chat_cap"] - float(daily.get("chat_gain", 0.0))
                gained = max(0.0, min(gain, room))
                if gained > 0:
                    state["score"] = self._clamp(state["score"] + gained, cfg)
                    daily["chat_gain"] = float(daily.get("chat_gain", 0.0)) + gained
                    state["last_gain_ts"] = now
            state["last_interaction"] = now
            self._save(uid, state)
            return gained

    def adjust(self, uid: str, delta: float, reason: str, source: str, now: float | None = None) -> dict[str, Any]:
        """Bounded adjustment from LLM ("llm") or reflection ("reflection") events."""
        now = now or time.time()
        with self._lock:
            cfg = self._cfg()
            state = self._load(uid, cfg, now)
            self._apply_decay(state, now, cfg)
            daily = state["daily"]

            if source == "llm":
                cap = cfg["llm_single_cap"]
                delta = max(-cap, min(cap, float(delta)))
                budget_key, daily_cap = "llm_delta", cfg["llm_daily_cap"]
            elif source == "reflection":
                budget_key, daily_cap = "reflection_delta", cfg["reflection_daily_cap"]
            else:
                budget_key, daily_cap = None, None

            if budget_key is not None:
                net = float(daily.get(budget_key, 0.0))
                new_net = max(-daily_cap, min(daily_cap, net + float(delta)))
                delta = new_net - net
                daily[budget_key] = new_net

            state["score"] = self._clamp(state["score"] + float(delta), cfg)
            history = state.get("history") or []
            history.append({"ts": now, "delta": round(float(delta), 2), "reason": reason, "source": source})
            state["history"] = history[-HISTORY_LIMIT:]
            state["last_interaction"] = now
            self._save(uid, state)
            name, _ = self.get_level(state["score"])
            return {"score": state["score"], "level": name, "applied_delta": round(float(delta), 2)}
