"""
UserThreadStore — L3 per-user cross-scene conversation strand (用户线索层).

Hybrid rule + LLM design:
- Write path (every agent turn, synchronous, rule-based): append a structured
  entry with a salience score to a small buffer. Zero LLM cost, never blocks.
- Compression path (background, batched): when the buffer is full enough or
  old enough, a cheap model merges old digest lines + buffer into a fresh
  <=5-line narrative digest with time anchors and scene tags.
- Read path: narrative digest (long-range) + last raw entries (precise recency).

Privacy: entries and digest lines carry a scene tag; DM-derived content is
filtered out when injecting in a group context unless explicitly enabled.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any

from .state_store import StateStore

logger = logging.getLogger(__name__)

DEFAULTS = {
    "enabled": True,
    "buffer_max": 20,
    "trigger_count": 8,
    "trigger_age_hours": 48.0,
    "trigger_age_min_entries": 3,
    "keep_recent_after_compress": 2,
    "max_digest_lines": 5,
    "expose_dm_in_group": False,
    "head_chars": 80,
}

TRIVIAL_RE = re.compile(r"^(哈+|呵+|嗯+|哦+|噢+|在吗|在不在|你好|hi|hello|早安?|晚安|午安|好的?|收到|谢+|\?+|？+|！+|!+|6+|草|绷|寄|typo)$", re.IGNORECASE)

COMPRESS_PROMPT = """你是一个记忆压缩引擎。下面是 bot 与某个用户的「旧记忆摘要」和「新增互动记录」。
请把两者合并成一份不超过 {max_lines} 行的新摘要，要求：
1. 合并同话题的碎片（如多次查机票 → "近期在规划出行，多次查询机票"）
2. 保留时间感（"今天"/"昨天"/"上周"/"8月初"），以提供给你的时间标注为准
3. 显著度高（sal 大）的条目优先保留细节；sal=0 的寒暄可以整体丢弃
4. 严禁在摘要中写入好感度/亲密度的具体分数（这类数值实时变化，写入摘要会变成过期脏数据），只可写"查询过好感度"这类行为描述
5. 每行标注来源场景：该行信息主要来自私聊填 "dm"，来自群聊填 "group"，混合填 "mixed"

