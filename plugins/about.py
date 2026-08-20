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
_tool_description = "查询当前 Bot 程序的底层软件版本、Python运行环境和操作系统宿主机节点信息（非角色人设介绍）。仅在用户明确询问底层系统/版本/技术环境时调用。"
_enabled = 1

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    frontend = message.frontend
    frontend_info = getattr(message.context, "frontend_system_info", "")
    if not frontend_info:
        frontend_info = f"nemo-bot-frontend-qq ({frontend}) by nemo, 0.2.0"
        
    footnote = """
==
nemo-bot 以使用 Python 而不是 Java, NodeJS, Ruby, Perl, PhP, C+-#%^* 或者 Rust 编写而自豪。
This Nemo has nemo power."""
    text = (
        f"头像是卡比，似乎和另外一个 bot 是镜像，但可惜它已经寄了\n"
        f"==\n"
        f"{frontend_info}\n"
        f"==\n"
        f"nemo-bot-backend-ng by nemo, 0.2.0\n"
        f"由 Python {platform.python_version()} 所执行, \n"
        f"运行在节点 {platform.node()}, \n"
        f"由 {platform.platform()} 所承载。\n"
        f"=="
        f"{footnote}"
    )
    message.reply(text, photo_url="assets/marshmallow.png")
