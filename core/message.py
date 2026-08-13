"""
Message — the primary interface that plugins use to reply/send messages.

This is intentionally kept compatible with the old backend so that all
existing plugins (echo, weather, chat_gemini, …) work without any changes.
Plugins call ``message.reply("text")`` or ``message.send("text")``, and the
adapters deliver the message to the chat platform.
"""

from __future__ import annotations

import importlib
from itertools import zip_longest
from pathlib import Path
from typing import Iterable, Union

from .message_context import MessageContext
from .message_request import MessageRequest

MAX_LINE_PER_MESSAGE = 30

MAX_LINE_COUNT = 5


def _grouper(iterable, n, fillvalue=None):
    args = [iter(iterable)] * n
    return zip_longest(*args, fillvalue=fillvalue)


def _transform_url(url: Union[str, Path]) -> Union[str, Path]:
    if isinstance(url, Path):
        return url
    if isinstance(url, str):
        return url if url.startswith("http") else Path(url)
    raise TypeError(f"不支持的类型: {type(url)}")


class Message:
    """
    Wraps a raw ingest payload and provides .reply() / .send() that
    dispatch through the appropriate adapter.
    """

    def __init__(self, message: dict) -> None:
        self.frontend: str = message["frontend"]
        self.context = MessageContext(message["context"])
        self.request = MessageRequest(message["request"])

    def __str__(self) -> str:
        return (
            f"<Message: frontend: {self.frontend}, "
            f"context: {self.context}, request: {self.request}>"
        )

    # ------------------------------------------------------------------
    # Serialisation helpers
    # ------------------------------------------------------------------

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
                "reply_to": self.request.reply_to,
                "message_id": self.request.message_id,
            },
        }

    # ------------------------------------------------------------------
    # Outbound: send / reply
    # ------------------------------------------------------------------

    def _get_adapter(self):
        """Lazy-load the adapter module for this frontend."""
        return importlib.import_module(f"adapters.{self.frontend}")

    def send(
        self,
        raw_message: Union[str, Iterable] = "",
        auto_escape: bool = False,
        voice_url: Union[str, Path, None] = None,
        photo_url: Union[str, Path, None] = None,
    ):
        adapter = self._get_adapter()
        if voice_url:
            voice_url = _transform_url(voice_url)
            adapter.send_voice(
                context=self.context, message=raw_message,
                auto_escape=auto_escape, voice=voice_url, reply=False,
            )
            return
        if photo_url:
            photo_url = _transform_url(photo_url)
            adapter.send_photo(
                context=self.context, message=raw_message,
                auto_escape=auto_escape, photo=photo_url, reply=False,
            )
            return
        lines = self._to_lines(raw_message)
        grouped = list(_grouper(lines, MAX_LINE_PER_MESSAGE, ""))
        if (
            self.frontend == "cqhttp"
            and self.context.group_id
            and len(grouped) > 1
        ):
            result = adapter.send_group_forward_msg(
                context=self.context, messages=grouped,
            )
            if not result.get("retcode"):
                return
        for group in grouped:
            text = "\n".join(group).strip()
            adapter.send_msg(
                context=self.context, message=text, auto_escape=auto_escape,
            )

    def reply(
        self,
        raw_message: Union[str, Iterable] = "",
        auto_escape: bool = True,
        voice_url: Union[str, Path, None] = None,
        photo_url: Union[str, Path, None] = None,
    ):
        adapter = self._get_adapter()
        if voice_url:
            voice_url = _transform_url(voice_url)
            adapter.send_voice(
                context=self.context, message=raw_message,
                auto_escape=auto_escape, voice=voice_url, reply=True,
            )
            return
        if photo_url:
            photo_url = _transform_url(photo_url)
            adapter.send_photo(
                context=self.context, message=raw_message,
                auto_escape=auto_escape, photo=photo_url, reply=True,
            )
            return

        lines = self._to_lines(raw_message)
        grouped = list(_grouper(lines, MAX_LINE_PER_MESSAGE, ""))
        if len(grouped) > MAX_LINE_COUNT:
            adapter.send_msg(
                context=self.context, message="Nemo: 消息过长",
                auto_escape=auto_escape, reply=True,
            )

        import time as _time

        for group in grouped:
            text = "\n".join(group).strip()
            adapter.send_msg(
                context=self.context, message=text,
                auto_escape=auto_escape, reply=True,
            )
            if self.frontend in ("cqhttp", "cqhttp_ws", "onebot", "satori_http"):
                _time.sleep(1.4)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _to_lines(raw_message) -> list[str]:
        if isinstance(raw_message, str):
            return raw_message.splitlines()
        if isinstance(raw_message, Iterable):
            return [str(e) for e in raw_message]
        return str(raw_message).splitlines()