严格按如下 JSON 返回，不要任何额外文字或 Markdown 标记：
{{"lines": [{{"text": "摘要内容", "scene": "group"}}]}}
"""


def _parse_lines_json(text: str) -> list[dict] | None:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.DOTALL)
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", t, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    lines = data.get("lines")
    if not isinstance(lines, list):
        return None
    out = []
    for ln in lines:
        if isinstance(ln, dict) and ln.get("text"):
            scene = ln.get("scene") if ln.get("scene") in ("dm", "group", "mixed") else "mixed"
            out.append({"text": str(ln["text"]).strip(), "scene": scene})
    return out


def _time_anchor(ts: float, now: float) -> str:
    delta = now - ts
    if delta < 86400 and datetime.fromtimestamp(ts).date() == datetime.fromtimestamp(now).date():
        return "今天" + datetime.fromtimestamp(ts).strftime("%H:%M")
    if delta < 2 * 86400:
        return "昨天"
    if delta < 7 * 86400:
        return f"{int(delta // 86400)}天前"
    if delta < 30 * 86400:
        return f"{int(delta // (7 * 86400))}周前"
    return datetime.fromtimestamp(ts).strftime("%m月%d日")


class UserThreadStore:
    def __init__(self, state_store: StateStore):
        self.state_store = state_store
        self._lock = threading.Lock()
        self._inflight: set[str] = set()

    def _cfg(self) -> dict:
        cfg = dict(DEFAULTS)
        try:
            from config import get_context_config
            static = get_context_config().get("user_thread", {})
            if isinstance(static, dict):
                cfg.update({k: v for k, v in static.items() if k in DEFAULTS})
        except Exception:
            pass
        return cfg

    # ------------------------------------------------------------------
    # Write path (rules, synchronous)
    # ------------------------------------------------------------------

    @staticmethod
    def _salience(query: str, tools: list[str], events: list[str]) -> int:
        q = (query or "").strip()
        if TRIVIAL_RE.match(q):
            return 0
        sal = 0
        real_tools = [t for t in tools if t not in ("think",)]
        if real_tools:
            sal += 2
        if any(e in ("affinity", "profile") for e in events):
            sal += 2
        if len(q) > 30:
            sal += 1
        return max(sal, 1) if q else sal

    def append_turn(self, uid: str, scene: str, query: str, answer: str,
                    tools: list[str] | None = None, events: list[str] | None = None,
                    now: float | None = None) -> None:
        cfg = self._cfg()
        if not cfg["enabled"]:
            return
        now = now or time.time()
        tools = tools or []
        events = events or []
        head = int(cfg["head_chars"])
        entry = {
            "ts": now,
            "scene": scene,  # "dm" or "group:<gid>"
            "q": (query or "").strip()[:head],
            "a": (answer or "").strip()[:head],
            "tools": [t for t in tools if t != "think"][:5],
            "sal": self._salience(query, tools, events),
        }
        with self._lock:
            buf = self.state_store.get("user_thread", f"user_{uid}", "buffer", default=[])
            buf.append(entry)
            # Evict: zero-salience first, then oldest
            while len(buf) > int(cfg["buffer_max"]):
                idx = next((i for i, e in enumerate(buf[:-2]) if e.get("sal", 0) == 0), 0)
                buf.pop(idx)
            self.state_store.set("user_thread", f"user_{uid}", "buffer", buf)

    # ------------------------------------------------------------------
    # Compression path (LLM, background)
    # ------------------------------------------------------------------

    def should_compress(self, uid: str, now: float | None = None) -> bool:
        cfg = self._cfg()
        if not cfg["enabled"]:
            return False
        now = now or time.time()
        if uid in self._inflight:
            return False
        buf = self.state_store.get("user_thread", f"user_{uid}", "buffer", default=[])
        if len(buf) >= int(cfg["trigger_count"]):
            return True
        if len(buf) >= int(cfg["trigger_age_min_entries"]):
            oldest = min(e.get("ts", now) for e in buf)
            if now - oldest >= float(cfg["trigger_age_hours"]) * 3600:
                return True
        return False

    def compress(self, uid: str, now: float | None = None) -> bool:
        """Merge digest + buffer via cheap LLM. Safe to call in a background thread."""
        cfg = self._cfg()
        now = now or time.time()
        with self._lock:
            if uid in self._inflight:
                return False
            self._inflight.add(uid)
        try:
            buf = self.state_store.get("user_thread", f"user_{uid}", "buffer", default=[])
            if not buf:
                return False
            digest = self.state_store.get("user_thread", f"user_{uid}", "digest", default={})
            old_lines = digest.get("lines", []) if isinstance(digest, dict) else []

            parts = ["【旧记忆摘要】"]
            if old_lines:
                for ln in old_lines:
                    parts.append(f"- [{ln.get('scene', 'mixed')}] {ln.get('text', '')}")
            else:
                parts.append("（无）")
            parts.append("\n【新增互动记录】")
            for e in buf:
                scene = "私聊" if e.get("scene") == "dm" else "群聊"
                tools = f" 使用工具:{','.join(e['tools'])}" if e.get("tools") else ""
                parts.append(
                    f"- {_time_anchor(e.get('ts', now), now)} [{scene}] (sal={e.get('sal', 1)}) "
                    f"用户: {e.get('q', '')} → bot: {e.get('a', '')}{tools}"
                )

            from agent.compress_llm import call_cheap_model
            resp_text = call_cheap_model(
                COMPRESS_PROMPT.format(max_lines=int(cfg["max_digest_lines"])),
                "\n".join(parts),
            )
            if not resp_text:
                return False
            lines = _parse_lines_json(resp_text)
            if lines is None:
                logger.warning("[user_thread] compress parse failed for %s, keeping buffer", uid)
                return False

            lines = lines[: int(cfg["max_digest_lines"])]
            keep = int(cfg["keep_recent_after_compress"])
            with self._lock:
                self.state_store.set("user_thread", f"user_{uid}", "digest",
                                     {"lines": lines, "updated_at": now})
                cur = self.state_store.get("user_thread", f"user_{uid}", "buffer", default=[])
                self.state_store.set("user_thread", f"user_{uid}", "buffer", cur[-keep:] if keep else [])
            return True
        except Exception:
            logger.exception("[user_thread] compress failed for %s", uid)
            return False
        finally:
            self._inflight.discard(uid)

    # ------------------------------------------------------------------
    # Read path (prompt injection)
    # ------------------------------------------------------------------

    def get_context(self, uid: str, in_group: bool, now: float | None = None) -> dict[str, Any]:
        cfg = self._cfg()
        if not cfg["enabled"]:
            return {"digest": [], "recent": []}
        now = now or time.time()
        hide_dm = in_group and not cfg["expose_dm_in_group"]

        digest = self.state_store.get("user_thread", f"user_{uid}", "digest", default={})
        lines = digest.get("lines", []) if isinstance(digest, dict) else []
        digest_out = [ln["text"] for ln in lines
                      if ln.get("text") and not (hide_dm and ln.get("scene") == "dm")]

        buf = self.state_store.get("user_thread", f"user_{uid}", "buffer", default=[])
        recent_out = []
        for e in buf[-3:]:
            if hide_dm and e.get("scene") == "dm":
                continue
            scene = "私聊" if e.get("scene") == "dm" else "群聊"
            recent_out.append(
                f"{_time_anchor(e.get('ts', now), now)}({scene}): {e.get('q', '')} → {e.get('a', '')}"
            )
        return {"digest": digest_out, "recent": recent_out[-2:]}
