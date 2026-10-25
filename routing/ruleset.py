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

    def add_exact(self, cmd: str, plugin: str, case_sensitive: bool = False):
        def _match(msg: IngestMessage) -> RuleMatch | None:
            text = msg.full_text.strip()
            clean_text = text[1:].strip() if text.startswith(("/", "／")) else text
            is_match = (clean_text == cmd) if case_sensitive else (clean_text.lower() == cmd.lower())
            if is_match:
                return RuleMatch(plugin, "")
            return None
        self.rules.append(_match)

    def add_prefix(self, prefix: str, plugin: str, strip: bool = True):
        def _match(msg: IngestMessage) -> RuleMatch | None:
            text = msg.full_text.strip()
            # Support leading slash or fullwidth slash (e.g. /cmd or ／cmd)
            clean_text = text[1:].strip() if text.startswith(("/", "／")) else text
            for candidate in (text, clean_text):
                if candidate.startswith(prefix):
                    # Prevent accidental word-prefix matches when matching without space (strip=False).
                    # E.g. ASCII prefix 'ca' matching 'calc', or 'ping' matching 'pingpong'.
                    if not strip and prefix.isascii() and len(candidate) > len(prefix):
                        next_char = candidate[len(prefix)]
                        if next_char.isalnum() or next_char == "_":
                            continue
                    args = candidate[len(prefix):].strip() if strip else candidate[len(prefix):]
                    return RuleMatch(plugin, args)
            return None
        self.rules.append(_match)

    def add_suffix(self, suffix: str, plugin: str, strip: bool = True):
        def _match(msg: IngestMessage) -> RuleMatch | None:
            if msg.full_text.endswith(suffix):
                args = msg.full_text[:-len(suffix)].strip() if strip else msg.full_text[:-len(suffix)]
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
        import sys
        from plugins import get_loaded_plugins

        # 1. Superuser / Management commands (priority over auto-discovered)
        self.add_prefix("sudo ", "nemo")

        registered_commands = {"sudo"}

        # 2. Auto-discover from centrally loaded plugins
        loaded_plugins = get_loaded_plugins()
        for module_name, mod in loaded_plugins.items():
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

            exact_only = bool(getattr(mod, "_exact", False) or getattr(mod, "_exact_only", False))

            if isinstance(cmds, list):
                for cmd in cmds:
                    if cmd in registered_commands:
                        logger.error("FATAL: Duplicate command '%s' found in plugin '%s'. Exiting.", cmd, module_name)
                        sys.exit(1)
                    registered_commands.add(cmd)

                    if exact_only:
                        self.add_exact(cmd, module_name, case_sensitive=False)
                    else:
                        # Add rule with space first (so it strips the space from args)
                        self.add_prefix(f"{cmd} ", module_name, strip=True)
                        # Fallback rule without space
                        self.add_prefix(cmd, module_name, strip=False)

        logger.info("Loaded %d routing rules", len(self.rules))

    def reload(self) -> int:
        """Clear existing rules, re-scan plugins directory, and reload routing rules."""
        from plugins import get_loaded_plugins
        get_loaded_plugins(reload=True)
        self.rules = []
        self.load_defaults()
        return len(self.rules)
