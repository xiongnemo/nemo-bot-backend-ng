"""
Superuser Tools — High-privilege tools only available to superusers.
"""

from __future__ import annotations

import os
import logging
import platform
import subprocess
from typing import Any

from core.message import Message
from nemollm.types import ToolDefinition
from store.state_store import StateStore
from config import is_superuser

logger = logging.getLogger(__name__)

# 1. Shell Execution
SHELL_DEF = ToolDefinition(
    name="shell",
    description="在服务器上执行 shell 命令。仅限超级用户使用。返回标准输出和错误。",
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "要执行的 shell 命令"},
        },
        "required": ["command"],
    },
)

def shell_executor(args: dict, msg: Message) -> dict:
    cmd = args.get("command", "")
    if not cmd:
        return {"error": "No command provided"}
        
    try:
        # Use bash on Unix, direct execution on Windows
        is_windows = platform.system() == "Windows"
        exe_args = cmd if is_windows else ["bash", "-c", cmd]
        
        result = subprocess.run(
            exe_args,
            capture_output=True,
            timeout=30,
            shell=is_windows,
        )
        
        def decode_bytes(b: bytes) -> str:
            if not b: return ""
            try:
                return b.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    return b.decode("gbk")
                except UnicodeDecodeError:
                    return b.decode("utf-8", errors="replace")
                    
        stdout_str = decode_bytes(result.stdout)
        stderr_str = decode_bytes(result.stderr)

        return {
            "stdout": stdout_str[:4000],  # truncate to prevent overwhelming LLM
            "stderr": stderr_str[:2000],
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"error": "Command timed out after 30 seconds."}
    except Exception as e:
        return {"error": str(e)}


# 2. Config Management
CONFIG_DEF = ToolDefinition(
    name="config",
    description="读写机器人配置、插件状态、alias等。仅限超级用户使用。",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["get", "set", "list", "delete"],
                "description": "操作类型"
            },
            "namespace": {
                "type": "string",
                "description": "配置命名空间，例如 'plugin_config', 'alias', 'scheduler'"
            },
            "scope": {
                "type": "string",
                "description": "作用域，默认为 'global'。如果是特定插件的配置可以传入插件名",
                "default": "global"
            },
            "key": {"type": "string", "description": "配置键名"},
            "value": {"type": "string", "description": "配置值（仅 action=set 时需要）"},
        },
        "required": ["action", "namespace"],
    },
)

def config_executor(args: dict, msg: Message, store: StateStore) -> dict:
    action = args.get("action")
    ns = args.get("namespace", "")
    scope = args.get("scope", "global")
    key = args.get("key", "")
    
    if action == "list":
        return {"keys": store.list_keys(ns, scope)}
        
    if not key:
        return {"error": "Key is required for get/set/delete"}
        
    if action == "get":
        val = store.get(ns, scope, key)
        return {"key": key, "value": val}
    elif action == "set":
        if "value" not in args:
            return {"error": "Value is required for set"}
        store.set(ns, scope, key, args["value"])
        return {"status": "ok", "key": key}
    elif action == "delete":
        store.delete(ns, scope, key)
        return {"status": "deleted", "key": key}
        
    return {"error": f"Unknown action: {action}"}

# 3. ACL Management
MANAGE_ACL_DEF = ToolDefinition(
    name="manage_acl",
    description="管理全局黑名单以及各个插件的白名单/黑名单。只有被你认定为危险、不友善，或者管理员明确要求拉黑的用户，你才可以使用 add_global_ban。注意：Superusers (超级管理员) 拥有最高权限，无视所有的 ACL 黑白名单拦截限制。",
    parameters={
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add_whitelist", "remove_whitelist", "add_blacklist", "remove_blacklist", "add_global_ban", "remove_global_ban", "list_bans", "list_plugin_acl"],
                "description": "要执行的操作类型"
            },
            "target_type": {
                "type": "string",
                "enum": ["user", "group"],
                "description": "目标类型（list操作可选）"
            },
            "target_id": {
                "type": "string",
                "description": "目标 ID（list操作可选）"
            },
            "plugin_name": {
                "type": "string",
                "description": "插件名称。仅在管理插件 ACL 时需要提供，全局操作无需提供。"
            }
        },
        "required": ["action"],
    },
)

