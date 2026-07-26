"""
设置 Verbose Level Plugin
-------------------
允许用户动态调整 Agent 的观测消息数量
"""

import logging
from core.message import Message
from core.types import Action
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

# ===========================
# 强制性模块变量 (Required)
# ===========================
_name = "设置播报等级"
_command = ["verbose", "设置播报", "设置啰嗦程度"]
_man = "用法: /verbose <0|1|2>\n说明: 设置 Agent 执行任务时的啰嗦程度。\n0=静默(默认), 1=常规, 2=啰嗦(打印完整参数)"
_enabled = True

_tool_description = "设置 Agent 执行任务时的中间态信息详细程度（Verbose Level）。支持的级别：0=静默(安静/默认模式)，1=常规模式，2=啰嗦(详细打印完整参数)。通常在用户觉得消息太刷屏，或者要求提供更详细的执行过程时调用。注意：此工具仅控制执行过程中的调试信息输出，完全不影响最终发给用户的回答内容质量！"
_parameters = {
    "type": "object",
    "properties": {
        "level": {
            "type": "integer",
            "description": "要设置的 Verbose 级别：0, 1, 或 2。"
        }
    },
    "required": ["level"]
}

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    from store.database import Database
    from store.state_store import StateStore
    
    db = Database()
    state_store = StateStore(db)
    
    args_str = message.request.args.strip() if message.request.args else ""
    level_str = ""
    
    # Try parsing as JSON (LLM Tool call)
    if args_str.startswith("{"):
        import json
        try:
            data = json.loads(args_str)
            if "level" in data:
                level_str = str(data["level"])
        except json.JSONDecodeError:
            pass
            
    # Fallback to plain string (User command)
    if not level_str and args_str and not args_str.startswith("{"):
        level_str = args_str.split()[0]
        
    if not level_str:
        return [Action(kind="reply", text="400: nemo: 缺少 <level> 参数。用法: /verbose <0|1|2>")]
        
    try:
        level = int(level_str)
        if level not in (0, 1, 2):
            raise ValueError()
    except ValueError:
        return [Action(kind="reply", text="400: nemo: 级别必须是 0, 1 或 2。")]
        
    # Get scope_key
    from config import get_platform
    platform = get_platform(message.frontend)
    link_key = f"{platform}:{message.context.user_id}"
    primary_uid = state_store.get("user_link", "global", link_key, default=message.context.user_id)
    
    gid = message.context.group_id
    scope_key = f"agent:{message.frontend}:group:{gid}" if gid else f"agent:{message.frontend}:dm:{primary_uid}"
    
    # Set verbose_level
    state_store.set("agent", "verbose_level", scope_key, level)
    logger.info(f"User {message.context.user_id} set verbose_level to {level} for scope {scope_key}")
    
    desc = {0: "静默", 1: "常规", 2: "啰嗦"}[level]
    return [Action(kind="reply", text=f"[Nemo] 已将你的播报等级设置为 Level {level} ({desc})。")]
