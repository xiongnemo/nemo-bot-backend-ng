"""MessageContext — identical interface to the old backend for plugin compat."""

from __future__ import annotations


class MessageContext:
    def __init__(self, context: dict) -> None:
        self.group_id: str = str(context.get("group_id", ""))
        self.user_id: str = str(context.get("user_id", ""))
        self.message_id: str = str(context.get("message_id", ""))
        self.self_id: str = str(context.get("self_id", ""))
        self.ated: bool = bool(context.get("ated", False))
        self.user_name: str = str(context.get("user_name", ""))
        self.frontend_system_info: str = str(context.get("frontend_system_info", ""))

    def __str__(self) -> str:
        gid = self.group_id if self.group_id else "NONE"
        return f"<MessageContext: group_id: {gid}, user_id: {self.user_id}, message_id: {self.message_id}>"
