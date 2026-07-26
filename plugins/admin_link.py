"""
Admin Link Plugin
-----------------
Allows an admin to link another platform's user ID to their current user ID.
This ensures memory and context are shared across platforms.
"""

import json
import logging

from config import backend_config, is_superuser, get_platform
from core.message import Message
from store.state_store import StateStore

logger = logging.getLogger(__name__)

_command = ["link"]
_name = "多平台身份绑定"
_man = "用法: link <目标平台> <目标ID>。例如: link telegram 361296026"
_tool_description = "将用户的其他账号（可以是跨平台的如 Telegram，也可以是同平台的其他小号）绑定到当前主身份上。这样用户在各个平台、各个小号之间的聊天记录和记忆就能无缝互通。"
_superuser_only = True
_parameters = {
    "type": "object",
    "properties": {
        "target_frontend": {
            "type": "string",
            "description": "目标平台的名称，比如 telegram, qq, console"
        },
        "target_id": {
            "type": "string",
            "description": "你在目标平台上的用户 ID"
        },
        "primary_frontend": {
            "type": "string",
            "description": "（仅帮他人绑定时使用）主平台的名称"
        },
        "primary_id": {
            "type": "string",
            "description": "（仅帮他人绑定时使用）主平台上的用户 ID"
        }
    },
    "required": ["target_frontend", "target_id"]
}
_enabled = 1
_superuser_only = True

def bot_execute(message: Message, config: dict) -> None:
    # Ensure superuser (though tool registry should already enforce this if _superuser_only is set, but this is a direct command)
    if not is_superuser(message.frontend, message.context.user_id):
        message.reply("Permission denied: You must be a superuser to use this command.")
        return

    try:
        args = json.loads(message.request.args)
        target_frontend = args.get("target_frontend")
        target_id = str(args.get("target_id"))
        primary_frontend = args.get("primary_frontend")
        primary_id_arg = args.get("primary_id")
    except json.JSONDecodeError:
        # Fallback to CLI command mode
        parts = message.request.args.strip().split()
        if len(parts) != 2:
            message.reply("参数错误。\n" + _man)
            return
        target_frontend = parts[0]
        target_id = parts[1]
        primary_frontend = None
        primary_id_arg = None

    if primary_frontend and primary_id_arg:
        primary_platform = get_platform(primary_frontend)
        primary_id = str(primary_id_arg)
    else:
        primary_platform = get_platform(message.frontend)
        primary_id = message.context.user_id

    from store.database import Database
    db = Database(backend_config.get("database", {}).get("path", "data/bot.db"))
    state_store = StateStore(db)

    # Normalize the frontends to platform names
    target_platform = get_platform(target_frontend)

    # We map `platform:user_id` to `primary_id`
    target_key = f"{target_platform}:{target_id}"
    
    # 1. Find what the target currently resolves to (its old primary)
    old_target_primary = state_store.get("user_link", "global", target_key, default=target_id)
    
    # 2. Merge the entire old cluster into the new primary_id to keep the tree completely flat
    all_links = state_store.list_all("user_link", "global")
    for k, v in all_links.items():
        if v == old_target_primary:
            state_store.set("user_link", "global", k, primary_id)
            
    # 3. Ensure the target_key itself is updated (in case it wasn't in all_links)
    state_store.set("user_link", "global", target_key, primary_id)

    # We also map the current platform's id to itself, just to be explicit
    current_key = f"{primary_platform}:{primary_id}"
    state_store.set("user_link", "global", current_key, primary_id)

    message.reply(f"已成功将 {target_key} 绑定至当前主身份: {primary_id}！")
