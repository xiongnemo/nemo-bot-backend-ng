"""
ToolExecutor — routes tool calls to either the process pool (for plugins)
or runs them locally (for builtins).
"""

from __future__ import annotations

import logging
from typing import Any

from core.message import Message
from runtime.executor import Executor
from runtime.sender import Sender
from store.state_store import StateStore
from .tool_registry import ToolRegistry

logger = logging.getLogger(__name__)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, executor: Executor, state_store: StateStore, sender: Sender, scheduler=None):
        self.registry = registry
        self.executor = executor
        self.state_store = state_store
        self.sender = sender
        self.scheduler = scheduler

    def execute(self, tool_name: str, arguments: dict, message: Message) -> dict[str, Any]:
        """
        Execute a tool and return an observation dict for the LLM.
        """
        entry = self.registry.get_tool(tool_name)
        if not entry:
            return {"error": f"Unknown tool: {tool_name}"}

        # Permission check happens here too, just in case
        if entry.requires_superuser:
            from config import is_superuser
            if not is_superuser(message.frontend, message.context.user_id):
                logger.warning(
                    "User %s attempted to use superuser tool %s",
                    message.context.user_id, tool_name
                )
                return {"error": "Permission denied: superuser only"}

        logger.info("Executing tool: %s with args: %s", tool_name, arguments)

        if entry.is_plugin:
            return self._execute_plugin(entry.plugin_name, arguments, message, entry)
        else:
            return self._execute_builtin(entry, arguments, message)

    def _execute_builtin(self, entry, arguments: dict, message: Message) -> dict:
        try:
            result = entry.builtin_executor(arguments, message, self.sender)
            import json
            res_str = json.dumps(result, ensure_ascii=False)
            logger.info("Tool %s succeeded with result: %s", entry.definition.name, res_str[:200] + ("..." if len(res_str) > 200 else ""))
            return result
        except Exception as e:
            logger.exception("Builtin tool %s failed", entry.definition.name)
            return {"error": str(e)}

    def _execute_plugin(self, plugin_name: str, arguments: dict, message: Message, entry: ToolEntry) -> dict:
        import json
        
        # Check if this is a modern plugin with custom parameters or a legacy one
        props = entry.definition.parameters.get("properties", {})
        if list(props.keys()) == ["query"]:
            # Legacy: pass just the query string
            query_str = str(arguments.get("query", ""))
        else:
            # Modern: pass the full arguments dict as a JSON string
            query_str = json.dumps(arguments, ensure_ascii=False)
        
        # Prepare the message dict
        msg_dict = message.to_dict()
        msg_dict["request"]["args"] = query_str
        msg_dict["request"]["command"] = plugin_name
        
        config = self.state_store.get_plugin_config(plugin_name)
        
        from config import backend_config
        plugin_timeout = float(backend_config.get("llm", {}).get("timeout", 120.0))
        
        # Sync call to the process pool
        result = self.executor.run_plugin_sync(
            message_dict=msg_dict,
            plugin_name=plugin_name,
            plugin_config=config,
            timeout=plugin_timeout,
        )
        
        if result.get("ok"):
            # Update config if the plugin mutated it
            new_config = result.get("config")
            if new_config and new_config != config:
                self.state_store.set_plugin_config(plugin_name, new_config)
                
            # Extract text output
            actions = result.get("actions", [])
            text_output = "\n".join(a.get("text", "") for a in actions if a.get("text"))
            
            photo_urls = [a.get("photo_url") for a in actions if a.get("photo_url")]
            voice_urls = [a.get("voice_url") for a in actions if a.get("voice_url")]
            
            obs = {
                "text": text_output or "(插件无文本输出)",
                "payload": result.get("payload"),
                "ok": True,
            }
            if photo_urls: obs["photo_urls"] = photo_urls
            if voice_urls: obs["voice_urls"] = voice_urls
            
            # Pack raw actions so the runner can forward them to the user
            obs["_raw_actions"] = actions
            logger.info(f"Tool {plugin_name} succeeded with result: {obs['text']}")
            return obs
        else:
            logger.warning(f"Tool {plugin_name} failed: {result.get('error')}")
            return {
                "ok": False,
                "error": result.get("error", "Unknown error in plugin"),
            }
