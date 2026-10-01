"""
System Unified Hot-Reload Plugin
--------------------------------
Allows superusers to dynamically hot-reload plugins, routing rules,
Agent tool definitions, and character personas/lore without restarting backend.
"""

import os
import logging
from typing import Any

from core.message import Message
from config import is_superuser
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

_name = "系统统一热重载"
_command = ["reload", "热重载", "重载"]
_man = """系统组件统一热重载（仅限超级管理员）。
用法:
  /reload               - 一键热重载所有组件（插件路由、Agent工具、人格库与Lore）
  /reload plugins       - 重新扫描 plugins/ 目录，动态热挂载新增/修改的插件及路由规则
  /reload persona       - 热重载 personas/ 目录下所有人格设定及伴生 Lore 故事文件
  /reload rules         - 仅刷新主进程指令路由规则
"""
_tool_description = "系统组件统一热重载工具。允许超级管理员免重启动态更新插件、路由规则、Agent 工具库及角色人格库。"
_enabled = 1
_superuser_only = True


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    from runtime import context

    # 1. Permission check
    frontend = message.frontend
    user_id = message.context.user_id if message.context else ""
    if not is_superuser(frontend, user_id):
        message.reply("403: nemo: 权限拒绝！该操作仅限超级管理员使用。")
        return

    raw_args = (message.request.args or "").strip()
    subcmd = raw_args.lower() if raw_args else "all"

    # Normalize subcommands
    do_plugins = False
    do_persona = False
    do_rules = False

    if subcmd in ("all", "", "全部", "全", "-a", "--all"):
        do_plugins = True
        do_persona = True
        do_rules = True
    elif subcmd in ("plugin", "plugins", "插件", "指令"):
        do_plugins = True
        do_rules = True
    elif subcmd in ("persona", "personas", "人设", "角色", "人格", "lore"):
        do_persona = True
    elif subcmd in ("rule", "rules", "路由", "规则"):
        do_rules = True
    else:
        # Default fallback to all if unrecognized single argument
        do_plugins = True
        do_persona = True
        do_rules = True

    results = []

    # 1. Reload Persona Store
    if do_persona:
        persona_store = context.persona_store
        if persona_store is None:
            from store.persona_store import PersonaStore
            personas_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "personas")
            persona_store = PersonaStore(personas_dir, context.state_store)
            context.persona_store = persona_store

        try:
            count = persona_store.reload()
            results.append(f"• 🎀 人格角色库: 已重载 {count} 个角色文件与伴生 Lore")
        except Exception as e:
            logger.exception("Failed to reload persona store: %s", e)
            results.append(f"• 🎀 人格角色库: 重载失败 ({e})")

    # 2. Reload Routing Rules & Plugins
    if do_rules:
        ruleset = context.ruleset
        if ruleset is not None and hasattr(ruleset, "reload"):
            try:
                rule_count = ruleset.reload()
                results.append(f"• 🧩 插件路由规则: 已扫描并激活 {rule_count} 条路由规则")
            except Exception as e:
                logger.exception("Failed to reload ruleset: %s", e)
                results.append(f"• 🧩 插件路由规则: 重载失败 ({e})")
        else:
            results.append("• 🧩 插件路由规则: 运行时尚未挂载 ruleset 实例")

    # 3. Reload Agent Tool Registry
    if do_plugins:
        tool_reg = context.tool_registry
        if tool_reg is not None and hasattr(tool_reg, "reload_plugins"):
            try:
                tool_count = tool_reg.reload_plugins()
                results.append(f"• 🛠️ Agent 工具池: 已同步热加载 {tool_count} 个插件工具")
            except Exception as e:
                logger.exception("Failed to reload tool registry: %s", e)
                results.append(f"• 🛠️ Agent 工具池: 重载失败 ({e})")

    summary_text = "🔄 Nemo-bot 统一热重载完成:\n" + "\n".join(results)
    logger.info("Hot-reload completed by superuser %s (%s):\n%s", user_id, frontend, summary_text)
    message.reply(summary_text)
