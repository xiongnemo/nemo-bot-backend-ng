"""Gemini Native API client (generateContent)."""

from __future__ import annotations

import logging
from typing import Any

import requests

from .base import BaseLLMClient
from .types import ChatMessage, LLMResponse, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)


class GeminiClient(BaseLLMClient):
    """Client for Google Gemini API."""

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
        contents: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "tool":
                is_coalesced = False
                if contents and contents[-1]["role"] == "user":
                    if any("functionResponse" in p for p in contents[-1]["parts"]):
                        contents[-1]["parts"].append({
                            "functionResponse": {
                                "name": msg.name or "unknown",
                                "response": {"result": str(msg.content)},
                            }
                        })
                        is_coalesced = True
                
                if not is_coalesced:
                    contents.append({
                        "role": "user",
                        "parts": [{
                            "functionResponse": {
                                "name": msg.name or "unknown",
                                "response": {"result": str(msg.content)},
                            }
                        }]
                    })
            else:
                contents.append(self._to_gemini_content(msg))

        # 2. Build payload
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {},
        }
        
        final_temp = temperature if temperature is not None else self.default_temperature
        if final_temp is not None:
            payload["generationConfig"]["temperature"] = final_temp
        if kwargs.get("response_format") == "json":
            payload["generationConfig"]["responseMimeType"] = "application/json"
        
        # Remove response_format from kwargs before updating payload
        kwargs.pop("response_format", None)
        if max_tokens:
            payload["generationConfig"]["maxOutputTokens"] = max_tokens
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}

        if tools:
            # Gemini nests function declarations
            payload["tools"] = [{"functionDeclarations": [
                {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                } for t in tools
            ]}]

        payload.update(kwargs)

        # 3. Execute
        # Note: model name usually includes prefix "models/" in Gemini API,
        # but if the user just passes "gemini-1.5-pro", we append it.
        model_path = model if "/" in model else f"models/{model}"
        url = f"{self.base_url}/v1beta/{model_path}:generateContent"

        resp = requests.post(url, params={"key": self.api_key}, json=payload, timeout=self.timeout)
        if resp.status_code != 200:
            logger.error("Gemini API error: %d %s", resp.status_code, resp.text)
        resp.raise_for_status()

        data = resp.json()

        # 4. Parse content blocks (candidates)
        candidate = data.get("candidates", [{}])[0]
        content = candidate.get("content", {})
        
        text = ""
        tool_calls = []
        
        for part in content.get("parts", []):
            if "text" in part:
                text += part["text"]
            elif "functionCall" in part:
                fc = part["functionCall"]
                # Gemini doesn't use explicit tool_call_ids, we generate a dummy one
                tool_calls.append(ToolCall(
                    id="call_gemini_" + fc.get("name", ""),
                    name=fc.get("name", ""),
                    arguments=fc.get("args", {}),
                ))

        return LLMResponse(
            text=text.strip(),
            tool_calls=tool_calls if tool_calls else None,
            usage=data.get("usageMetadata"),
            finish_reason=candidate.get("finishReason", ""),
            raw=data,
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _to_gemini_content(self, msg: ChatMessage) -> dict[str, Any]:
        """Convert unified ChatMessage to Gemini Content Object."""
        # Gemini roles: "user" or "model"
        role = "model" if msg.role == "assistant" else "user"
        parts = []

        if msg.role == "tool":
            # Function response
            parts.append({
                "functionResponse": {
                    "name": msg.name or "unknown",
                    "response": {"result": str(msg.content)},
                }
            })
        else:
            if isinstance(msg.content, list):
                for part in msg.content:
                    if part.get("type") == "text":
                        parts.append({"text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url.startswith("data:"):
                            mime_type = url.split(";")[0][5:]
                            b64_data = url.split(",", 1)[1]
                            parts.append({
                                "inlineData": {
                                    "mimeType": mime_type,
                                    "data": b64_data
                                }
                            })
            elif msg.content:
                parts.append({"text": str(msg.content)})
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    parts.append({
                        "functionCall": {
                            "name": tc.name,
                            "args": tc.arguments,
                        }
                    })

        return {"role": role, "parts": parts}
