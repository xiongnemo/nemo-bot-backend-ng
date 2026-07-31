from core.message import Message
from utilities import generic_exception_handler
import logging
import shlex
from store.database import Database
from store.state_store import StateStore
from config import is_superuser

logger = logging.getLogger(__name__)

_name = "指令别名"
_command = ["alias"]
_man = "用法: alias [name='value']\n管理命令别名，支持完全的 POSIX 标准解析"
_tool_description = "查看、设置或删除系统别名映射。"
_enabled = 1

@generic_exception_handler
def bot_execute(message: Message, config: dict):
    if not is_superuser(message.frontend, message.context.user_id):
        raise ValueError("401: nemo: 只有超级用户可以管理 alias")

    args_str = message.request.args.strip()
    db = Database()
    state_store = StateStore(db)
    
    if not args_str:
        # list all aliases
        keys = state_store.list_keys("alias", "global")
        if not keys:
            message.reply("当前没有设置任何 alias。")
            return
        out = ["当前所有 alias 如下：", "---"]
        for k in keys:
            v = state_store.get("alias", "global", k)
            out.append(f"alias {k}='{v}'")
        message.reply("\n".join(out))
        return

    if args_str in ("rmall", "flushall", "flush"):
        keys = state_store.list_keys("alias", "global")
        for k in keys:
            state_store.delete("alias", "global", k)
        message.reply(f"已清空所有 {len(keys)} 个 alias。")
        return

    try:
        tokens = shlex.split(args_str)
    except ValueError as e:
        raise ValueError(f"400: nemo: 参数解析失败，请检查引号是否闭合 ({e})")

    out = []
    for token in tokens:
        if '=' in token:
            name, target = token.split('=', 1)
            if not name:
                continue
            if not target:
                state_store.delete("alias", "global", name)
                out.append(f"已删除 alias {name}")
            else:
                old_target = state_store.get("alias", "global", name)
                state_store.set("alias", "global", name, target)
                if old_target:
                    out.append(f"已设置 alias {name}='{target}' (替换了 '{old_target}')")
                else:
                    out.append(f"已设置 alias {name}='{target}'")
        else:
            v = state_store.get("alias", "global", token)
            if v:
                out.append(f"alias {token}='{v}'")
            else:
                out.append(f"bash: alias: {token}: 未找到")
                
    if out:
        message.reply("\n".join(out))
