"""
Ping Plugin
-----------
Simple connectivity check.
"""

import time
from core.message import Message
from utilities import generic_exception_handler

_name = "连通性测试"
_command = ["ping", "zaima"]
_man = "用法: ping\n用于测试 Bot 是否在线。"
_tool_description = "检查 Bot 是否在线并返回 Pong 和大致延迟。"
_enabled = 1

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    args = message.request.args.strip()
    if args:
        message.reply(args)
    else:
        message.reply("+PONG")
