import logging
logger = logging.getLogger(__name__)

"""
Console Adapter for testing nemo-bot-backend-ng locally.
"""

import requests
from core.message_context import MessageContext
from config import backend_config

console_cfg = backend_config.get("message_backend", {}).get("console", {})
CLIENT_ENDPOINT = console_cfg.get("endpoint", "http://127.0.0.1:42165/receive")

def _send_to_client(context: MessageContext, content: str, reply: bool, photo_url: str = None):
    prefix = f"[Nemo -> {context.user_name or context.user_id}]:" if reply else "[Nemo]:"
    
    payload = {
        "text": f"\n{prefix}\n{content}\n",
        "message_id": getattr(context, 'message_id', None),
        "photo_url": photo_url
    }
    try:
        requests.post(CLIENT_ENDPOINT, json=payload, timeout=2)
    except Exception:
        # If client isn't listening, just fallback to server stdout
    logger.info(payload["text"])

def send_msg(
    context: MessageContext,
    message: str | list = "Hello",
    auto_escape: bool = False,
    reply: bool = False
):
    _send_to_client(context, str(message), reply)

def send_photo(
    context: MessageContext,
    message: str = "",
    auto_escape: bool = False,
    photo: str = "",
    reply: bool = False
):
    _send_to_client(context, message, reply, photo_url=photo)

def send_voice(
    context: MessageContext,
    message: str = "",
    auto_escape: bool = False,
    voice: str = "",
    reply: bool = False
):
    _send_to_client(context, f"[Voice: {voice}]\n{message}", reply)
