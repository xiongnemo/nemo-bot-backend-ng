"""
RecordingMessage — a drop-in replacement for Message that *records*
reply/send calls instead of actually dispatching them through adapters.

This is the key adapter layer that lets existing sync plugins be used as
agent tools: the plugin calls ``message.reply("weather is sunny")``, and
instead of sending to QQ/WeChat, the text is captured in ``self.outbox``
as an Action.  The agent then reads it as a structured observation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Union

from .types import Action
from .message_context import MessageContext
from .message_request import MessageRequest


class RecordingMessage:
    """
    Implements the same interface as Message (reply / send / attributes)
    but captures all output into ``self.outbox`` instead of sending it.

    NOTE: we intentionally do NOT inherit from Message to avoid importing
    adapters in worker processes.  Plugins only use .reply(), .send(),
    .frontend, .context, and .request — all of which we provide.
    """

    def __init__(self, message_dict: dict) -> None:
        self.frontend: str = message_dict["frontend"]
        self.context = MessageContext(message_dict["context"])
        self.request = MessageRequest(message_dict["request"])
        self.outbox: list[Action] = []
        self.payload: Any = None

    def __str__(self) -> str:
        return (
            f"<RecordingMessage: frontend: {self.frontend}, "
            f"context: {self.context}, request: {self.request}, "
            f"recorded_actions: {len(self.outbox)}>"
        )

    def to_dict(self) -> dict:
        return {
            "frontend": self.frontend,
            "context": {
                "group_id": self.context.group_id,
                "user_id": self.context.user_id,
                "user_name": self.context.user_name,
                "message_id": self.context.message_id,
                "self_id": self.context.self_id,
                "ated": self.context.ated,
                "frontend_system_info": self.context.frontend_system_info,
            },
            "request": {
                "command": self.request.command,
                "args": self.request.args,
                "imgs": self.request.imgs,
                "raw_message": self.request.raw_message,
            },
        }

    # ------------------------------------------------------------------
    # Recording versions of reply / send
    # ------------------------------------------------------------------

    def reply(
        self,
        raw_message: Union[str, Iterable] = "",
        auto_escape: bool = True,
        voice_url: Union[str, Path, None] = None,
        photo_url: Union[str, Path, None] = None,
    ):
        self.outbox.append(Action(
            kind="reply",
            text=self._flatten(raw_message),
            auto_escape=auto_escape,
            photo_url=str(photo_url) if photo_url else None,
            voice_url=str(voice_url) if voice_url else None,
        ))

    def send(
        self,
        raw_message: Union[str, Iterable] = "",
        auto_escape: bool = False,
        voice_url: Union[str, Path, None] = None,
        photo_url: Union[str, Path, None] = None,
    ):
        self.outbox.append(Action(
            kind="send",
            text=self._flatten(raw_message),
            auto_escape=auto_escape,
            photo_url=str(photo_url) if photo_url else None,
            voice_url=str(voice_url) if voice_url else None,
        ))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _flatten(raw_message) -> str:
        if isinstance(raw_message, str):
            return raw_message
        if isinstance(raw_message, Iterable):
            return "\n".join(str(e) for e in raw_message)
        return str(raw_message)
