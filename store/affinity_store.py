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
    # fun: chat-gain critical hit (once per day)
    "crit_chance": 0.05,
    "crit_multiplier": 2.0,
    # good-deed reports (user self-reported positive behavior, LLM-verified)
    "deed_single_cap": 3.0,
    "deed_daily_cap": 3.0,
    "deed_weekly_cap": 10.0,
    "deed_min_credibility": 0.5,
}

DEED_CATEGORIES = ["学习", "工作", "运动", "健康", "生活", "助人", "其他"]

# Weekly challenges: deterministic per (uid, iso-week), lazily evaluated
CHALLENGES: list[dict] = [
    {"id": "chat20", "name": "本周和我互动满 20 次", "metric": "interactions", "target": 20, "reward": 8.0},
    {"id": "active5", "name": "本周有 5 天来找我聊天", "metric": "days_active", "target": 5, "reward": 8.0},
    {"id": "gain25", "name": "本周累计赚取 25 点好感", "metric": "gain", "target": 25, "reward": 8.0},
]

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
TIMELINE_LIMIT = 30
BIRTHDAY_RE = re.compile(r"(\d{1,2})\s*[月/\-.]\s*(\d{1,2})")

# Volatile-stat leak guard: affinity numbers must never enter long-term memory
AFFINITY_STAT_RE = re.compile(r"好感度?|好感分|亲密度|affinity", re.IGNORECASE)


def is_affinity_stat_text(text: str) -> bool:
    """True if the text looks like a stored affinity score (e.g. '好感度69分')."""
    t = str(text or "")
    return bool(AFFINITY_STAT_RE.search(t)) and any(ch.isdigit() for ch in t)


SPARK_CHARS = "▁▂▃▄▅▆▇█"


