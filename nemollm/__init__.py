"""
nemollm — unified LLM client library for nemo-bot.

Provides a single interface across OpenAI, Anthropic, and Gemini APIs
with built-in conversation memory backed by SQLite.

Quick start::

    from nemollm import chat, chat_with_memory

    # Simple one-shot
    resp = chat(model="gemini-3.5-flash", messages=[...])

    # With persistent memory (scope-keyed SQLite storage)
    resp = chat_with_memory(
        scope_key="agent:satori_http:group_123:user_456",
        model="gemini-3.5-flash",
        user_text="今天天气怎么样",
    )
"""

from .types import ChatMessage, LLMResponse, ToolCall, ToolDefinition
from .registry import ModelRegistry, get_registry

__all__ = [
    "ChatMessage",
    "LLMResponse",
    "ToolCall",
    "ToolDefinition",
    "ModelRegistry",
    "get_registry",
]
