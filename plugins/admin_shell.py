"""
Admin Shell Plugin
------------------
Executes native OS commands on the host machine.
Extremely dangerous. Restricted to superusers only.
"""

import subprocess
import logging

from core.message import Message
from config import backend_config
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "超管终端 (Shell)"
_command = ["shell", "cmd"]
_man = "用法: shell <command>。仅限超级管理员使用。"
_tool_description = "在宿主机上执行原生 OS 命令行（Windows CMD/PowerShell）。仅当用户是超级管理员时才可以调用。返回命令的标准输出和错误流。"
_enabled = 1
_superuser_only = True

def is_superuser(message: Message) -> bool:
    frontend = message.frontend
    user_id = message.context.user_id
    if not frontend or not user_id:
        return False
        
    frontend_config = backend_config.get("message_backend", {}).get(frontend, {})
    superusers = frontend_config.get("superusers", [])
    
    return str(user_id) in superusers

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    if not is_superuser(message):
        message.reply("403: nemo: 权限拒绝！该工具仅限超级管理员使用。")
        return

    cmd = message.request.args.strip()
    if not cmd:
        message.reply("400: nemo: 请提供要执行的命令。例如：shell ping 127.0.0.1")
        return

    message.reply(f"正在执行: {cmd}")
    
    try:
        # Use shell=True to allow arbitrary shell syntax like pipelines
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            timeout=60 # Timeout to prevent hanging commands
        )
        
        import locale
        encoding = locale.getpreferredencoding()
        
        output = result.stdout.decode(encoding, errors="replace").strip() if result.stdout else ""
        error = result.stderr.decode(encoding, errors="replace").strip() if result.stderr else ""
        
        reply_text = f"【执行完毕 (Exit: {result.returncode})】\n"
        if output:
            reply_text += f"\n[STDOUT]:\n{output}"
        if error:
            reply_text += f"\n[STDERR]:\n{error}"
            
        if not output and not error:
            reply_text += "\n(无输出)"
            
        # Truncate if too long for messaging platforms
        if len(reply_text) > 3000:
            reply_text = reply_text[:3000] + "\n... (已截断)"
            
        message.reply(reply_text)
        
        # Populate payload for Agent
        message.payload = {
            "command": cmd,
            "exit_code": result.returncode,
            "stdout": output,
            "stderr": error
        }
    except subprocess.TimeoutExpired:
        message.reply("504: nemo: 命令执行超时 (60s)")
    except Exception as e:
        message.reply(f"500: nemo: 命令执行失败: {str(e)}")

