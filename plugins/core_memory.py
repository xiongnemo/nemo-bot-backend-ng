"""
Core Memory Plugin
------------------
Allows the Agent to proactively memorize, forget, or list long-term facts
about a user or a group. These facts are stored in StateStore and injected
into future system prompts.
"""

import json
import logging
from typing import Any

from config import backend_config, is_superuser
from core.message import Message
from store.state_store import StateStore
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_command = ["core_memory"]
_name = "核心记忆系统"
_tool_description = "管理长期记忆事实。你可以记录用户偏好、群组规则或任何值得长期记住的信息。当你认为某些信息对于未来对话有用时，主动调用此工具进行存取。"
_parameters = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["memorize", "forget", "list"],
            "description": "操作类型。memorize: 记录新事实；forget: 遗忘事实；list: 列出所有事实"
        },
        "target": {
            "type": "string",
            "enum": ["user", "group"],
            "description": "记忆目标。user: 针对当前用户；group: 针对当前群组"
        },
        "fact": {
            "type": "string",
            "description": "要记录的事实内容（仅 memorize 需要）"
        },
        "fact_index": {
            "type": "integer",
            "description": "要删除的事实索引，从0开始（仅 forget 需要，通过 list 查阅索引）"
        }
    },
    "required": ["action", "target"]
}
_enabled = 1

@generic_exception_handler
def bot_execute(message: Message, config: dict) -> None:
    from store.database import Database
    db = Database(backend_config.get("database", {}).get("path", "data/bot.db"))
    state_store = StateStore(db)

    try:
        args = json.loads(message.request.args)
    except json.JSONDecodeError:
        message.reply("解析参数失败，需要 JSON 格式的参数。")
        return

    action = args.get("action")
    target = args.get("target")

    if action in ["memorize", "forget"] and target == "group":
        if not is_superuser(message.frontend, message.context.user_id):
            message.reply("401: nemo: 权限不足！修改或遗忘群组公共记忆（group）属于管理员敏感操作，普通用户无权操作。")
            return

    if target == "group":
        if not message.context.group_id:
            message.reply("当前不在群组环境中，无法操作群组记忆。")
            return
        key = f"group_{message.context.group_id}"
    else:
        key = f"user_{message.context.user_id}"

    facts = state_store.get("memory", key, "facts", default=[])

    if action == "list":
        if not facts:
            message.reply(f"当前 {target} 没有任何长期记忆。")
            return
        resp = f"当前 {target} 记忆列表：\n"
        for i, f in enumerate(facts):
            resp += f"[{i}] {f}\n"
        message.reply(resp.strip())
        return

    elif action == "memorize":
        fact = args.get("fact")
        if not fact:
            message.reply("memorize 操作需要提供 fact 内容。")
            return
        if fact in facts:
            message.reply(f"事实 '{fact}' 已经存在，无需重复记录。")
            return
        facts.append(fact)
        state_store.set("memory", key, "facts", facts)
        message.reply(f"已成功永久记录关于 {target} 的事实：{fact}")
        return

    elif action == "forget":
        idx = args.get("fact_index")
        if idx is None or not isinstance(idx, int) or idx < 0 or idx >= len(facts):
            message.reply("无效的 fact_index。请先用 list 操作查看索引。")
            return
        removed = facts.pop(idx)
        state_store.set("memory", key, "facts", facts)
        message.reply(f"已成功遗忘关于 {target} 的事实：{removed}")
        return

    message.reply(f"未知的 action: {action}")
