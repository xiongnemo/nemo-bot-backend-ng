"""Anthropic Messages API client."""

from __future__ import annotations

import logging
from typing import Any

import requests

from .base import BaseLLMClient
from .types import ChatMessage, LLMResponse, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)


class AnthropicClient(BaseLLMClient):
    """Client for Anthropic API (Claude)."""

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
        # 1. Translate messages
        wire_messages: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "tool":
                safe_id = self._get_safe_id(msg.tool_call_id)
                is_coalesced = False
                if wire_messages and wire_messages[-1]["role"] == "user":
                    if any(b.get("type") == "tool_result" for b in wire_messages[-1].get("content", [])):
                        wire_messages[-1]["content"].append({
                            "type": "tool_result",
                            "tool_use_id": safe_id,
                            "content": str(msg.content),
                        })
                        is_coalesced = True
                        
                if not is_coalesced:
                    wire_messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": safe_id,
                            "content": str(msg.content),
                        }]
                    })
            else:
                wire_messages.append(self._to_wire_message(msg))

        # 2. Build payload
        payload: dict[str, Any] = {
            "model": model,
            "messages": wire_messages,
            "max_tokens": max_tokens or 8192,
        }
        
        final_temp = temperature if temperature is not None else self.default_temperature
        if final_temp is not None:
            payload["temperature"] = final_temp
        if system:
            payload["system"] = system

        if tools:
            # Anthropic tools omit the {"type": "function", "function": {...}} nesting
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters,
                }
                for t in tools
            ]

        payload.update(kwargs)

        # 3. Execute
        url = f"{self.base_url}/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
        if resp.status_code == 400 and "temperature" in resp.text and "deprecated" in resp.text:
            logger.warning("Temperature is deprecated for this model, retrying without temperature.")
            if "temperature" in payload:
                del payload["temperature"]
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout)

        if resp.status_code != 200:
            logger.error("Anthropic API error: %d %s", resp.status_code, resp.text)
        resp.raise_for_status()

        data = resp.json()

        # 4. Parse content blocks
        text = ""
        tool_calls = []
        thinking = ""
        
        for block in data.get("content", []):
            btype = block.get("type")
            if btype == "text":
                text += block.get("text", "")
            elif btype == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.get("id", ""),
                    name=block.get("name", ""),
                    arguments=block.get("input", {}),
                ))
            elif btype == "thinking":
                thinking += block.get("thinking", "")

        return LLMResponse(
            text=text.strip(),
            tool_calls=tool_calls if tool_calls else None,
            usage=data.get("usage"),
            finish_reason=data.get("stop_reason", ""),
            thinking=thinking if thinking else None,
            raw=data,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_safe_id(self, original_id: str) -> str:
        if not original_id:
            return "toolu_000000000000000000000000"
        if original_id.startswith("toolu_") and len(original_id) == 30 and original_id[6:].isalnum():
            return original_id
        import hashlib
        h = hashlib.md5(original_id.encode()).hexdigest()[:24]
        return f"toolu_{h}"

    def _to_wire_message(self, msg: ChatMessage) -> dict[str, Any]:
        if msg.role == "tool":
            # Anthropic expects tool results as 'user' role with content type 'tool_result'
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": self._get_safe_id(msg.tool_call_id),
                        "content": str(msg.content),
                    }
                ]
            }

        if msg.tool_calls:
            # Assistant returning tool calls
            content_blocks = []
            if isinstance(msg.content, list):
                for part in msg.content:
                    if part.get("type") == "text":
                        content_blocks.append({"type": "text", "text": part.get("text", "")})
            elif msg.content:
                content_blocks.append({"type": "text", "text": str(msg.content)})
            for tc in msg.tool_calls:
                content_blocks.append({
                    "type": "tool_use",
                    "id": self._get_safe_id(tc.id),
                    "name": tc.name,
                    "input": tc.arguments,
                })
            return {"role": "assistant", "content": content_blocks}

        content_blocks = []
        if isinstance(msg.content, list):
            for part in msg.content:
                if part.get("type") == "text":
                    content_blocks.append({"type": "text", "text": part.get("text", "")})
                elif part.get("type") == "image_url":
                    url = part.get("image_url", {}).get("url", "")
                    if url.startswith("data:"):
                        mime_type = url.split(";")[0][5:]
                        b64_data = url.split(",", 1)[1]
                        content_blocks.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": mime_type,
                                "data": b64_data
                            }
                        })
            return {"role": msg.role, "content": content_blocks}

        return {"role": msg.role, "content": str(msg.content)}
