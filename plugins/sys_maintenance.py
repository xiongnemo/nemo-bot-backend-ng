"""
System Maintenance & Feature Switch Management Plugin
------------------------------------------------------
Allows superusers to control global and granular runtime switches:
- Master Agent switch
- Chat conversational Agent (with customizable maintenance notification)
- Background vision image tagging (silently skips when disabled)
- Scheduled background cron jobs (silently skips when disabled)
- Maintenance test whitelist for admin group exemptions
"""

import logging
from typing import Any

from core.message import Message
from config import is_superuser
from utilities import generic_exception_handler

logger = logging.getLogger(__name__)

# ===========================
# Mandatory Plugin Attributes
# ===========================
_name = "系统维护与开关管理"
_command = ["maintenance", "维护", "维护模式", "switch", "开关", "sys_ctrl", "系统管理"]
_man = """系统组件维护模式与功能开关管理（仅限超级管理员）。
用法:
  /maintenance status                     - 查看当前系统各开关与维护状态
  /maintenance on [维护理由]              - 开启全系统维护（一键停用所有 Agent，可附带自定义理由）
  /maintenance off                        - 关闭全系统维护（恢复所有 Agent 功能）
  
  /switch chat <on|off>                   - 仅开启/关闭聊天 Agent（关闭后显式调用将提示维护理由）
  /switch tagging <on|off>                - 仅开启/关闭后台图片视觉打标（关闭后静默跳过）
  /switch jobs <on|off>                   - 仅开启/关闭后台定时任务（关闭后静默跳过）
  
  /maintenance reason <文字内容>          - 更新显式调用 Agent 时的维护提示语
  /maintenance test                       - 预览显式调用 Agent 时用户看到的维护文案
  /maintenance whitelist <add|del|list> [群号] - 管理维护模式豁免测试白名单群
"""
_tool_description = "系统维护与功能开关管理。允许超级管理员控制聊天Agent、后台识图标注、定时任务的启闭及维护文案设置。"
_enabled = 1
_superuser_only = True
_main_process_only = True


