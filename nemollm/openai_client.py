"""OpenAI-compatible client (also used for most relays/middle-layers)."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from .base import BaseLLMClient
from .types import ChatMessage, LLMResponse, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)


class OpenAIClient(BaseLLMClient):
    """Client for OpenAI and OpenAI-compatible endpoints."""

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
        # 1. Build messages array (system goes first if present)
        wire_messages: list[dict[str, Any]] = []
        if system:
            wire_messages.append({"role": "system", "content": system})

        for msg in messages:
            wire_messages.append(self._to_wire_message(msg))

        # 2. Build payload
        payload: dict[str, Any] = {
            "model": model,
            "messages": wire_messages,
        }
        
        final_temp = temperature if temperature is not None else self.default_temperature
        if final_temp is not None:
            payload["temperature"] = final_temp
        if kwargs.get("response_format") == "json":
            payload["response_format"] = {"type": "json_object"}
            
        kwargs.pop("response_format", None)
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = [t.to_openai_tool() for t in tools]
            # If we pass tools, tell the model it can auto-select
            payload["tool_choice"] = "auto"

        payload.update(kwargs)

        # 3. Execute request
        base = self.base_url.rstrip("/")
        url = f"{base}/chat/completions" if base.endswith("/v1") else f"{base}/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        logger.debug("POST %s (model=%s, tools=%d)", url, model, len(tools or []))
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)

        # Handle o1 or models that do not support temperature
        if resp.status_code == 400 and "temperature" in resp.text:
            logger.warning("Temperature is unsupported for this model (OpenAI), retrying without temperature.")
            if "temperature" in payload:
                del payload["temperature"]
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)

        if resp.status_code != 200:
            logger.error("OpenAI API error: %d %s", resp.status_code, resp.text)
        resp.raise_for_status()

        data = resp.json()

        # 4. Parse response
        choice = data.get("choices", [{}])[0]
        msg_out = choice.get("message", {})

        return LLMResponse(
            text=msg_out.get("content") or "",
            tool_calls=self._parse_tool_calls(msg_out.get("tool_calls")),
            usage=data.get("usage"),
            finish_reason=choice.get("finish_reason", ""),
            raw=data,
        )

    # ------------------------------------------------------------------
    # Internal Translation Helpers
    # ------------------------------------------------------------------

    def _get_safe_id(self, original_id: str) -> str:
        if not original_id:
            return "call_000000000000000000000000"
        if original_id.startswith("call_") and len(original_id) == 29 and original_id[5:].isalnum():
            return original_id
        import hashlib
        h = hashlib.md5(original_id.encode()).hexdigest()[:24]
        return f"call_{h}"

    def _to_wire_message(self, msg: ChatMessage) -> dict[str, Any]:
        """Convert a unified ChatMessage to OpenAI format."""
        m: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.name:
            m["name"] = msg.name
        if msg.tool_call_id:
            m["tool_call_id"] = self._get_safe_id(msg.tool_call_id)

        if msg.tool_calls:
            m["tool_calls"] = [
                {
                    "id": self._get_safe_id(tc.id),
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in msg.tool_calls
            ]
        return m

    def _parse_tool_calls(self, wire_tool_calls: list[dict] | None) -> list[ToolCall] | None:
        """Parse OpenAI tool_calls into unified ToolCall objects."""
        if not wire_tool_calls:
            return None
        result = []
        for wtc in wire_tool_calls:
            if wtc.get("type") != "function":
                continue
            func = wtc.get("function", {})
            try:
                args = json.loads(func.get("arguments", "{}"))
            except json.JSONDecodeError:
                args = {}  # fallback if model returned bad JSON
            result.append(ToolCall(
                id=wtc.get("id", ""),
                name=func.get("name", ""),
                arguments=args,
            ))
        return result
