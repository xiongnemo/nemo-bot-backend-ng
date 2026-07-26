"""
ToolRegistry — manages available tools for the Agent.

Combines standard plugin adapters, builtin tools (chat history),
and superuser tools (shell, config).
Enforces permissions so only superusers see/use dangerous tools.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable, List

from core.message import Message
from nemollm.types import ToolDefinition

from config import is_superuser

logger = logging.getLogger(__name__)


@dataclass
class ToolEntry:
    definition: ToolDefinition
    is_plugin: bool = False
    plugin_name: str | None = None
    builtin_executor: Callable | None = None
    requires_superuser: bool = False


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolEntry] = {}

    def register_plugin(self, name: str, description: str, requires_superuser: bool = False, parameters: dict | None = None):
        """Register a legacy plugin as an LLM tool."""
        if parameters is None:
            # By default, plugins take a single string argument "query"
            parameters = {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查询内容或指令参数"},
                },
                "required": ["query"],
            }
        
        defn = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
        )
        self._tools[name] = ToolEntry(
            definition=defn,
            is_plugin=True,
            plugin_name=name,
            requires_superuser=requires_superuser,
        )

    def register_builtin(self, defn: ToolDefinition, executor: Callable, requires_superuser: bool = False):
        """Register a native Python function as a tool."""
        self._tools[defn.name] = ToolEntry(
            definition=defn,
            is_plugin=False,
            builtin_executor=executor,
            requires_superuser=requires_superuser,
        )

    def get_tool(self, name: str) -> ToolEntry | None:
        return self._tools.get(name)

    def get_tools_for_user(self, frontend: str, user_id: str) -> List[ToolDefinition]:
        """Return only the tools this user is allowed to see."""
        su = is_superuser(frontend, user_id)
        return [
            entry.definition
            for entry in self._tools.values()
            if not entry.requires_superuser or su
        ]

    def load_defaults(self):
        """Auto-discover plugins from the plugins/ directory and register them.

        Each plugin module can declare the following top-level attributes:
          _name            (str)  — Human-readable name (required for discovery)
          _man             (str)  — Human-readable manual / usage (for command mode)
          _tool_description (str) — LLM-optimized description (preferred for agent mode)
          _command         (list) — Command trigger words (for command mode)

        If _tool_description is absent, we synthesize one from _name + _man.
        Plugins without _name are skipped (not agent-compatible).
        """
        import importlib
        import re
        from plugins import plugin_names

        count = 0
        for module_name in plugin_names:
            try:
                mod = importlib.import_module(f"plugins.{module_name}")
            except Exception:
                logger.warning("Failed to import plugin module: %s", module_name, exc_info=True)
                continue

            # Skip modules that don't declare _name (not a proper plugin)
            if not hasattr(mod, "_name"):
                logger.debug("Skipping %s: no _name attribute", module_name)
                continue

            # Determine the description for the LLM
            if hasattr(mod, "_tool_description"):
                description = mod._tool_description
            else:
                # Synthesize from _name + _man, stripping {0} placeholders
                description = getattr(mod, "_name", module_name)
                man = getattr(mod, "_man", "")
                if man:
                    # Remove {0} placeholder and extra whitespace
                    clean_man = re.sub(r"\{0\}\s*", "", man).strip()
                    description = f"{description}。{clean_man}"

            parameters = getattr(mod, "_parameters", None)
            requires_superuser = getattr(mod, "_superuser_only", False)
            self.register_plugin(module_name, description, parameters=parameters, requires_superuser=requires_superuser)
            count += 1

        logger.info("Auto-discovered and registered %d plugin tools", count)

