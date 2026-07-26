"""MessageRequest — identical interface to the old backend for plugin compat."""

from __future__ import annotations

from typing import Union


class MessageRequest:
    def __init__(self, request: dict) -> None:
        self.args: str = str(request.get("args", ""))
        self.command: str = str(request.get("command", ""))
        self.imgs: list[str] = list(request.get("imgs", []))
        self.raw_message: Union[str, dict] = request.get("raw_message", "")

    def __str__(self) -> str:
        args_display = self.args if self.args else "NONE"
        return f"<MessageRequest: args: {args_display}, command: {self.command}>"