def manage_acl_executor(args: dict, msg: Message, state_store: StateStore) -> dict:
    action = args.get("action")
    target_type = args.get("target_type")
    target_id = args.get("target_id")
    plugin_name = args.get("plugin_name")
    
    target_key = f"{target_type}_{target_id}" if target_type and target_id else None
    
    if action == "list_bans":
        bans = state_store.get("acl", "global", "blacklist", default=[])
        return {"global_blacklist": bans}
        
    if action == "list_plugin_acl":
        if not plugin_name:
            return {"error": "Missing plugin_name for list_plugin_acl"}
        whitelist = state_store.get("acl", f"plugin_{plugin_name}", "whitelist", default=[])
        blacklist = state_store.get("acl", f"plugin_{plugin_name}", "blacklist", default=[])
        return {"plugin": plugin_name, "whitelist": whitelist, "blacklist": blacklist}
        
    if not target_key:
        return {"error": "target_type and target_id are required for this action."}
        
    if action in ["add_global_ban", "remove_global_ban"]:
        bans = state_store.get("acl", "global", "blacklist", default=[])
        if action == "add_global_ban":
            if target_key not in bans:
                bans.append(target_key)
        else:
            if target_key in bans:
                bans.remove(target_key)
        state_store.set("acl", "global", "blacklist", bans)
        return {"status": "success", "global_blacklist": bans}
        
    if not plugin_name:
        return {"error": "plugin_name is required for plugin ACL actions."}
        
    list_type = "whitelist" if "whitelist" in action else "blacklist"
    current_list = state_store.get("acl", f"plugin_{plugin_name}", list_type, default=[])
    
    if "add" in action:
        if target_key not in current_list:
            current_list.append(target_key)
    elif "remove" in action:
        if target_key in current_list:
            current_list.remove(target_key)
            
    state_store.set("acl", f"plugin_{plugin_name}", list_type, current_list)
    return {"status": "success", "plugin": plugin_name, list_type: current_list}

# Affinity Administration
ADMIN_AFFINITY_DEF = ToolDefinition(
    name="admin_affinity",
    description="【管理员】好感度管理：将指定用户的好感度设定为精确值（set），或彻底清零重置（reset，从零开始重新积累）。仅限超级用户使用。",
    parameters={
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["set", "reset"], "description": "set: 设定为指定分数；reset: 清空该用户全部好感度状态（分数/streak/里程碑/流水）"},
            "user_id": {"type": "string", "description": "目标用户 ID（QQ号等，若对方有 user_link 绑定请填主账号 ID）"},
            "score": {"type": "number", "description": "目标分数，仅 action=set 时需要，范围 -20 到 100"},
            "reason": {"type": "string", "description": "调整原因，会记入好感度流水"},
        },
        "required": ["action", "user_id"],
    },
)

def admin_affinity_executor(args: dict, msg: Message) -> dict:
    from runtime import context
    if context.affinity_store is None:
        return {"error": "好感度系统未启用。"}
    action = args.get("action")
    uid = str(args.get("user_id") or "").strip()
    if not uid:
        return {"error": "缺少 user_id。"}
    if action == "set":
        if args.get("score") is None:
            return {"error": "set 操作需要提供 score。"}
        r = context.affinity_store.set_score(
            uid, float(args["score"]),
            reason=args.get("reason") or "管理员设定",
            operator=str(msg.context.user_id),
        )
        return {"result": f"已将用户 {uid} 的好感度从 {r['old_score']} 设定为 {r['score']:.1f}（{r['level']}）。"}
    elif action == "reset":
        existed = context.affinity_store.reset(uid)
        return {"result": f"已重置用户 {uid} 的好感度状态，从零开始重新积累。" if existed
                else f"用户 {uid} 本来就没有好感度记录，无需重置。"}
    return {"error": f"未知 action: {action}"}


# 5. Document Reading (PDF, Word, Text)
READ_DOCUMENT_DEF = ToolDefinition(
    name="read_document",
    description=(
        "解析并读取用户发送或群聊中的 PDF、Word (.docx) 以及代码/文本文件的内容。\n"
        "仅限超级管理员使用（出于系统安全考量，非管理员无法使用此工具）。\n"
        "支持传入 query（文件名、关键词或文件ID），不提供则自动读取最新收到的文档。\n"
        "【回复要求】：调用本工具获取文档后，你必须在回答中对文档的核心内容、主旨与结论进行归纳汇报，严禁在获取文档后忽略其内容。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "文件名、文件关键词或文件数据库ID。如果不提供，默认读取最新接收到的文档文件。",
            },
            "max_pages": {
                "type": "integer",
                "description": "读取 PDF 时的最大页数（默认 20 页）。",
            },
        },
    },
)

