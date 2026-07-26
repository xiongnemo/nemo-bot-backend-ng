"""Persistent conversation memory backed by store.ConversationStore."""

from __future__ import annotations

import logging
from typing import Any

from store.conversation_store import ConversationStore

from .registry import get_registry
from .types import ChatMessage, LLMResponse, ToolDefinition

logger = logging.getLogger(__name__)


class ConversationMemory:
    """
    Wraps the LLM chat call with automatic SQLite history loading and saving.
    """

    def __init__(self, store: ConversationStore):
        self.store = store

    def chat(
        self,
        *,
        scope_key: str,
        user_text: str,
        model: str | None = None,
        system: str = "",
        tools: list[ToolDefinition] | None = None,
        max_history_turns: int = 30,
        **kwargs,
    ) -> LLMResponse:
        """
        1. Loads history for `scope_key`.
        2. Appends the new user message.
        3. Calls the LLM.
        4. Saves the user message + assistant response to the DB.
        """
        # 1. Load history
        history_dicts = self.store.get_history(scope_key, max_turns=max_history_turns)
        messages: list[ChatMessage] = []

        for d in history_dicts:
            # We reconstruct ChatMessage from the stored dict
            tc_data = d.get("metadata", {}).get("tool_calls")
            tcs = None
            if tc_data:
                from .types import ToolCall
                tcs = [ToolCall(**tc) for tc in tc_data]

            messages.append(ChatMessage(
                role=d["role"],
                content=d["content"],
                tool_calls=tcs,
            ))

        # 2. Append new user message
        messages.append(ChatMessage(role="user", content=user_text))

        # 3. Resolve client and call
        registry = get_registry()
        client, actual_model = registry.resolve(model)

        logger.debug("chat_with_memory: %s via %s", actual_model, type(client).__name__)
        resp = client.chat(
            model=actual_model,
            messages=messages,
            system=system,
            tools=tools,
            **kwargs,
        )

        # 4. Save to DB
        # User message
        self.store.append(scope_key, role="user", content=user_text)

        # Assistant message
        meta: dict[str, Any] = {}
        if resp.tool_calls:
            meta["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in resp.tool_calls
            ]
        self.store.append(
            scope_key,
            role="assistant",
            content=resp.text,
            metadata=meta if meta else None,
        )

        return resp
