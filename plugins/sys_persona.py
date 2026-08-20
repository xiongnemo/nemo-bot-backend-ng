"""
人格切换与管理插件
------------------
允许用户/管理员查看、热重载以及一键切换当前会话的人格设定。
"""

import logging
from core.message import Message
from core.types import Action
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

# ===========================
# 强制性模块变量 (Required)
# ===========================
_name = "人格角色管理"
_command = ["persona", "角色", "切换人格", "切换角色", "人设"]
_man = "用法:\n/persona list - 查看所有角色及当前激活状态\n/persona switch <角色ID> - 切换当前会话角色\n/persona reset - 恢复当前会话为默认角色\n/persona reload - 热重载所有人格文件"
_enabled = True

_tool_description = "查看或切换当前群聊/私聊的人格角色设定。支持查看角色清单、一键切换到指定角色、恢复默认角色或热重载角色库。"
_parameters = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "description": "操作类型：'list'(查看列表), 'switch'(切换角色), 'reset'(恢复默认), 'reload'(热重载文件)",
            "enum": ["list", "switch", "reset", "reload"],
        },
        "persona_id": {
            "type": "string",
            "description": "要切换的目标角色 ID（当 action 为 'switch' 时必填）",
        },
    },
    "required": ["action"],
}


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    from runtime import context
    from store.database import Database
    from store.state_store import StateStore

    state_store = context.state_store
    if state_store is None:
        db = Database()
        state_store = StateStore(db)

    persona_store = context.persona_store
    if persona_store is None:
        from store.persona_store import PersonaStore
        import os
        personas_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "personas")
        persona_store = PersonaStore(personas_dir, state_store)

    gid = message.context.group_id
    uid = message.context.user_id
    scope_key = f"agent:{message.frontend}:group:{gid}" if gid else f"agent:{message.frontend}:dm:{uid}"

    args_str = (message.request.args or "").strip()
    action = "list"
    persona_id = ""

    # Try parsing as JSON (LLM tool call)
    if args_str.startswith("{"):
        import json
        try:
            data = json.loads(args_str)
            action = data.get("action", "list")
            persona_id = data.get("persona_id", "")
        except json.JSONDecodeError:
            pass
    elif args_str:
        parts = args_str.split()
        subcmd = parts[0].lower()
        if subcmd in ("list", "ls", "列表", "查看"):
            action = "list"
        elif subcmd in ("switch", "set", "use", "切换", "选择") and len(parts) > 1:
            action = "switch"
            persona_id = parts[1]
        elif subcmd in ("reset", "default", "重置", "恢复"):
            action = "reset"
        elif subcmd in ("reload", "refresh", "重载"):
            action = "reload"
        else:
            # If user just gave persona ID: /persona maid
            action = "switch"
            persona_id = parts[0]

    reply_text = ""
    # Handle actions
    if action == "reload":
        count = persona_store.reload()
        reply_text = f"[Nemo] 已成功热重载人格库，当前已加载 {count} 个角色文件。"

    elif action == "reset":
        ok, msg_text = persona_store.reset_active_persona(scope_key)
        reply_text = f"[Nemo] {msg_text}"

    elif action == "switch":
        if not persona_id:
            reply_text = "400: nemo: 缺少目标角色 ID。用法: /persona switch <角色ID>"
        else:
            ok, msg_text = persona_store.set_active_persona(scope_key, persona_id)
            if not ok:
                reply_text = f"404: nemo: {msg_text}"
            else:
                reply_text = f"[Nemo] {msg_text}"

    else:
        # Default action: list
        active = persona_store.get_active_persona(scope_key)
        all_personas = persona_store.list_personas()

        lines = ["【系统可用角色列表】"]
        for p in all_personas:
            cur_mark = " (★当前激活)" if p.id == active.id else ""
            def_mark = " [默认]" if p.is_default else ""
            lines.append(f"- {p.id}: {p.display_name}{def_mark}{cur_mark}\n  简介: {p.description}")

        lines.append(f"\n当前会话激活人格：「{active.display_name}」")
        lines.append("提示：可使用 /persona switch <ID> 快速切换。")
        reply_text = "\n".join(lines)

    message.reply(reply_text)
    return reply_text
