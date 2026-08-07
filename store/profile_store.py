"""
ProfileStore — structured per-user profile (用户画像), isolated by primary_uid.

Stored at ("profile", f"user_{primary_uid}", "data"). Written by the
update_profile builtin tool (realtime) and the daily reflection job (batch).
"""

from __future__ import annotations

import time
from typing import Any

from .state_store import StateStore

STR_FIELDS = {"nickname", "occupation", "birthday"}
LIST_FIELDS = {"hobbies", "personality", "notes"}
ALL_FIELDS = STR_FIELDS | LIST_FIELDS

FIELD_LABELS = {
    "nickname": "称呼偏好",
    "occupation": "职业",
    "birthday": "生日",
    "hobbies": "爱好",
    "personality": "性格特点",
    "notes": "备注",
}

NOTES_LIMIT = 10
LIST_ITEM_LIMIT = 20


class ProfileStore:
    def __init__(self, state_store: StateStore):
        self.state_store = state_store

    def get(self, uid: str) -> dict[str, Any]:
        data = self.state_store.get("profile", f"user_{uid}", "data")
        return data if isinstance(data, dict) else {}

    def _save(self, uid: str, data: dict) -> None:
        data["updated_at"] = time.time()
        self.state_store.set("profile", f"user_{uid}", "data", data)

    def apply(self, uid: str, field: str, action: str, value: str) -> str:
        """Apply one profile mutation. Returns a human-readable result message."""
        if field not in ALL_FIELDS:
            return f"无效字段: {field}（可用: {', '.join(sorted(ALL_FIELDS))}）"
        value = (value or "").strip()
        if not value and action != "remove":
            return "value 不能为空。"

        data = self.get(uid)
        label = FIELD_LABELS[field]

        if field in STR_FIELDS:
            if action == "remove":
                data.pop(field, None)
                self._save(uid, data)
                return f"已清除{label}。"
            data[field] = value
            self._save(uid, data)
            return f"已更新{label}: {value}"

        items: list[str] = list(data.get(field) or [])
        if action == "remove":
            if value not in items:
                return f"{label}中找不到: {value}"
            items.remove(value)
        elif action == "set":
            items = [value]
        else:  # append (default)
            if value in items:
                return f"{label}中已存在: {value}"
            items.append(value)
        limit = NOTES_LIMIT if field == "notes" else LIST_ITEM_LIMIT
        data[field] = items[-limit:]
        self._save(uid, data)
        return f"已更新{label}: {', '.join(data[field]) if data[field] else '（空）'}"

    def render_for_prompt(self, uid: str) -> str:
        """Compact prompt block; empty string when the profile has no content."""
        data = self.get(uid)
        lines: list[str] = []
        for field in ("nickname", "occupation", "birthday"):
            v = data.get(field)
            if v:
                lines.append(f"- {FIELD_LABELS[field]}：{v}")
        for field in ("hobbies", "personality", "notes"):
            items = data.get(field)
            if items:
                lines.append(f"- {FIELD_LABELS[field]}：{'；'.join(items)}")
        return "\n".join(lines)
