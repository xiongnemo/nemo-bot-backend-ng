"""
Superuser Tools — High-privilege tools only available to superusers.
"""

from __future__ import annotations

import platform
import subprocess
from typing import Any

from core.message import Message
from nemollm.types import ToolDefinition
from store.state_store import StateStore

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
