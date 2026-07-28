"""
Ruleset — deterministic routing rules ported from the old frontend.

Matches messages based on prefix, suffix, or custom lambdas.
Alias resolution is applied BEFORE matching.
"""

from __future__ import annotations

import logging
from typing import Callable, NamedTuple

from core.types import IngestMessage

logger = logging.getLogger(__name__)


class RuleMatch(NamedTuple):
    plugin: str
    args: str


class Ruleset:
    def __init__(self):
        self.rules: list = []

    def add_prefix(self, prefix: str, plugin: str, strip: bool = True):
        def _match(msg: IngestMessage) -> RuleMatch | None:
            if msg.full_text.startswith(prefix):
                args = msg.full_text[len(prefix):].strip() if strip else msg.full_text
                return RuleMatch(plugin, args)
            return None
        self.rules.append(_match)

    def add_suffix(self, suffix: str, plugin: str, strip: bool = True):
        def _match(msg: IngestMessage) -> RuleMatch | None:
            if msg.full_text.endswith(suffix):
                args = msg.full_text[:-len(suffix)].strip() if strip else msg.full_text
                return RuleMatch(plugin, args)
            return None
        self.rules.append(_match)

    def add_custom(self, matcher: Callable[[str], bool], plugin: str, stripper: Callable[[str], str]):
        def _match(msg: IngestMessage) -> RuleMatch | None:
            if matcher(msg.full_text):
                return RuleMatch(plugin, stripper(msg.full_text))
            return None
        self.rules.append(_match)

    def match(self, msg: IngestMessage) -> RuleMatch | None:
        """Find the first matching rule."""
        for rule in self.rules:
            result = rule(msg)
            if result:
                return result
        return None

    def load_defaults(self):
        """Populate standard plugins and auto-discover _command prefixes."""
        import importlib
        from plugins import plugin_names

        import sys
        
        # 1. Superuser / Management commands (priority over auto-discovered)
        self.add_prefix("sudo ", "nemo")
        
        registered_commands = {"sudo"}
        
        # 2. Auto-discover from plugins
        for module_name in plugin_names:
            try:
                mod = importlib.import_module(f"plugins.{module_name}")
            except Exception:
                logger.warning("Failed to import plugin module: %s", module_name, exc_info=True)
                continue
                
            # Strict validation for required attributes
            required_attrs = ["_name", "_command", "bot_execute"]
            missing = [attr for attr in required_attrs if not hasattr(mod, attr)]
            
            # Require either _man (for CLI) or _tool_description (for Agent internal tools)
            if not hasattr(mod, "_man") and not hasattr(mod, "_tool_description"):
                missing.append("_man or _tool_description")

            if missing:
                logger.error("FATAL: Plugin '%s' is missing required attributes: %s. Exiting.", module_name, missing)
                sys.exit(1)
                
            cmds = getattr(mod, "_command")
            if not cmds:
                logger.warning("Plugin '%s' has an empty _command list. It cannot be triggered via command mode.", module_name)
                continue
                
            if isinstance(cmds, list):
                for cmd in cmds:
                    if cmd in registered_commands:
                        logger.error("FATAL: Duplicate command '%s' found in plugin '%s'. Exiting.", cmd, module_name)
                        sys.exit(1)
                    registered_commands.add(cmd)
                    
                    # Add rule with space first (so it strips the space from args)
                    self.add_prefix(f"{cmd} ", module_name, strip=True)
                    # Fallback rule without space
                    self.add_prefix(cmd, module_name, strip=False)

        logger.info("Loaded %d routing rules", len(self.rules))
