"""Base interface for all LLM clients."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Iterator

from .types import ChatMessage, LLMResponse, LLMStreamChunk, ToolDefinition

logger = logging.getLogger(__name__)

VALID_THINKING_EFFORTS = {
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "extra_high",
    "extra-high",
    "ultra",
    "max",
    "extreme",
    "none",
    "off",
    "disabled",
}


def parse_model_and_effort(model_name: str) -> tuple[str, str | None]:
    """
    Parse a model string that may include an optional thinking effort or token budget suffix.
    
    Examples:
        - "glm-5.3:medium" -> ("glm-5.3", "medium")
        - "glm-5.3:max" -> ("glm-5.3", "max")
        - "claude-3-7-sonnet:4096" -> ("claude-3-7-sonnet", "4096")
        - "llama3:8b" -> ("llama3:8b", None)
        - "google/gemini-2.0-flash:free:high" -> ("google/gemini-2.0-flash:free", "high")
        - "gpt-4o:nitro" -> ("gpt-4o:nitro", None)
    """
    if not model_name or ":" not in model_name:
        return model_name, None

    prefix, suffix = model_name.rsplit(":", 1)
    suffix_clean = suffix.strip().lower()

    if suffix_clean in VALID_THINKING_EFFORTS:
        return prefix, suffix_clean

    if suffix_clean.isdigit():
        val = int(suffix_clean)
        # Token budget typically between 0 (disabled) and 131072
        if 0 <= val <= 131072:
            return prefix, suffix_clean

    return model_name, None


def map_effort_to_anthropic_budget(effort: str) -> int:
    """Map string effort to Anthropic thinking budget tokens."""
    effort_lower = effort.lower()
    if effort_lower.isdigit():
        return int(effort_lower)
    mapping = {
        "minimal": 1024,
        "low": 2048,
        "medium": 4096,
        "high": 8192,
        "xhigh": 16384,
        "extra_high": 16384,
        "extra-high": 16384,
        "ultra": 32768,
        "max": 32768,
        "extreme": 65536,
    }
    return mapping.get(effort_lower, 4096)


def map_effort_to_gemini_budget(effort: str) -> int:
    """Map string effort to Gemini thinkingBudget tokens."""
    effort_lower = effort.lower()
    if effort_lower.isdigit():
        return int(effort_lower)
    mapping = {
        "minimal": 1024,
        "low": 1024,
        "medium": 4096,
        "high": 8192,
        "xhigh": 16384,
        "extra_high": 16384,
        "extra-high": 16384,
        "ultra": 32768,
        "max": 32768,
        "extreme": 65536,
    }
    return mapping.get(effort_lower, 4096)


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

