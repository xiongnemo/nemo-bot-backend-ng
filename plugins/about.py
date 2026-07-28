"""
About Plugin
------------
Provides bot system information (migrated from frontend).
"""

import platform
from core.message import Message
from utilities import generic_exception_handler

_name = "关于本 Bot"
_command = ["about"]
_man = "用法: about\n介绍本 Bot 的系统信息。"
_tool_description = "获取 Bot 的环境、版本、和基本介绍信息。"
_enabled = 1

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    frontend = message.frontend
    text = (
        f"头像是卡比，似乎和另外一个 bot 是镜像，但可惜它已经寄了\n"
        f"==\n"
        f"nemo-bot ({frontend} via backend-ng) by nemo, 0.2.0\n"
        f"由 Python {platform.python_version()} 所执行, \n"
        f"运行在节点 {platform.node()}, \n"
        f"由 {platform.platform()} 所承载。\n"
        f"=="
    )
    message.reply(text)
