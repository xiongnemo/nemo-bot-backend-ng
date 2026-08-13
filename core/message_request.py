"""MessageRequest — identical interface to the old backend for plugin compat."""

from __future__ import annotations

from typing import Union


class MessageRequest:
    def __init__(self, request: dict) -> None:
        self.args: str = str(request.get("args", ""))
        self.command: str = str(request.get("command", ""))
        self.imgs: list[str] = list(request.get("imgs", []))
        self.raw_message: Union[str, dict] = request.get("raw_message", "")
        self.reply_to: dict | None = request.get("reply_to")
        self._message_id: str = str(
            request.get("message_id")
            or (self.reply_to.get("message_id") if isinstance(self.reply_to, dict) else "")
            or ""
        )

    @property
    def message_id(self) -> str:
        if isinstance(self.reply_to, dict) and "message_id" in self.reply_to:
            return str(self.reply_to["message_id"])
        return self._message_id

    @message_id.setter
    def message_id(self, value: str) -> None:
        self._message_id = str(value)

    def __str__(self) -> str:
        args_display = self.args if self.args else "NONE"
        return f"<MessageRequest: args: {args_display}, command: {self.command}>"

