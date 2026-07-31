from core.types import Message
from core.exceptions import RequestParsingError
from utilities import generic_exception_handler
import logging

logger = logging.getLogger(__name__)

_name = "指令别名"
_command = ["alias"]
_man = "用法: alias <add/del/list> [alias_name] [target_command]"
_tool_description = "管理命令别名"
_enabled = 1

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    # This is a placeholder for the alias functionality which was previously in the frontend.
    # The actual alias execution interceptor would likely be in `ruleset.py` or `router.py`.
    # This plugin just provides an interface to manage them in the StateStore.
    args = message.request.args.split()
    if not args:
        raise RequestParsingError(f"400: nemo: 请提供子命令，例如: alias list")
    
    action = args[0]
    # TODO: Implement StateStore integration for alias management
    message.reply(f"Alias management is currently under construction in the backend.")