@generic_exception_handler
def bot_execute(message: Message, config: dict):
    from runtime import context

    # 1. Superuser Permission Check
    frontend = message.frontend
    user_id = message.context.user_id if message.context else ""
    if not is_superuser(frontend, user_id):
        message.reply("403: nemo: 权限拒绝！该操作仅限超级管理员使用。")
        return

    sys_ctrl = getattr(context, "system_control", None)
    if sys_ctrl is None:
        from store.database import Database
        from store.state_store import StateStore
        from store.system_control import SystemControl
        db = getattr(context, "db", None) or Database()
        state_store = getattr(context, "state_store", None) or StateStore(db)
        sys_ctrl = SystemControl(state_store)
        context.system_control = sys_ctrl

    raw_args = (message.request.args or "").strip()
    parts = raw_args.split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "status"
    sub_args = parts[1].strip() if len(parts) > 1 else ""

    # Allow /maintenance switch chat off or /switch chat off
    if subcmd in ("switch", "开关"):
        parts = sub_args.split(maxsplit=1)
        subcmd = parts[0].lower() if parts else "status"
        sub_args = parts[1].strip() if len(parts) > 1 else ""

    # Normalize subcommands
    if subcmd in ("status", "状态", "查看", "info", "list"):
        st = sys_ctrl.get_status()
        master_str = "🟢 正常运行 (ONLINE)" if st["master_agent"] else "🔴 维护中 (MAINTENANCE)"
        chat_str = "🟢 开启" if st["chat"] else "🔴 已关闭"
        tagging_str = "🟢 开启" if st["tagging"] else "🔴 已关闭 (静默跳过)"
        jobs_str = "🟢 开启" if st["jobs"] else "🔴 已暂停 (静默跳过)"
        wl_str = ", ".join(st["whitelist_groups"]) if st["whitelist_groups"] else "无（全局生效）"

        msg_lines = [
            "🛡️ Nemo-bot 系统运维与功能开关状态:",
            "──────────────────────────",
            f"• 🌐 Agent 总控开关: {master_str}",
            f"• 💬 聊天 Agent: {chat_str}",
            f"• 🖼️ 后台图片视觉打标: {tagging_str}",
            f"• ⏰ 后台定时任务: {jobs_str}",
            "──────────────────────────",
            f"📢 当前维护提示理由:\n「{st['reason']}」",
            "──────────────────────────",
            f"🏷️ 豁免测试白名单群: {wl_str}",
            "💡 提示: /maintenance on [理由] 一键开启维护；/switch <chat|tagging|jobs> <on|off> 单项开关。"
        ]
        message.reply("\n".join(msg_lines))
        return

    elif subcmd in ("on", "开启", "enable", "维护开启"):
        reason = sub_args if sub_args else None
        sys_ctrl.set_maintenance_mode(True, reason=reason)
        active_reason = sys_ctrl.get_maintenance_reason()
        reply_lines = [
            "🚧 系统维护模式已【全面开启】！",
            "• 💬 聊天 Agent: 🔴 已停用（显式调用将提示维护理由）",
            "• 🖼️ 后台图片打标: 🔴 已停用（静默跳过）",
            "• ⏰ 后台定时任务: 🔴 已暂停（静默跳过）",
            "──────────────────────────",
            f"📢 维护回复已设为:\n「{active_reason}」"
        ]
        message.reply("\n".join(reply_lines))
        return

    elif subcmd in ("off", "关闭", "disable", "恢复", "恢复正常"):
        sys_ctrl.set_maintenance_mode(False)
        message.reply("✅ 系统维护模式已【解除】！\n• 聊天 Agent、后台图片打标与定时任务已全量恢复就绪。")
        return

    elif subcmd in ("reason", "理由", "文案", "提示"):
        if sub_args:
            updated = sys_ctrl.set_maintenance_reason(sub_args)
            message.reply(f"📢 维护提示理由已更新为:\n「{updated}」")
        else:
            current = sys_ctrl.get_maintenance_reason()
            message.reply(f"📢 当前维护提示理由为:\n「{current}」\n(使用 /maintenance reason <新文字> 进行修改)")
        return

    elif subcmd in ("test", "测试", "preview", "预览"):
        reason = sys_ctrl.get_maintenance_reason()
        message.reply(f"🤖 [维护模式回复预览]\n{reason}")
        return

    elif subcmd in ("reset", "重置", "恢复默认"):
        from store.system_control import DEFAULT_MAINTENANCE_REASON
        sys_ctrl.set_maintenance_reason(DEFAULT_MAINTENANCE_REASON)
        message.reply(f"📢 维护提示理由已重置为系统默认:\n「{DEFAULT_MAINTENANCE_REASON}」")
        return

    # Granular component switches
    elif subcmd in ("all", "agent", "master", "总控"):
        action = sub_args.lower()
        if action in ("on", "1", "true", "开启", "开"):
            sys_ctrl.set_component_switch("master", True)
            message.reply("🌐 Agent 总控开关已【开启】。")
        elif action in ("off", "0", "false", "关闭", "关"):
            sys_ctrl.set_component_switch("master", False)
            message.reply("🌐 Agent 总控开关已【关闭】（所有 Agent 衍生功能均进入暂停状态）。")
        else:
            cur = sys_ctrl.is_master_agent_enabled()
            message.reply(f"🌐 Agent 总控开关当前状态: {'🟢 开启' if cur else '🔴 关闭'}\n用法: /switch master <on|off>")
        return

    elif subcmd in ("chat", "agent_chat", "对话", "聊天"):
        action = sub_args.lower()
        if action in ("on", "1", "true", "开启", "开"):
            sys_ctrl.set_component_switch("chat", True)
            message.reply("💬 聊天 Agent 功能已【开启】。")
        elif action in ("off", "0", "false", "关闭", "关"):
            sys_ctrl.set_component_switch("chat", False)
            active_reason = sys_ctrl.get_maintenance_reason()
            message.reply(f"💬 聊天 Agent 功能已【关闭】。\n（普通用户显式 @ 或私聊将回复: 「{active_reason}」）")
        else:
            cur = sys_ctrl.is_agent_chat_enabled()
            message.reply(f"💬 聊天 Agent 当前状态: {'🟢 开启' if cur else '🔴 关闭'}\n用法: /switch chat <on|off>")
        return

    elif subcmd in ("tagging", "vision", "vision_tagger", "打标", "识图"):
        action = sub_args.lower()
        if action in ("on", "1", "true", "开启", "开"):
            sys_ctrl.set_component_switch("tagging", True)
            message.reply("🖼️ 后台图片视觉打标已【开启】。")
        elif action in ("off", "0", "false", "关闭", "关"):
            sys_ctrl.set_component_switch("tagging", False)
            message.reply("🖼️ 后台图片视觉打标已【关闭】（收到图片时将静默跳过）。")
        else:
            cur = sys_ctrl.is_tagging_enabled()
            message.reply(f"🖼️ 后台图片视觉打标当前状态: {'🟢 开启' if cur else '🔴 关闭'}\n用法: /switch tagging <on|off>")
        return

    elif subcmd in ("jobs", "job", "cron", "scheduler", "定时任务", "计划任务"):
        action = sub_args.lower()
        if action in ("on", "1", "true", "开启", "开"):
            sys_ctrl.set_component_switch("jobs", True)
            message.reply("⏰ 后台定时任务已【开启】。")
        elif action in ("off", "0", "false", "关闭", "关"):
            sys_ctrl.set_component_switch("jobs", False)
            message.reply("⏰ 后台定时任务已【关闭】（所有周期计划任务将静默跳过执行）。")
        else:
            cur = sys_ctrl.is_jobs_enabled()
            message.reply(f"⏰ 后台定时任务当前状态: {'🟢 开启' if cur else '🔴 关闭'}\n用法: /switch jobs <on|off>")
        return

    elif subcmd in ("whitelist", "白名单", "wl"):
        wl_parts = sub_args.split(maxsplit=1)
        wl_act = wl_parts[0].lower() if wl_parts else "list"
        wl_target = wl_parts[1].strip() if len(wl_parts) > 1 else ""

        if wl_act in ("add", "添加", "+"):
            if not wl_target:
                message.reply("400: nemo: 请提供要加入豁免白名单的群号，例如: /maintenance whitelist add 903421726")
                return
            current_list = sys_ctrl.add_whitelist_group(wl_target)
            message.reply(f"🏷️ 已将群号 {wl_target} 加入维护豁免白名单！当前白名单群: {', '.join(current_list)}")
        elif wl_act in ("del", "delete", "remove", "删除", "-"):
            if not wl_target:
                message.reply("400: nemo: 请提供要移出豁免白名单的群号，例如: /maintenance whitelist del 903421726")
                return
            current_list = sys_ctrl.remove_whitelist_group(wl_target)
            message.reply(f"🏷️ 已将群号 {wl_target} 移出维护豁免白名单！当前白名单群: {', '.join(current_list) if current_list else '无'}")
        elif wl_act in ("clear", "清空", "reset"):
            sys_ctrl.clear_whitelist_groups()
            message.reply("🏷️ 维护豁免白名单已清空。")
        else:
            groups = sys_ctrl.get_whitelist_groups()
            message.reply(f"🏷️ 当前维护豁免白名单群列表: {', '.join(groups) if groups else '无'}\n用法: /maintenance whitelist <add|del|clear> [群号]")
        return

    else:
        message.reply("400: nemo: 未知的管理指令参数，输入 /man maintenance 查看完整操作手册。")
