"""
Context loader — L2 speaker-weighted history + FTS retrieval + prompt budget.

- load_weighted_history: for group scopes, keep the current speaker's turns
  intact, keep other speakers' most recent turns verbatim, and collapse older
  other-speaker turns into a one-message rule-based recap. DM scopes load as
  before. Turn ownership comes from metadata.user_id (new rows) with a regex
  fallback on the speaker prefix (legacy rows).
- retrieve_related: FTS5 keyword lookup over the raw messages table.
- trim_memory_blocks: priority-based character budget for system prompt blocks.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime

from nemollm import ChatMessage

logger = logging.getLogger(__name__)

SPEAKER_RE = re.compile(r"^\[(.+?) \(ID: ([^)]+)\)")

DEFAULTS = {
    "raw_turns": 60,
    "own_turns": 15,
    "other_turns_verbatim": 5,
    "collapse_max_items": 8,
    "collapse_head_chars": 40,
}


def _to_chat_message(d: dict, current_persona: Any | None = None, switched_at: float = 0.0) -> ChatMessage:
    meta = d.get("metadata") or {}
    tc_data = meta.get("tool_calls")
    tcs = None
    if tc_data:
        from nemollm.types import ToolCall
        tcs = [ToolCall(**tc) for tc in tc_data]

    content = d.get("content") or ""
    role = d.get("role")

    # If this is an assistant message, check if it belongs to a past/different persona
    if role == "assistant" and current_persona and content:
        msg_pid = str(meta.get("persona_id") or "").strip().lower()
        msg_pname = str(meta.get("persona_name") or "").strip()
        created_at = float(d.get("created_at") or 0.0)

        is_other_persona = False
        other_name = ""

        if msg_pid:
            if msg_pid != current_persona.id.lower():
                is_other_persona = True
                other_name = msg_pname or msg_pid
        elif switched_at > 0.0 and created_at and created_at < switched_at:
            is_other_persona = True
            other_name = "前序助理"

        if is_other_persona and other_name:
            if not content.startswith("[") or "此前回复" not in content[:30]:
                content = f"[{other_name} (此前回复)]: {content}"

    return ChatMessage(
        role=role,
        content=content,
        tool_calls=tcs,
        tool_call_id=meta.get("tool_call_id"),
        name=meta.get("name"),
    )


def _turn_owner(user_row: dict) -> tuple[str, str]:
    """Return (uid, display_name) of the user turn; ('', '') if unknown."""
    meta = user_row.get("metadata") or {}
    uid = str(meta.get("user_id") or "")
    content = user_row.get("content") or ""
    m = SPEAKER_RE.match(content)
    name = m.group(1) if m else ""
    if not uid and m:
        uid = m.group(2)
    return uid, name


def _split_turns(history: list[dict]) -> list[list[dict]]:
    """Group rows into turns: each turn starts at a role=user row."""
    turns: list[list[dict]] = []
    current: list[dict] = []
    for row in history:
        if row["role"] == "user":
            if current:
                turns.append(current)
            current = [row]
        else:
            if not current:
                current = [row]  # orphan leading assistant/tool rows form a pseudo-turn
            else:
                current.append(row)
    if current:
        turns.append(current)
    return turns


def load_weighted_history(conv_store, scope_key: str, current_uid: str,
                          is_group: bool, cfg: dict | None = None,
                          state_store: Any | None = None) -> list[ChatMessage]:
    c = dict(DEFAULTS)
    if cfg:
        c.update({k: v for k, v in cfg.items() if k in DEFAULTS})

    current_persona = None
    switched_at = 0.0
    try:
        from runtime import context as rt_context
        if getattr(rt_context, "persona_store", None) is not None:
            current_persona = rt_context.persona_store.get_active_persona(scope_key)
        if state_store is not None:
            switched_at = float(state_store.get("persona", scope_key, "switched_at", default=0.0) or 0.0)
            if not switched_at:
                switched_at = float(state_store.get("persona", "global", "switched_at", default=0.0) or 0.0)
    except Exception:
        pass

    if not is_group:
        history = conv_store.get_history(scope_key, max_turns=30)
        return [_to_chat_message(d, current_persona, switched_at) for d in history]

    history = conv_store.get_history(scope_key, max_turns=int(c["raw_turns"]))
    turns = _split_turns(history)

    own_indices = []
    other_indices = []
    for i, turn in enumerate(turns):
        if turn[0]["role"] != "user":
            own_indices.append(i)  # orphan pseudo-turns: keep with own to preserve flow
            continue
        uid, _ = _turn_owner(turn[0])
        if uid and str(uid) == str(current_uid):
            own_indices.append(i)
        else:
            other_indices.append(i)

    keep = set(own_indices[-int(c["own_turns"]):])
    keep.update(other_indices[-int(c["other_turns_verbatim"]):])

    # Collapse the older other-speaker turns into a rule-based recap
    collapsed_items = []
    head = int(c["collapse_head_chars"])
    for i in other_indices:
        if i in keep:
            continue
        user_row = turns[i][0]
        uid, name = _turn_owner(user_row)
        content = user_row.get("content") or ""
        m = SPEAKER_RE.match(content)
        body = content[m.end():].lstrip(":]").strip() if m else content
        body = body.split("\n")[0][:head]
        if body:
            collapsed_items.append(f"{name or uid or '某人'}: {body}")
    collapsed_items = collapsed_items[-int(c["collapse_max_items"]):]

    messages: list[ChatMessage] = []
    if collapsed_items:
        recap = "[前情提要·其他群友早前的零散发言（已折叠归档，非当前发言用户）]\n" + "\n".join(f"- {it}" for it in collapsed_items)
        messages.append(ChatMessage(role="user", content=recap))
        messages.append(ChatMessage(role="assistant", content="（已了解群内早前前情，清楚上述发言非当前对话者。）"))

    for i, turn in enumerate(turns):
        if i in keep:
            for row in turn:
                messages.append(_to_chat_message(row, current_persona, switched_at))
    return messages


def retrieve_related(msg_store, group_id: str, query: str,
                     top_k: int = 3, exclude_recent_seconds: float = 1800.0) -> list[str]:
    """FTS5 keyword retrieval of related history snippets (best-effort)."""
    q = (query or "").strip()
    if len(q) < 6 or not msg_store:
        return []
    # Sanitize for FTS5 MATCH syntax: strip operators/punctuation, join terms with OR
    terms = re.findall(r"[\w\u4e00-\u9fff]{2,}", q)
    if not terms:
        return []
    match_expr = " OR ".join(f'"{t}"' for t in terms[:6])
    try:
        rows = msg_store.search(match_expr, group_id=group_id, limit=top_k + 10)
    except Exception:
        return []
    cutoff = time.time() - exclude_recent_seconds
    out = []
    for r in rows:
        if r.get("timestamp", 0) > cutoff:
            continue  # recent messages are already visible via ambient/thread layers
        text = (r.get("text") or "").strip()
        if not text:
            continue
        day = datetime.fromtimestamp(r.get("timestamp", 0)).strftime("%m-%d")
        name = r.get("user_name") or r.get("user_id") or "?"
        out.append(f"[{day}] {name}: {text[:80]}")
        if len(out) >= top_k:
            break
    return out


def trim_memory_blocks(blocks: list[tuple[int, str]], budget_chars: int = 6000) -> list[str]:
    """Keep blocks under a total char budget; lower priority number = kept first.

    Original relative order is preserved in the output. When the budget runs
    out mid-block, the block is truncated with an ellipsis if it is high
    priority (<=2), otherwise dropped entirely.
    """
    if budget_chars <= 0:
        return [text for _, text in blocks]
    indexed = sorted(range(len(blocks)), key=lambda i: (blocks[i][0], i))
    kept: dict[int, str] = {}
    remaining = budget_chars
    for i in indexed:
        prio, text = blocks[i]
        if not text:
            continue
        if len(text) <= remaining:
            kept[i] = text
            remaining -= len(text)
        elif prio <= 2 and remaining > 200:
            kept[i] = text[: remaining - 1] + "…"
            remaining = 0
        # else: dropped
    return [kept[i] for i in range(len(blocks)) if i in kept]
