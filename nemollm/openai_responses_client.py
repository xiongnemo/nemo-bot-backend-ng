"""OpenAI Responses API client adapter."""

from __future__ import annotations

import json
import logging
from typing import Any

import requests

from .base import BaseLLMClient
from .types import ChatMessage, LLMResponse, ToolCall, ToolDefinition

logger = logging.getLogger(__name__)


class OpenAIResponsesClient(BaseLLMClient):
    """Client for OpenAI's new Responses API (/v1/responses)."""

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
        # 1. Build input array
        wire_messages: list[dict[str, Any]] = []
        if system:
            wire_messages.append({"role": "system", "content": system})

        for msg in messages:
            wire_messages.append(self._to_wire_message(msg))

        # 2. Build payload
        payload: dict[str, Any] = {
            "model": model,
            "input": wire_messages,
        }
        
        final_temp = temperature if temperature is not None else self.default_temperature
        if final_temp is not None:
            payload["temperature"] = final_temp
            
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        if tools:
            payload["tools"] = [t.to_openai_tool() for t in tools]
            payload["tool_choice"] = "auto"

        payload.update(kwargs)

        # 3. Execute request
        base = self.base_url.rstrip("/")
        url = f"{base}/responses" if base.endswith("/v1") else f"{base}/v1/responses"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        is_stream = payload.get("stream", False)
        logger.debug("POST %s (model=%s, tools=%d, stream=%s)", url, model, len(tools or []), is_stream)
        resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout, stream=is_stream)

        # Handle o1 or models that do not support temperature
        if resp.status_code == 400 and "temperature" in resp.text:
            logger.warning("Temperature is unsupported for this model, retrying without temperature.")
            if "temperature" in payload:
                del payload["temperature"]
            resp = requests.post(url, json=payload, headers=headers, timeout=self.timeout, stream=is_stream)

        if resp.status_code != 200:
            logger.error("OpenAI Responses API error: %d %s", resp.status_code, resp.text)
        resp.raise_for_status()

        out_text = ""
        wire_tool_calls = []
        usage_data = None
        raw_data = {}

        if is_stream:
            tool_calls_dict = {}
            for line in resp.iter_lines():
                if not line:
                    continue
                line_str = line.decode("utf-8")
                if line_str.startswith("data: "):
                    data_str = line_str[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    # Fallback to standard chat completions delta
                    if "choices" in chunk and isinstance(chunk["choices"], list) and len(chunk["choices"]) > 0:
                        delta = chunk["choices"][0].get("delta", {})
                        if "content" in delta and isinstance(delta["content"], str):
                            out_text += delta["content"]
                        if "tool_calls" in delta:
                            for tc in delta["tool_calls"]:
                                idx = tc.get("index", tc.get("id", len(tool_calls_dict)))
                                if idx not in tool_calls_dict:
                                    tool_calls_dict[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                                if tc.get("id"):
                                    tool_calls_dict[idx]["id"] = tc["id"]
                                func = tc.get("function", {})
                                if func.get("name"):
                                    tool_calls_dict[idx]["function"]["name"] += func["name"]
                                if func.get("arguments"):
                                    tool_calls_dict[idx]["function"]["arguments"] += func["arguments"]
                                    
                    # hypothetical /v1/responses streaming format
                    elif "output" in chunk and isinstance(chunk["output"], list):
                        for out_item in chunk["output"]:
                            if out_item.get("type") == "message" and "content" in out_item:
                                if isinstance(out_item["content"], str):
                                    out_text += out_item["content"]
                            elif "delta" in out_item:
                                delta = out_item["delta"]
                                if "content" in delta and isinstance(delta["content"], str):
                                    out_text += delta["content"]

                    if "usage" in chunk:
                        usage_data = chunk["usage"]

            for idx, tc in tool_calls_dict.items():
                wire_tool_calls.append(tc)
                
            raw_data = {"stream_consumed": True}
        else:
            data = resp.json()
            raw_data = data
            usage_data = data.get("usage")

            # In /v1/responses, data typically has an "output" array instead of "choices".
            if "output" in data and isinstance(data["output"], list):
                for out_item in data["output"]:
                    if out_item.get("type") == "message" and "content" in out_item:
                        if isinstance(out_item["content"], str):
                            out_text += out_item["content"]
                        elif isinstance(out_item["content"], list):
                            for block in out_item["content"]:
                                if isinstance(block, dict) and block.get("type") in ("output_text", "text"):
                                    out_text += block.get("text", "")
                    elif out_item.get("type") == "tool_call":
                        wire_tool_calls.append(out_item)
                    # Some implementations put tool_calls inside message content
                    if out_item.get("type") == "message" and "tool_calls" in out_item:
                        wire_tool_calls.extend(out_item["tool_calls"])
            elif "choices" in data:
                # Fallback to standard chat completions format just in case
                choice = data.get("choices", [{}])[0]
                msg_out = choice.get("message", {})
                out_text = msg_out.get("content") or ""
                wire_tool_calls = msg_out.get("tool_calls") or []
            else:
                logger.warning("Unexpected response format from Responses API: %s", data)

        return LLMResponse(
            text=out_text,
            tool_calls=self._parse_tool_calls(wire_tool_calls),
            usage=usage_data,
            finish_reason="stop", # Defaults to stop
            raw=raw_data,
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
