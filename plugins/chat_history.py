"""
Chat History Plugin
-------------------
Allows the Agent to query recent raw messages from the database
or search for past messages via FTS5.
"""

import json
import logging
from typing import Any

from config import backend_config
from core.message import Message
from store.message_store import MessageStore

logger = logging.getLogger(__name__)

_command = ["chat_history"]
_name = "聊天记录检索"
_tool_description = "检索当前聊天上下文（群组或私聊）的历史消息记录。你可以获取最近的 N 条消息，或者使用关键词搜索过往聊天。"
_parameters = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": ["recent", "search", "time_range"],
            "description": "操作类型。recent: 获取最近的消息；search: 搜索过往消息；time_range: 按时间范围检索消息"
        },
        "query": {
            "type": "string",
            "description": "搜索关键词（仅当 action 为 search 时需要）"
        },
        "limit": {
            "type": "integer",
            "description": "返回的消息数量上限，默认 20，最大 50"
        },
        "start_time": {
            "type": "number",
            "description": "起始时间的时间戳（Unix 秒，支持小数）。仅当 action 为 time_range 时需要"
        },
        "end_time": {
            "type": "number",
            "description": "结束时间的时间戳（Unix 秒，支持小数）。仅当 action 为 time_range 时可选，不填默认为当前时间"
        }
    },
    "required": ["action"]
}
_enabled = 1

def bot_execute(message: Message, config: dict) -> None:
    from store.database import Database
    db = Database(backend_config.get("database", {}).get("path", "data/nemo.sqlite"))
    message_store = MessageStore(db)

    try:
        args = json.loads(message.request.args)
    except json.JSONDecodeError:
        message.reply("解析参数失败，需要 JSON 格式的参数。")
        return

    action = args.get("action")
    query = args.get("query", "")
    limit = args.get("limit")
    if limit is None:
        limit = 20
    limit = min(limit, 50)
    
    gid = message.context.group_id
    uid = message.context.user_id if not gid else ""

    if action == "recent":
        rows = message_store.recent(group_id=gid, user_id=uid, limit=limit)
    elif action == "search":
        if not query:
            message.reply("搜索操作需要提供 query 参数。")
            return
        rows = message_store.search(query=query, group_id=gid, limit=limit)
    elif action == "time_range":
        start_time = args.get("start_time")
        end_time = args.get("end_time")
        if start_time is None:
            message.reply("按时间范围检索需要提供 start_time 参数（Unix 时间戳）。")
            return
        rows = message_store.get_by_time_range(
            start_time=float(start_time),
            end_time=float(end_time) if end_time else None,
            group_id=gid,
            limit=limit
        )
    else:
        message.reply(f"未知的 action: {action}")
        return

    if not rows:
        message.reply("没有找到任何相关消息。")
        return
        
    import datetime
    
    resp = "找到以下消息记录：\n"
    for r in rows:
        # timestamp to readable time
        dt = datetime.datetime.fromtimestamp(r["timestamp"]).strftime('%Y-%m-%d %H:%M:%S')
        sender = r["user_name"] or r["user_id"]
        text = r["text"]
        resp += f"[{dt}] {sender}: {text}\n"
        
    message.reply(resp.strip())
