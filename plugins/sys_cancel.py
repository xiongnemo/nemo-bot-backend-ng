"""
取消任务 Plugin
-------------------
允许用户强行取消一个正在执行的 Agent 任务
"""

import logging
from core.message import Message
from core.types import Action
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

# ===========================
# 强制性模块变量 (Required)
# ===========================
_name = "取消任务"
_command = ["cancel", "取消任务", "取消"]
_man = "用法: /cancel <run_id>\n说明: 强行中止正在运行的 Agent 任务。"
_enabled = True

_tool_description = "强行中止/取消正在后台运行的一个长时 Agent 任务。当你认为前一个任务卡死，或者用户要求中止先前的动作时调用。"
_parameters = {
    "type": "object",
    "properties": {
        "run_id": {
            "type": "string",
            "description": "要取消的任务的 6 位字母数字 Run ID。如果未提供，默认取消该用户上下文中最近的一次任务。"
        }
    },
    "required": []
}

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    from store.database import Database
    from store.state_store import StateStore
    
    db = Database()
    state_store = StateStore(db)

    args_str = message.request.args.strip() if message.request.args else ""
    run_id = ""
    
    # Try parsing as JSON (LLM Tool call)
    if args_str.startswith("{"):
        import json
        try:
            data = json.loads(args_str)
            run_id = data.get("run_id", "").strip()
        except json.JSONDecodeError:
            pass
            
    # Fallback to plain string (User command)
    if not run_id and args_str and not args_str.startswith("{"):
        run_id = args_str
        
    # If still no run_id, attempt to fetch the latest run_id from state_store
    if not run_id:
        from config import get_platform
        platform = get_platform(message.frontend)
        link_key = f"{platform}:{message.context.user_id}"
        primary_uid = state_store.get("user_link", "global", link_key, default=message.context.user_id)
        
        gid = message.context.group_id
        scope_key = f"agent:{message.frontend}:group:{gid}" if gid else f"agent:{message.frontend}:dm:{primary_uid}"
        run_id = state_store.get("agent", "latest_run_id", scope_key)
        
    if not run_id:
        return [Action(kind="reply", text="400: nemo: 缺少 <run_id> 参数，且未找到最近正在运行的任务。用法: /cancel <run_id>")]
        
    # 设置取消标记
    state_store.set("sys", "cancel", run_id, True)
    logger.info(f"User {message.context.user_id} requested cancellation for Run ID: {run_id}")
    
    return [Action(kind="reply", text=f"[Nemo] 已发送取消指令给任务 {run_id}。如果任务正处于卡死的网络请求中，可能会有延迟。")]
