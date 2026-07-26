"""
Router — the core decision engine for every incoming message.

Decides between: command, agent, man, explain, management, or silent.
"""

from __future__ import annotations

import logging
from typing import List

from core.types import IngestMessage, RouteResult
from store.state_store import StateStore
from .ruleset import Ruleset

logger = logging.getLogger(__name__)


class Router:
    def __init__(
        self,
        ruleset: Ruleset,
        state_store: StateStore,
        bot_names: List[str],
        trigger_prefixes: List[str],
    ):
        self.ruleset = ruleset
        self.state_store = state_store
        self.bot_names = bot_names
        self.trigger_prefixes = trigger_prefixes

    def route(self, msg: IngestMessage) -> RouteResult:
        text = msg.text.strip()
        if not text:
            return RouteResult("silent")

        # 0. Apply Alias rewriting
        # e.g. alias "wt" -> "天气 上海"
        alias_target = self.state_store.get_alias(text)
        if alias_target:
            logger.debug("Alias hit: %r -> %r", text, alias_target)
            msg.text = alias_target  # Mutate for subsequent routing
            text = alias_target

        # 1. Built-in help/system commands
        if text.startswith("man ") or text == "man":
            args = text[4:].strip() if text.startswith("man ") else ""
            return RouteResult(mode="man", args=args)
        if text.startswith("explain "):
            return RouteResult(mode="explain", args=text[8:].strip())

        # 2. Deterministic Rule Match (Command)
        hit = self.ruleset.match(msg)
        if hit:
            return RouteResult(mode="command", plugin=hit.plugin, args=hit.args)

        # 3. Explicit Agent Triggers ("nemonemo", "@bot")
        for pfx in self.trigger_prefixes:
            if text.startswith(pfx):
                query = text[len(pfx):].strip()
                return RouteResult(mode="agent", query=query)

        if msg.ated:
            return RouteResult(mode="agent", query=text)

        # 4. NLP / Keyword check (is it addressing the bot?)
        if self._is_addressing_me(text):
            return RouteResult(mode="agent", query=text)

        # 5. Group chat noise -> ignore
        if msg.group_id:
            return RouteResult(mode="silent")

        # 6. Direct Message (fallback to agent)
        return RouteResult(mode="agent", query=text)

    def _is_addressing_me(self, text: str) -> bool:
        lower = text.lower()
        for name in self.bot_names:
            if name in lower:
                return True
        return False
