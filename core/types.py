"""Core types used throughout nemo-bot-backend-ng."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


# ---------------------------------------------------------------------------
# Action: a single outbound operation (reply / send) produced by a plugin or
# the agent.  The Sender reads these and dispatches them via adapters.
# ---------------------------------------------------------------------------

@dataclass
class Action:
    kind: Literal["reply", "send"]
    text: str = ""
    auto_escape: bool = True
    photo_url: Optional[str] = None
    voice_url: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "text": self.text,
            "auto_escape": self.auto_escape,
            "photo_url": self.photo_url,
            "voice_url": self.voice_url,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Action":
        return cls(
            kind=d["kind"],
            text=d.get("text", ""),
            auto_escape=d.get("auto_escape", True),
            photo_url=d.get("photo_url"),
            voice_url=d.get("voice_url"),
        )


# ---------------------------------------------------------------------------
# PluginResult: the structured output of executing a plugin in a worker.
# Serialisable so it can cross the process boundary.
# ---------------------------------------------------------------------------

@dataclass
class PluginResult:
    ok: bool = True
    actions: list[Action] = field(default_factory=list)
    payload: Any = None
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "actions": [a.to_dict() for a in self.actions],
            "payload": self.payload,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PluginResult":
        return cls(
            ok=d.get("ok", True),
            actions=[Action.from_dict(a) for a in d.get("actions", [])],
            payload=d.get("payload"),
            error=d.get("error", ""),
        )


# ---------------------------------------------------------------------------
# RouteResult: the decision produced by the Router for a given message.
# ---------------------------------------------------------------------------

@dataclass
class RouteResult:
    mode: Literal["command", "agent", "silent", "man", "explain", "management"]
    plugin: str = ""
    args: str = ""
    query: str = ""


# ---------------------------------------------------------------------------
# IngestMessage: the standard envelope that every frontend sends to /ingest.
# ---------------------------------------------------------------------------

@dataclass
class IngestMessage:
    frontend: str
    group_id: str
    user_id: str
    user_name: str
    message_id: str
    self_id: str
    ated: bool
    text: str
    imgs: list[str]
    raw_message: Any
    timestamp: float = 0.0
    nickname: str = ""
    reply_to: dict | None = None

    @property
    def full_text(self) -> str:
        if self.reply_to and "text" in self.reply_to:
            return f"{self.text} {self.reply_to['text']}".strip()
        return self.text

    def to_dict(self) -> dict:
        """Convert to the wire dict that Message.__init__ expects."""
        return {
            "frontend": self.frontend,
            "context": {
                "group_id": self.group_id,
                "user_id": self.user_id,
                "user_name": self.user_name,
                "message_id": self.message_id,
                "self_id": self.self_id,
                "ated": self.ated,
            },
            "request": {
                "command": "",
                "args": self.text,
                "imgs": self.imgs,
                "raw_message": self.raw_message,
                "reply_to": self.reply_to,
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "IngestMessage":
        ctx = d.get("context", {})
        req = d.get("request", {})
        import time as _time

        return cls(
            frontend=d.get("frontend", ""),
            group_id=str(ctx.get("group_id", "")),
            user_id=str(ctx.get("user_id", "")),
            user_name=str(ctx.get("nickname", "") or ctx.get("user_name", "")),
            message_id=str(ctx.get("message_id", "")),
            self_id=str(ctx.get("self_id", "")),
            ated=bool(ctx.get("ated", False)),
            text=str(req.get("args", "")),
            imgs=list(req.get("imgs", [])),
            raw_message=req.get("raw_message", ""),
            timestamp=float(d.get("timestamp", _time.time())),
            nickname=str(ctx.get("nickname", "")),
            reply_to=req.get("reply_to", None),
        )
