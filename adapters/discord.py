"""
Discord Platform Adapter for nemo-bot-backend-ng.
-------------------------------------------------
Delivers outbound actions (send_msg, send_photo, send_voice, withdraw, pin, unpin)
via Discord REST API (v10).
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from pathlib import Path
from typing import Any
import requests

from config import backend_config
from core.message_context import MessageContext

logger = logging.getLogger(__name__)

# Configuration
_discord_cfg = backend_config.get("message_backend", {}).get("discord", {})
DISCORD_API_ENDPOINT = _discord_cfg.get("endpoint", "https://discord.com/api/v10").rstrip("/")
DISCORD_BOT_TOKEN = _discord_cfg.get("token", "")
DISCORD_PROXY = _discord_cfg.get("proxy", "")

s = requests.Session()
if DISCORD_PROXY:
    s.proxies.update({
        "http": DISCORD_PROXY,
        "https": DISCORD_PROXY,
    })

_dm_channel_cache: dict[str, str] = {}


def _get_headers() -> dict[str, str]:
    token = DISCORD_BOT_TOKEN or backend_config.get("message_backend", {}).get("discord", {}).get("token", "")
    return {
        "Authorization": f"Bot {token}",
        "User-Agent": "NemoBot (https://github.com/nemo-bot, 1.0)",
    }


def _safe_json(r: requests.Response) -> dict[str, Any]:
    try:
        r.raise_for_status()
        if r.status_code == 204:
            return {"ok": True}
        return r.json()
    except Exception as e:
        logger.error("Discord API Error: %s - %s", r.status_code, r.text)
        return {"ok": False, "error": str(e), "status_code": r.status_code}


def _request_with_retry(method: str, url: str, max_retries: int = 3, **kwargs) -> requests.Response:
    """Send HTTP request with automatic Discord rate-limit (HTTP 429) backoff."""
    headers = kwargs.pop("headers", None) or _get_headers()
    
    for attempt in range(max_retries):
        resp = s.request(method, url, headers=headers, **kwargs)
        if resp.status_code == 429:
            retry_after = 1.0
            try:
                data = resp.json()
                retry_after = float(data.get("retry_after", 1.0))
            except Exception:
                retry_after = float(resp.headers.get("X-RateLimit-Reset-After", 1.0))
            
            logger.warning("Discord Rate Limited (429). Retrying in %.2fs (attempt %d/%d)", retry_after, attempt + 1, max_retries)
            time.sleep(retry_after + 0.1)
            continue
        return resp
    return resp


def _resolve_target_channel(context: MessageContext) -> str | None:
    """
    Resolve the destination channel_id for Discord.
    - If group_id is present: it represents the channel_id.
    - If channel_id is explicitly present: use it.
    - If group_id is empty (DM): fetch/create the DM channel with user_id.
    """
    if context.group_id:
        return context.group_id

    raw_ctx = getattr(context, "raw_context", {}) or {}
    if getattr(context, "channel_id", ""):
        return context.channel_id
    if raw_ctx.get("channel_id"):
        return str(raw_ctx["channel_id"])

    user_id = str(context.user_id or "").strip()
    if not user_id:
        logger.error("Cannot resolve Discord destination channel: missing both group_id and user_id")
        return None

    # Check DM cache
    if user_id in _dm_channel_cache:
        return _dm_channel_cache[user_id]

    # Open DM channel via POST /users/@me/channels
    try:
        url = f"{DISCORD_API_ENDPOINT}/users/@me/channels"
        resp = _request_with_retry("POST", url, json={"recipient_id": user_id})
        if resp.status_code in (200, 201):
            dm_channel = resp.json().get("id")
            if dm_channel:
                _dm_channel_cache[user_id] = str(dm_channel)
                return str(dm_channel)
        logger.error("Failed to create DM channel for Discord user %s: %s - %s", user_id, resp.status_code, resp.text)
    except Exception as e:
        logger.exception("Exception while creating DM channel for Discord user %s: %s", user_id, e)

    return None


def _chunk_discord_message(message: str, max_len: int = 1950) -> list[str]:
    """
    Split long message into chunks under Discord's 2000 character limit,
    respecting code blocks and newline boundaries.
    """
    if not message:
        return []
    if len(message) <= max_len:
        return [message]

    lines = message.splitlines(keepends=True)
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_len = 0
    in_code_block = False
    code_lang = ""

    for line in lines:
        line_len = len(line)
        
        # Check if line contains code block toggle
        code_matches = re.findall(r"```([a-zA-Z0-9_\-+]*)\b", line)
        toggles = line.count("```")
        if toggles % 2 != 0:
            if not in_code_block:
                in_code_block = True
                code_lang = code_matches[0] if code_matches else ""
            else:
                in_code_block = False
                code_lang = ""

        # If adding this line exceeds max_len, push current_chunk
        if current_len + line_len > max_len and current_chunk:
            chunk_text = "".join(current_chunk)
            if in_code_block:
                # Close code block in current chunk
                chunk_text += "\n```"
            chunks.append(chunk_text)

            current_chunk = []
            current_len = 0
            if in_code_block:
                # Reopen code block in next chunk
                reopen = f"```{code_lang}\n" if code_lang else "```\n"
                current_chunk.append(reopen)
                current_len += len(reopen)

        # If a single line itself is longer than max_len (rare long word/data)
        if line_len > max_len:
            start = 0
            while start < line_len:
                sub = line[start:start + max_len]
                chunks.append(sub)
                start += max_len
            continue

        current_chunk.append(line)
        current_len += line_len

    if current_chunk:
        chunks.append("".join(current_chunk))

    return chunks


def send_msg(
    context: MessageContext,
    message: str = "Hello from nemo-bot-ng-backend",
    auto_escape: bool = False,
    reply: bool = False,
    *args,
    **kwargs,
) -> dict[str, Any]:
    """Send text message to Discord channel, auto-chunking if > 1950 characters."""
    channel_id = _resolve_target_channel(context)
    if not channel_id:
        return {"ok": False, "error": "Unable to resolve target channel"}

    endpoint = f"{DISCORD_API_ENDPOINT}/channels/{channel_id}/messages"
    chunks = _chunk_discord_message(message, max_len=1950)
    if not chunks:
        return {"ok": False, "error": "Empty message"}

    last_result: dict[str, Any] = {"ok": False}

    for idx, chunk in enumerate(chunks):
        payload: dict[str, Any] = {
            "content": chunk,
        }

        # Apply reply reference to first chunk only
        if idx == 0 and reply and context.message_id:
            payload["message_reference"] = {
                "message_id": str(context.message_id),
                "fail_if_not_exists": False,
            }

        r = _request_with_retry("POST", endpoint, json=payload)
        last_result = _safe_json(r)
        logger.debug("Discord send_msg chunk %d/%d result: %s", idx + 1, len(chunks), last_result.get("id") or last_result)

    return last_result


def send_photo(
    context: MessageContext,
    message: str = "",
    photo: str | Path = "",
    auto_escape: bool = False,
    reply: bool = False,
    *args,
    **kwargs,
) -> dict[str, Any]:
    """Send an image to Discord channel with optional caption message."""
    channel_id = _resolve_target_channel(context)
    if not channel_id:
        return {"ok": False, "error": "Unable to resolve target channel"}

    endpoint = f"{DISCORD_API_ENDPOINT}/channels/{channel_id}/messages"
    
    # 1. URL string mode
    if isinstance(photo, str) and (photo.startswith("http://") or photo.startswith("https://")):
        payload: dict[str, Any] = {
            "content": message if message else "",
            "embeds": [
                {
                    "image": {"url": photo}
                }
            ]
        }
        if reply and context.message_id:
            payload["message_reference"] = {
                "message_id": str(context.message_id),
                "fail_if_not_exists": False,
            }
        r = _request_with_retry("POST", endpoint, json=payload)
        return _safe_json(r)

    # 2. Base64 or local file mode
    file_bytes: bytes = b""
    filename = "image.png"

    if isinstance(photo, str) and photo.startswith("base64://"):
        raw_b64 = photo[len("base64://"):]
        file_bytes = base64.b64decode(raw_b64)
    elif isinstance(photo, (str, Path)):
        p = Path(photo)
        if p.exists():
            filename = p.name
            file_bytes = p.read_bytes()
        else:
            logger.error("Photo file not found on disk: %s", photo)
            # Fallback to sending text message
            return send_msg(context, f"[图片缺失: {photo}]\n{message}", reply=reply)

    data_payload: dict[str, Any] = {}
    if message:
        data_payload["content"] = message
    if reply and context.message_id:
        data_payload["message_reference"] = {
            "message_id": str(context.message_id),
            "fail_if_not_exists": False,
        }

    files = {
        "files[0]": (filename, file_bytes),
    }

    # In Discord API, when sending multipart form, data payload goes to 'payload_json'
    import json
    form_data = {
        "payload_json": json.dumps(data_payload),
    }

    r = _request_with_retry("POST", endpoint, data=form_data, files=files)
    res = _safe_json(r)
    logger.debug("Discord send_photo result: %s", res.get("id") or res)
    return res


def send_voice(
    context: MessageContext,
    message: str = "",
    voice: str | Path = "",
    auto_escape: bool = False,
    reply: bool = False,
    *args,
    **kwargs,
) -> dict[str, Any]:
    """Send voice or audio file as attachment to Discord channel."""
    channel_id = _resolve_target_channel(context)
    if not channel_id:
        return {"ok": False, "error": "Unable to resolve target channel"}

    endpoint = f"{DISCORD_API_ENDPOINT}/channels/{channel_id}/messages"
    
    file_bytes: bytes = b""
    filename = "voice.ogg"

    if isinstance(voice, str) and (voice.startswith("http://") or voice.startswith("https://")):
        try:
            resp = requests.get(voice, timeout=10.0)
            if resp.status_code == 200:
                file_bytes = resp.content
                filename = voice.split("/")[-1].split("?")[0] or "voice.ogg"
        except Exception as e:
            logger.warning("Failed to download voice URL %s: %s", voice, e)

    elif isinstance(voice, str) and voice.startswith("base64://"):
        raw_b64 = voice[len("base64://"):]
        file_bytes = base64.b64decode(raw_b64)
    elif isinstance(voice, (str, Path)):
        p = Path(voice)
        if p.exists():
            filename = p.name
            file_bytes = p.read_bytes()

    if not file_bytes:
        return send_msg(context, f"[语音缺失]\n{message}", reply=reply)

    import json
    data_payload: dict[str, Any] = {}
    if message:
        data_payload["content"] = message
    if reply and context.message_id:
        data_payload["message_reference"] = {
            "message_id": str(context.message_id),
            "fail_if_not_exists": False,
        }

    form_data = {
        "payload_json": json.dumps(data_payload),
    }
    files = {
        "files[0]": (filename, file_bytes),
    }

    r = _request_with_retry("POST", endpoint, data=form_data, files=files)
    res = _safe_json(r)
    logger.debug("Discord send_voice result: %s", res.get("id") or res)
    return res


def withdraw(context: MessageContext, target_id: str) -> str:
    """Delete a message in the channel."""
    channel_id = _resolve_target_channel(context)
    if not channel_id:
        raise ValueError("Cannot resolve target channel for withdraw")

    endpoint = f"{DISCORD_API_ENDPOINT}/channels/{channel_id}/messages/{target_id}"
    r = _request_with_retry("DELETE", endpoint)
    if r.status_code in (200, 204):
        return "撤回成功"
    raise Exception(f"Discord API Error: {r.status_code} - {r.text}")


def pin(context: MessageContext, target_id: str) -> str:
    """Pin a message in the channel."""
    channel_id = _resolve_target_channel(context)
    if not channel_id:
        raise ValueError("Cannot resolve target channel for pin")

    endpoint = f"{DISCORD_API_ENDPOINT}/channels/{channel_id}/pins/{target_id}"
    r = _request_with_retry("PUT", endpoint)
    if r.status_code in (200, 204):
        return "置顶成功"
    raise Exception(f"Discord API Error: {r.status_code} - {r.text}")


def unpin(context: MessageContext, target_id: str) -> str:
    """Unpin a message in the channel."""
    channel_id = _resolve_target_channel(context)
    if not channel_id:
        raise ValueError("Cannot resolve target channel for unpin")

    endpoint = f"{DISCORD_API_ENDPOINT}/channels/{channel_id}/pins/{target_id}"
    r = _request_with_retry("DELETE", endpoint)
    if r.status_code in (200, 204):
        return "取消置顶成功"
    raise Exception(f"Discord API Error: {r.status_code} - {r.text}")