def read_document_executor(args: dict, msg: Message) -> dict:
    import os
    from config import is_superuser
    if not is_superuser(msg.frontend, msg.context.user_id):
        return {"error": "权限拒绝：由于安全风险，非管理员无法处理未知文件（如 Word、PDF 等），需要让超级管理员来。"}

    from runtime import context
    fstore = getattr(context, "file_store", None)
    if not fstore:
        try:
            from store.database import Database
            from store.file_store import FileStore
            fstore = FileStore(Database())
            context.file_store = fstore
        except Exception:
            fstore = None

    query = str(args.get("query") or "").strip()
    max_pages = int(args.get("max_pages") or 20)

    target_file = None
    # 1. Direct message files
    current_files = getattr(msg.request, "files", [])
    if current_files and not query:
        target_file = current_files[-1]

    # 2. Query search
    if not target_file and query:
        target_file = fstore.find_file(query, group_id=msg.context.group_id, user_id=msg.context.user_id)

    # 3. Quoted reply
    if not target_file and msg.request.reply_to:
        reply_id = str(msg.request.reply_to.get("message_id", ""))
        rfiles = fstore.get_files_by_message(reply_id)
        if rfiles:
            target_file = rfiles[-1]

    # 4. Recent files in scope
    if not target_file:
        recent = fstore.get_recent_files(
            frontend=msg.frontend,
            group_id=msg.context.group_id,
            user_id=msg.context.user_id if not msg.context.group_id else "",
            limit=1,
            max_age_seconds=86400.0,
        )
        if recent:
            target_file = recent[0]

    logger.info(
        "[AgentTool:read_document] Requested by %s in %s (query: %r, max_pages: %d)",
        msg.context.user_id, msg.context.group_id or "DM", query, max_pages
    )

    if not target_file:
        logger.warning("[AgentTool:read_document] Target file not found for query %r", query)
        return {"error": "未找到可供解析的文档文件。请检查文件名或重新发送该文件。"}

    local_path = target_file.get("local_path", "")
    if not local_path or not os.path.exists(local_path):
        if fstore and hasattr(fstore, "ensure_local_file"):
            local_path = fstore.ensure_local_file(target_file)
            
    if not local_path or not os.path.exists(local_path):
        logger.warning("[AgentTool:read_document] File '%s' not present on disk", target_file.get("file_name"))
        return {"error": f"文件 '{target_file.get('file_name')}' 在本地磁盘不存在或尚未完成下载。"}

    from core.document_parser import parse_document
    parsed = parse_document(local_path, max_pages=max_pages)
    if not parsed.get("ok"):
        logger.warning("[AgentTool:read_document] Parse error for '%s': %s", target_file.get("file_name"), parsed.get("error"))
        return {"error": parsed.get("error", "解析失败")}

    raw_content = parsed.get("content", "")
    content_len = len(raw_content)
    MAX_TOOL_CONTENT = 35000
    if content_len > MAX_TOOL_CONTENT:
        head_chars = 25000
        tail_chars = 8000
        omitted = content_len - head_chars - tail_chars
        content = (
            raw_content[:head_chars]
            + f"\n\n... [为防止上下文超出限制，中间省略了 {omitted} 字符的详细数据/参考文献，保留核心分析与结尾结论] ...\n\n"
            + raw_content[-tail_chars:]
        )
    else:
        content = raw_content

    logger.info(
        "[AgentTool:read_document] Successfully parsed '%s' (%s, %d/%d pages, %d chars -> %d chars)",
        target_file.get("file_name"), parsed.get("type"), parsed.get("read_pages", 1),
        parsed.get("page_count", 1), content_len, len(content)
    )

    return {
        "file_name": target_file.get("file_name"),
        "file_type": parsed.get("type"),
        "page_count": parsed.get("page_count"),
        "read_pages": parsed.get("read_pages"),
        "content": content,
    }


def register_superuser_tools(registry, state_store: StateStore):
    """Register all superuser tools with injected dependencies."""
    
    registry.register_builtin(
        SHELL_DEF,
        lambda args, msg, sender: shell_executor(args, msg),
        requires_superuser=True,
    )
    
    registry.register_builtin(
        CONFIG_DEF,
        lambda args, msg, sender: config_executor(args, msg, state_store),
        requires_superuser=True,
    )
    
    registry.register_builtin(
        MANAGE_ACL_DEF,
        lambda args, msg, sender: manage_acl_executor(args, msg, state_store),
        requires_superuser=True,
    )

    registry.register_builtin(
        ADMIN_AFFINITY_DEF,
        lambda args, msg, sender: admin_affinity_executor(args, msg),
        requires_superuser=True,
    )

    registry.register_builtin(
        READ_DOCUMENT_DEF,
        lambda args, msg, sender: read_document_executor(args, msg),
        requires_superuser=True,
    )
