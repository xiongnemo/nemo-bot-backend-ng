"""Base interface for all LLM clients."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Iterator

from .types import ChatMessage, LLMResponse, LLMStreamChunk, ToolDefinition

logger = logging.getLogger(__name__)


class BaseLLMClient(ABC):
    """
    Abstract base class for LLM providers.
    Every provider must implement at least `chat`.
    """

    def __init__(self, base_url: str, api_key: str, timeout: int = 120, default_temperature: float | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.default_temperature = default_temperature

    @abstractmethod
    def chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        system: str = "",
        tools: list[ToolDefinition] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> LLMResponse:
        """
        Send a chat completion request to the provider.

        Args:
            model: The model name (e.g. "gpt-4o", "gemini-1.5-pro").
            messages: List of conversation messages (excluding system).
            system: The system prompt (if any).
            tools: List of ToolDefinitions available to the model.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.
            **kwargs: Provider-specific overrides.
        """
        pass

    def chat_stream(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        system: str = "",
        tools: list[ToolDefinition] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs,
    ) -> Iterator[LLMStreamChunk]:
        """
        Streaming version of chat. Override in subclass if needed.
        """
        raise NotImplementedError("Streaming not implemented for this provider")

