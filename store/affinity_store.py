"""
AffinityStore v2 — event-driven per-user affinity (好感度) with a clear
behavior→feedback mapping.

v2 design goals:
- Every gain is an *event* recorded in a daily ledger, so users can see
  exactly what earned points today (今日明细).
- Habit loop: daily-first bonus + consecutive-day streak bonus.
- Spike moments: interaction milestones, birthday surprise, sharing
  personal info (wired from update_profile).
- Gentle decay: 3-day grace period (冷淡不惩罚), then half-life regression
  toward 0, with milestone floors so old friends never fully reset.
- Fresh start: state lives under the "state_v2" key; v1 data is ignored,
  which re-initializes everyone from zero as requested.

All writes happen in the main process (ingest hook, builtin tools,
reflection job); plugin workers only read.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import datetime
from typing import Any

from .state_store import StateStore

STATE_KEY = "state_v2"

DEFAULTS: dict[str, float] = {
    # bounds & decay
    "min_score": -20.0,
    "max_score": 100.0,
    "decay_grace_days": 3.0,
    "half_life_days": 45.0,
    # chat gains (habit: high-frequency, low-weight)
    "gain_engaged": 1.0,
    "gain_passive": 0.2,
    "cooldown_seconds": 60.0,
    "daily_chat_cap": 10.0,
    # event gains (spike: low-frequency, high-weight)
    "daily_first_bonus": 2.0,
    "streak_step": 0.5,          # streak bonus = streak_step * min(streak-1, streak_max_steps)
    "streak_max_steps": 6.0,     # caps streak bonus at +3
    "profile_share_bonus": 5.0,
    "birthday_bonus": 10.0,
    "daily_event_cap": 20.0,
    # llm / reflection channels
    "llm_single_cap": 5.0,
    "llm_daily_cap": 10.0,
    "reflection_daily_cap": 3.0,
}

MILESTONES: list[tuple[int, float, str]] = [
    (100, 5.0, "累计互动 100 次"),
    (500, 10.0, "累计互动 500 次"),
    (1000, 15.0, "累计互动 1000 次"),
    (5000, 25.0, "累计互动 5000 次"),
]

# (upper_bound_exclusive, name, Lv, tone)
LEVELS: list[tuple[float, str, int, str]] = [
    (0, "反感", 0, "对该用户态度冷淡、阴阳怪气，惜字如金，不主动搭话。"),
    (21, "陌生", 1, "礼貌客气，保持适当距离，像对待刚认识的人。"),
    (51, "熟悉", 2, "自然友好，可以偶尔开开玩笑，正在慢慢熟络。"),
    (81, "朋友", 3, "放松热情，主动关心对方的近况，聊天像老朋友。"),
    (float("inf"), "挚友", 4, "亲昵无间，记挂着对方，撒娇吐槽都可以，是最好的朋友。"),
]

# decay floors unlocked by peak score: 曾达到挚友(81)→衰减下限51；曾达到朋友(51)→下限21
PEAK_FLOORS: list[tuple[float, float]] = [(81.0, 51.0), (51.0, 21.0)]

HISTORY_LIMIT = 50
BIRTHDAY_RE = re.compile(r"(\d{1,2})\s*[月/\-.]\s*(\d{1,2})")


class AffinityStore:
    def __init__(self, state_store: StateStore, profile_store=None):
        self.state_store = state_store
        self.profile_store = profile_store  # optional, enables birthday surprise
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Config / level helpers
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
    def get_level(score: float) -> tuple[str, str, int]:
        """Returns (name, tone, lv)."""
        for upper, name, lv, tone in LEVELS:
            if score < upper:
                return name, tone, lv
        last = LEVELS[-1]
        return last[1], last[3], last[2]

    @staticmethod
    def next_level_info(score: float) -> tuple[str, float] | None:
        """Returns (next_level_name, points_needed), or None at max level."""
        for i, (upper, _, _, _) in enumerate(LEVELS):
            if score < upper:
                if i + 1 < len(LEVELS):
                    return LEVELS[i + 1][1], round(upper - score, 1)
                return None
        return None

    @staticmethod
    def _clamp(score: float, cfg: dict) -> float:
        return max(cfg["min_score"], min(cfg["max_score"], score))

    # ------------------------------------------------------------------
    # State load / save
    # ------------------------------------------------------------------

    def _load(self, uid: str, now: float) -> dict[str, Any]:
        state = self.state_store.get("affinity", f"user_{uid}", STATE_KEY)
        if not isinstance(state, dict):
            state = {
                "score": 0.0,
                "created_at": now,
                "last_interaction": None,
                "last_gain_ts": 0.0,
                "peak_score": 0.0,
                "streak": {"days": 0, "last_date": ""},
                "daily": {},
                "granted": [],
                "total_interactions": 0,
                "history": [],
            }
        self._roll_daily(state, now)
        return state

    def _save(self, uid: str, state: dict) -> None:
        state["peak_score"] = max(float(state.get("peak_score", 0.0)), float(state["score"]))
        self.state_store.set("affinity", f"user_{uid}", STATE_KEY, state)

    @staticmethod
    def _today(now: float) -> str:
        return datetime.fromtimestamp(now).strftime("%Y-%m-%d")

    def _roll_daily(self, state: dict, now: float) -> dict:
        today = self._today(now)
        daily = state.get("daily") or {}
        if daily.get("date") != today:
            daily = {"date": today, "chat_gain": 0.0, "event_gain": 0.0,
                     "llm_delta": 0.0, "reflection_delta": 0.0, "events": []}
            state["daily"] = daily
        return daily

    def _decay_floor(self, state: dict, cfg: dict) -> float:
        peak = float(state.get("peak_score", 0.0))
        for need, floor in PEAK_FLOORS:
            if peak >= need:
                return floor
        return cfg["min_score"]

    def _apply_decay(self, state: dict, now: float, cfg: dict) -> None:
        last = state.get("last_interaction")
        if not last:
            return
        idle_days = max(0.0, (now - last) / 86400.0)
        if idle_days <= cfg["decay_grace_days"]:
            return  # grace period: 日常冷淡不惩罚
        effective = idle_days - cfg["decay_grace_days"]
        decayed = state["score"] * (0.5 ** (effective / cfg["half_life_days"]))
        floor = self._decay_floor(state, cfg)
        if state["score"] > floor:
            state["score"] = max(decayed, floor)  # milestone floor protects old friends
        # scores already at/below the floor are not touched by decay

    # ------------------------------------------------------------------
    # Event ledger
    # ------------------------------------------------------------------

    def _grant_event(self, state: dict, cfg: dict, key: str, points: float,
                     note: str, once: str = "day") -> float:
        """Grant an event gain under the daily event cap. Returns applied points."""
        daily = state["daily"]
        if once == "day" and any(e.get("k") == key for e in daily["events"]):
            return 0.0
        if once == "ever" and key in state.setdefault("granted", []):
            return 0.0
        room = cfg["daily_event_cap"] - float(daily.get("event_gain", 0.0))
        applied = max(0.0, min(points, room))
        if applied <= 0:
            return 0.0
        state["score"] = self._clamp(state["score"] + applied, cfg)
        daily["event_gain"] = float(daily.get("event_gain", 0.0)) + applied
        daily["events"].append({"k": key, "pts": round(applied, 1), "note": note})
        if once == "ever":
            state["granted"].append(key)
        return applied

    def grant_profile_share(self, uid: str, field: str, now: float | None = None) -> float:
        """Reward sharing personal info; granted once per field, ever."""
        now = now or time.time()
        with self._lock:
            cfg = self._cfg()
            state = self._load(uid, now)
            self._apply_decay(state, now, cfg)
            applied = self._grant_event(state, cfg, f"profile_share:{field}",
                                        cfg["profile_share_bonus"],
                                        f"分享了个人信息({field})", once="ever")
            if applied:
                state["last_interaction"] = now
            self._save(uid, state)
            return applied

    def _birthday_today(self, uid: str, now: float) -> bool:
        if self.profile_store is None:
            return False
        try:
            birthday = (self.profile_store.get(uid) or {}).get("birthday") or ""
            m = BIRTHDAY_RE.search(str(birthday))
            if not m:
                return False
            d = datetime.fromtimestamp(now)
            return int(m.group(1)) == d.month and int(m.group(2)) == d.day
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_message(self, uid: str, engaged: bool, now: float | None = None) -> float:
        """Count one interaction: chat gain + daily-first + streak + milestone
        + birthday events. Returns total points gained by this call."""
        now = now or time.time()
        with self._lock:
            cfg = self._cfg()
            state = self._load(uid, now)
            self._apply_decay(state, now, cfg)
            daily = state["daily"]
            state["total_interactions"] = int(state.get("total_interactions", 0)) + 1
            gained = 0.0

            # habit loop: daily first + streak (+ birthday surprise)
            streak = state.setdefault("streak", {"days": 0, "last_date": ""})
            today = self._today(now)
            if streak.get("last_date") != today:
                yesterday = self._today(now - 86400)
                streak["days"] = streak.get("days", 0) + 1 if streak.get("last_date") == yesterday else 1
                streak["last_date"] = today
                gained += self._grant_event(state, cfg, "daily_first",
                                            cfg["daily_first_bonus"], "每日初见")
                steps = min(max(streak["days"] - 1, 0), int(cfg["streak_max_steps"]))
                if steps > 0:
                    gained += self._grant_event(state, cfg, "streak",
                                                cfg["streak_step"] * steps,
                                                f"连续互动 {streak['days']} 天 🔥")
                if self._birthday_today(uid, now):
                    gained += self._grant_event(state, cfg, "birthday",
                                                cfg["birthday_bonus"], "生日快乐！🎂")

            # spike: interaction milestones (once ever)
            total = state["total_interactions"]
            for need, pts, note in MILESTONES:
                if total >= need:
                    gained += self._grant_event(state, cfg, f"milestone:{need}", pts,
                                                f"里程碑达成：{note} 🏆", once="ever")

            # plain chat gain (cooldown + daily cap)
            if now - float(state.get("last_gain_ts", 0)) >= cfg["cooldown_seconds"]:
                gain = cfg["gain_engaged"] if engaged else cfg["gain_passive"]
                room = cfg["daily_chat_cap"] - float(daily.get("chat_gain", 0.0))
                chat_gained = max(0.0, min(gain, room))
                if chat_gained > 0:
                    state["score"] = self._clamp(state["score"] + chat_gained, cfg)
                    daily["chat_gain"] = float(daily.get("chat_gain", 0.0)) + chat_gained
                    state["last_gain_ts"] = now
                    gained += chat_gained

            state["last_interaction"] = now
            self._save(uid, state)
            return round(gained, 2)

    def adjust(self, uid: str, delta: float, reason: str, source: str,
               now: float | None = None) -> dict[str, Any]:
        """Bounded adjustment from LLM ("llm") or reflection ("reflection")."""
        now = now or time.time()
        with self._lock:
            cfg = self._cfg()
            state = self._load(uid, now)
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
            name, _, _ = self.get_level(state["score"])
            return {"score": state["score"], "level": name, "applied_delta": round(float(delta), 2)}

    def get_state(self, uid: str, now: float | None = None) -> dict[str, Any]:
        """Read-only view with lazy decay applied. Never persists (worker-safe)."""
        now = now or time.time()
        cfg = self._cfg()
        state = self._load(uid, now)
        self._apply_decay(state, now, cfg)
        state["score"] = self._clamp(state["score"], cfg)
        name, tone, lv = self.get_level(state["score"])
        state["level"] = name
        state["tone"] = tone
        state["lv"] = lv
        nxt = self.next_level_info(state["score"])
        if nxt:
            state["next_level"] = {"name": nxt[0], "need": nxt[1]}
        daily = state.get("daily", {})
        state["today_total"] = round(
            float(daily.get("chat_gain", 0.0)) + float(daily.get("event_gain", 0.0))
            + float(daily.get("llm_delta", 0.0)) + float(daily.get("reflection_delta", 0.0)), 1)
        return state
