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
    current_time = time.time()
    # If the frontend timestamp is reliable, calculate latency
    latency = current_time - message.timestamp if message.timestamp > 0 else 0
    
    if latency > 0 and latency < 86400:
        message.reply(f"pong! 通信链路延迟大约 {latency:.3f} 秒")
    else:
        message.reply("pong!")
