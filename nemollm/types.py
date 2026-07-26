"""
nemollm.types — data classes shared across all providers.

ToolDefinition follows the OpenAI function calling standard (JSON Schema
parameters), so it maps directly to any provider that supports tool/function
calling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional


@dataclass
class ToolCall:
    """A single tool invocation requested by the model."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ToolDefinition:
    """
    Standard tool/function definition — compatible with OpenAI function
    calling JSON Schema.

    Example::

        ToolDefinition(
            name="weather",
            description="查询中国城市天气",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "城市名称"}
                },
                "required": ["query"],
            },
        )
    """
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=lambda: {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "查询内容"},
        },
        "required": ["query"],
    })

    def to_openai_tool(self) -> dict:
        """Render as an OpenAI-style tool object."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ChatMessage:
    """
    A single message in a conversation, provider-agnostic.

    ``content`` can be:
    - a plain string (text)
    - a list of content parts for multimodal (each part is a dict)
    """
    role: Literal["user", "assistant", "system", "tool"]
    content: str | list[dict[str, Any]] = ""
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None
    name: str | None = None

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in self.tool_calls
            ]
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if self.name:
            d["name"] = self.name
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ChatMessage":
        tcs = None
        if "tool_calls" in d and d["tool_calls"]:
            tcs = [
                ToolCall(id=tc["id"], name=tc["name"], arguments=tc["arguments"])
                for tc in d["tool_calls"]
            ]
        return cls(
            role=d["role"],
            content=d.get("content", ""),
            tool_calls=tcs,
            tool_call_id=d.get("tool_call_id"),
            name=d.get("name"),
        )


@dataclass
class LLMResponse:
    """Unified response from any LLM provider."""
    text: str = ""
    tool_calls: list[ToolCall] | None = None
    usage: dict[str, Any] | None = None
    raw: dict | None = None
    thinking: str | None = None  # Extended thinking / Gemini thought
    finish_reason: str = ""

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class LLMStreamChunk:
    """A single chunk from a streaming response."""
    delta_text: str = ""
    tool_calls_delta: list[dict] | None = None
    finish_reason: Optional[str] = None
