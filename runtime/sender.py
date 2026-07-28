"""
Sender — delivers Actions (produced by plugins or the agent) to chat
platforms via the appropriate adapter.

This is the single exit point for all outbound messages.  It reads
the ``frontend`` field to pick the right adapter module and calls
send_msg / send_voice / send_photo accordingly.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from core.types import Action

logger = logging.getLogger(__name__)

# These will be populated from adapters/* at import time
import adapters  # noqa: F401 — triggers auto-import of all adapter modules


class Sender:
    """
    Stateless sender.  Given a message dict (with frontend + context) and a
    list of Actions, deliver each action through the correct adapter.
    """

    # Adapters that need a rate-limit delay between consecutive messages
    _RATE_LIMITED_ADAPTERS = {"cqhttp", "cqhttp_ws", "onebot", "satori_http"}

    def deliver(self, message_dict: dict, result: dict) -> None:
        """Deliver all actions from a PluginResult dict."""
        actions = result.get("actions", [])
        if not actions:
            return
        for action_dict in actions:
            self._deliver_one(message_dict, Action.from_dict(action_dict))

    def deliver_actions(self, message_dict: dict, actions: list[Action]) -> None:
        """Deliver a list of Action objects."""
        for action in actions:
            self._deliver_one(message_dict, action)

    def send_text(self, message_dict: dict, text: str, reply: bool = True) -> None:
        """Convenience: send a single text message."""
        action = Action(kind="reply" if reply else "send", text=text)
        self._deliver_one(message_dict, action)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _deliver_one(self, message_dict: dict, action: Action) -> None:
        frontend = message_dict.get("frontend", "")
        context = message_dict.get("context", {})

        try:
            import importlib
            from core.message_context import MessageContext
            from pathlib import Path
            
            adapter = importlib.import_module(f"adapters.{frontend}")
            if adapter is None:
                logger.error("No adapter found for frontend: %s", frontend)
                return

            ctx = MessageContext(context)

            def _transform_url(url: str | None):
                if not url: return None
                if url.startswith("http://") or url.startswith("https://") or url.startswith("base64://") or url.startswith("file://"):
                    return url
                return Path(url)

            if action.voice_url:
                adapter.send_voice(
                    context=ctx, message=action.text,
                    auto_escape=action.auto_escape,
                    voice=_transform_url(action.voice_url),
                    reply=(action.kind == "reply"),
                )
            elif action.photo_url:
                adapter.send_photo(
                    context=ctx, message=action.text,
                    auto_escape=action.auto_escape,
                    photo=_transform_url(action.photo_url),
                    reply=(action.kind == "reply"),
                )
            else:
                adapter.send_msg(
                    context=ctx, message=action.text,
                    auto_escape=action.auto_escape,
                    reply=(action.kind == "reply"),
                )

            if frontend in self._RATE_LIMITED_ADAPTERS:
                time.sleep(1.4)

        except Exception:
            logger.exception("Failed to deliver action via %s", frontend)