def render_sparkline(values: list[float], lo: float | None = None, hi: float | None = None) -> str:
    if not values:
        return ""
    lo = min(values) if lo is None else lo
    hi = max(values) if hi is None else hi
    span = (hi - lo) or 1.0
    return "".join(SPARK_CHARS[min(7, int((v - lo) / span * 7.99))] for v in values)


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

    def _load(self, uid: str, now: float, archive: bool = False) -> dict[str, Any]:
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
        self._roll_daily(uid, state, now, archive=archive)
        return state

    def _save(self, uid: str, state: dict) -> None:
        state["peak_score"] = max(float(state.get("peak_score", 0.0)), float(state["score"]))
        if not state.get("indexed"):
            index = self.state_store.get("affinity", "global", "index", default=[])
            if uid not in index:
                index.append(uid)
                self.state_store.set("affinity", "global", "index", index)
            state["indexed"] = True
        self.state_store.set("affinity", f"user_{uid}", STATE_KEY, state)

    @staticmethod
    def _today(now: float) -> str:
        return datetime.fromtimestamp(now).strftime("%Y-%m-%d")

    def _roll_daily(self, uid: str, state: dict, now: float, archive: bool = False) -> dict:
        today = self._today(now)
        daily = state.get("daily") or {}
        if daily.get("date") != today:
            # Archive the finished day into the per-user timeline. Only write
            # paths archive; read paths (get_state, worker processes) stay pure.
            if archive and daily.get("date"):
                timeline = self.state_store.get("affinity", f"user_{uid}", "timeline", default=[])
                timeline.append({
                    "date": daily.get("date"),
                    "end_score": round(float(state.get("score", 0.0)), 1),
                    "chat": round(float(daily.get("chat_gain", 0.0)), 1),
                    "event": round(float(daily.get("event_gain", 0.0)), 1),
                    "llm": round(float(daily.get("llm_delta", 0.0)), 1),
                    "refl": round(float(daily.get("reflection_delta", 0.0)), 1),
                })
                self.state_store.set("affinity", f"user_{uid}", "timeline", timeline[-TIMELINE_LIMIT:])
            daily = {"date": today, "chat_gain": 0.0, "event_gain": 0.0, "deed_gain": 0.0,
                     "llm_delta": 0.0, "reflection_delta": 0.0, "events": []}
            state["daily"] = daily
        return daily

    @staticmethod
    def _week(now: float) -> str:
        return datetime.fromtimestamp(now).strftime("%G-W%V")

    def _roll_weekly(self, uid: str, state: dict, now: float) -> dict:
        week = self._week(now)
        weekly = state.get("weekly") or {}
        if weekly.get("week") != week:
            import hashlib
            idx = int(hashlib.md5(f"{uid}:{week}".encode()).hexdigest(), 16) % len(CHALLENGES)
            weekly = {"week": week, "interactions": 0, "days_active": 0, "gain": 0.0,
                      "deed_gain": 0.0, "last_active_date": "",
                      "challenge": dict(CHALLENGES[idx]), "done": False}
            state["weekly"] = weekly
        return weekly

    def _check_challenge(self, state: dict, cfg: dict) -> float:
        weekly = state.get("weekly") or {}
        ch = weekly.get("challenge")
        if not ch or weekly.get("done"):
            return 0.0
        value = weekly.get(ch["metric"], 0)
        if value >= ch["target"]:
            weekly["done"] = True
            return self._grant_event(state, cfg, f"challenge:{weekly['week']}",
                                     float(ch["reward"]), f"周挑战达成：{ch['name']} 🏅")
        return 0.0

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
        if key.split(":")[0] in ("milestone", "birthday", "profile_share", "challenge", "gift_from", "gift_sent"):
            history = state.get("history") or []
            history.append({"ts": time.time(), "delta": round(applied, 2), "reason": note, "source": "event"})
            state["history"] = history[-HISTORY_LIMIT:]
        if once == "ever":
            state["granted"].append(key)
        return applied

    def _check_level_up(self, state: dict, old_score: float, now: float) -> None:
        """Record a celebration event when the score crosses into a higher level."""
        old_name, _, old_lv = self.get_level(old_score)
        new_name, _, new_lv = self.get_level(float(state["score"]))
        if new_lv > old_lv:
            state["daily"]["events"].append(
                {"k": f"levelup:{new_name}", "pts": 0, "note": f"关系升级：{old_name} → {new_name} 🎉"})
            history = state.get("history") or []
            history.append({"ts": now, "delta": 0, "reason": f"关系升级为「{new_name}」🎉", "source": "event"})
            state["history"] = history[-HISTORY_LIMIT:]

    def grant_profile_share(self, uid: str, field: str, now: float | None = None) -> float:
        """Reward sharing personal info; granted once per field, ever."""
        now = now or time.time()
        with self._lock:
            cfg = self._cfg()
            state = self._load(uid, now, archive=True)
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
            state = self._load(uid, now, archive=True)
            self._apply_decay(state, now, cfg)
            daily = state["daily"]
            state["total_interactions"] = int(state.get("total_interactions", 0)) + 1
            gained = 0.0
            score_before = float(state["score"])

            weekly = self._roll_weekly(uid, state, now)
            weekly["interactions"] = int(weekly.get("interactions", 0)) + 1
            today = self._today(now)
            if weekly.get("last_active_date") != today:
                weekly["days_active"] = int(weekly.get("days_active", 0)) + 1
                weekly["last_active_date"] = today

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
                    # fun: critical hit — chat gain doubled, at most once a day
                    import random
                    if random.random() < cfg["crit_chance"]:
                        extra = chat_gained * (cfg["crit_multiplier"] - 1.0)
                        gained += self._grant_event(state, cfg, "crit", extra, "⚡手气暴击！本次聊天加分翻倍")

            weekly["gain"] = round(float(weekly.get("gain", 0.0)) + gained, 2)
            gained += self._check_challenge(state, cfg)
            self._check_level_up(state, score_before, now)
            state["last_interaction"] = now
            self._save(uid, state)
            return round(gained, 2)

    def adjust(self, uid: str, delta: float, reason: str, source: str,
               now: float | None = None) -> dict[str, Any]:
        """Bounded adjustment from LLM ("llm") or reflection ("reflection")."""
        now = now or time.time()
        with self._lock:
            cfg = self._cfg()
            state = self._load(uid, now, archive=True)
            self._apply_decay(state, now, cfg)
            daily = state["daily"]
            score_before = float(state["score"])

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
            self._check_level_up(state, score_before, now)
            state["last_interaction"] = now
            self._save(uid, state)
            name, _, _ = self.get_level(state["score"])
            return {"score": state["score"], "level": name, "applied_delta": round(float(delta), 2)}

    def set_score(self, uid: str, score: float, reason: str = "管理员设定",
                  operator: str = "", now: float | None = None) -> dict[str, Any]:
        """Admin: pin the score to an exact value (bypasses caps, audited in history)."""
        now = now or time.time()
        with self._lock:
            cfg = self._cfg()
            state = self._load(uid, now, archive=True)
            old = float(state.get("score", 0.0))
            state["score"] = self._clamp(float(score), cfg)
            state["peak_score"] = max(float(state.get("peak_score", 0.0)), state["score"])
            history = state.get("history") or []
            history.append({"ts": now, "delta": round(state["score"] - old, 2),
                            "reason": f"{reason}（操作者:{operator}）" if operator else reason,
                            "source": "admin"})
            state["history"] = history[-HISTORY_LIMIT:]
            state["last_interaction"] = now
            self._save(uid, state)
            name, _, _ = self.get_level(state["score"])
            return {"score": state["score"], "level": name, "old_score": round(old, 1)}

    def reset(self, uid: str) -> bool:
        """Admin: wipe a user's affinity state entirely (restarts from zero)."""
        with self._lock:
            self.state_store.delete("affinity", f"user_{uid}", "timeline")
            return self.state_store.delete("affinity", f"user_{uid}", STATE_KEY)

    def report_deed(self, uid: str, category: str, summary: str,
                    suggested_points: float, credibility: float,
                    now: float | None = None) -> dict[str, Any]:
        """User-reported positive behavior (studied/worked N hours etc.),
        pre-verified by the LLM. Hard rule caps make prompt-tricking the
        model insufficient to farm points:
        - credibility gate (below threshold -> rejected)
        - reward = clamp(points, 1..single_cap) * credibility
        - one report per category per day; daily and weekly channel caps
        """
        now = now or time.time()
        category = category if category in DEED_CATEGORIES else "其他"
        summary = (summary or "").strip()[:60]
        with self._lock:
            cfg = self._cfg()
            state = self._load(uid, now, archive=True)
            self._apply_decay(state, now, cfg)
            daily = state["daily"]
            weekly = self._roll_weekly(uid, state, now)

            cred = max(0.0, min(1.0, float(credibility)))
            if cred < cfg["deed_min_credibility"]:
                return {"ok": False, "reason": "可信度不足：请先和用户聊聊细节（做了什么/多久/有什么收获），确认真实后再奖励。"}
            if any(e.get("k") == f"deed:{category}" for e in daily["events"]):
                return {"ok": False, "reason": f"今天已经奖励过「{category}」类的汇报了，同类事项每天只认一次。"}

            base = max(1.0, min(float(suggested_points), cfg["deed_single_cap"]))
            points = round(base * cred, 1)
            day_room = cfg["deed_daily_cap"] - float(daily.get("deed_gain", 0.0))
            week_room = cfg["deed_weekly_cap"] - float(weekly.get("deed_gain", 0.0))
            points = round(max(0.0, min(points, day_room, week_room)), 1)
            if points <= 0:
                return {"ok": False, "reason": "今日/本周的自律奖励额度已用完，明天再来吧（额度防刷，不针对你）。"}

            score_before = float(state["score"])
            state["score"] = self._clamp(state["score"] + points, cfg)
            daily["deed_gain"] = round(float(daily.get("deed_gain", 0.0)) + points, 1)
            weekly["deed_gain"] = round(float(weekly.get("deed_gain", 0.0)) + points, 1)
            note = f"自律打卡[{category}]：{summary} ✨"
            daily["events"].append({"k": f"deed:{category}", "pts": points, "note": note})
            history = state.get("history") or []
            history.append({"ts": now, "delta": points, "reason": note, "source": "deed"})
            state["history"] = history[-HISTORY_LIMIT:]
            self._check_level_up(state, score_before, now)
            state["last_interaction"] = now
            self._save(uid, state)
            name, _, _ = self.get_level(state["score"])
            return {"ok": True, "points": points, "score": round(state["score"], 1), "level": name,
                    "day_remaining": round(cfg["deed_daily_cap"] - daily["deed_gain"], 1),
                    "week_remaining": round(cfg["deed_weekly_cap"] - weekly["deed_gain"], 1)}

    def gift(self, giver_uid: str, target_uid: str, now: float | None = None) -> dict[str, Any]:
        """User-to-user gift: recipient +2, giver +1 (warmth is mutual).
        Anti-abuse: giver once per day; requires giver level >= 熟悉(21)."""
        now = now or time.time()
        giver_uid, target_uid = str(giver_uid), str(target_uid)
        if giver_uid == target_uid:
            return {"ok": False, "reason": "不能给自己送礼。"}
        with self._lock:
            cfg = self._cfg()
            giver = self._load(giver_uid, now, archive=True)
            self._apply_decay(giver, now, cfg)
            if giver["score"] < 21:
                return {"ok": False, "reason": "赠礼需要你和 Nemo 的关系达到「熟悉」(21分) 以上。"}
            if any(e.get("k") == "gift_sent" for e in giver["daily"]["events"]):
                return {"ok": False, "reason": "今天已经送过礼了，明天再来吧。"}

            target = self._load(target_uid, now, archive=True)
            self._apply_decay(target, now, cfg)
            t_before = float(target["score"])
            received = self._grant_event(target, cfg, f"gift_from:{giver_uid}", 2.0,
                                         f"收到来自 {giver_uid} 的好感度赠礼 🎁")
            if received <= 0:
                return {"ok": False, "reason": "对方今天已经收过你的礼物了（或对方今日事件加分已满）。"}
            g_before = float(giver["score"])
            self._grant_event(giver, cfg, "gift_sent", 1.0, f"向 {target_uid} 赠出好感度 🎁（暖心 +1）")
            self._check_level_up(target, t_before, now)
            self._check_level_up(giver, g_before, now)
            giver["last_interaction"] = now
            self._save(giver_uid, giver)
            self._save(target_uid, target)
            return {"ok": True, "giver_score": round(giver["score"], 1),
                    "target_score": round(target["score"], 1), "received": received}

    def leaderboard(self, top_n: int = 10, now: float | None = None) -> list[dict]:
        """Global top-N by current (decayed) score. Reads only."""
        now = now or time.time()
        index = self.state_store.get("affinity", "global", "index", default=[])
        rows = []
        for uid in index[:500]:
            st = self.get_state(uid, now=now)
            rows.append({"uid": uid, "score": round(st["score"], 1), "level": st["level"],
                         "lv": st["lv"], "streak": (st.get("streak") or {}).get("days", 0)})
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows[:max(1, min(int(top_n), 20))]

    @staticmethod
    def get_titles(state: dict) -> list[str]:
        """Rule-derived honor titles (computed, never stored)."""
        titles = []
        streak = (state.get("streak") or {}).get("days", 0)
        if streak >= 30:
            titles.append("连更30天·风雨无阻")
        elif streak >= 7:
            titles.append("七日之约 🔥")
        total = int(state.get("total_interactions", 0))
        if total >= 5000:
            titles.append("万语千言")
        elif total >= 1000:
            titles.append("千言万语")
        if float(state.get("peak_score", 0.0)) >= 81:
            titles.append("挚友认证 💎")
        granted = state.get("granted") or []
        if sum(1 for g in granted if str(g).startswith("profile_share:")) >= 3:
            titles.append("坦诚相待")
        daily = state.get("daily") or {}
        if any(e.get("k") == "crit" for e in daily.get("events", [])):
            titles.append("今日欧皇 ⚡")
        if (state.get("weekly") or {}).get("done"):
            titles.append("本周挑战达人 🏅")
        return titles

    def get_timeline(self, uid: str, days: int = 7) -> list[dict]:
        """Daily rollups (oldest→newest), up to TIMELINE_LIMIT days back."""
        timeline = self.state_store.get("affinity", f"user_{uid}", "timeline", default=[])
        days = max(1, min(int(days), TIMELINE_LIMIT))
        return timeline[-days:]

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
        self._roll_weekly(uid, state, now)  # in-memory view only; read path never persists
        state["titles"] = self.get_titles(state)
        daily = state.get("daily", {})
        state["today_total"] = round(
            float(daily.get("chat_gain", 0.0)) + float(daily.get("event_gain", 0.0))
            + float(daily.get("deed_gain", 0.0))
            + float(daily.get("llm_delta", 0.0)) + float(daily.get("reflection_delta", 0.0)), 1)
        return state
