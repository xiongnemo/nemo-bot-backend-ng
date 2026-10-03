"""
SystemControl — System runtime switches and maintenance state management.
Persisted in StateStore under namespace="system_control", scope="global".
"""

import logging
from typing import Any

from store.state_store import StateStore

logger = logging.getLogger(__name__)

DEFAULT_MAINTENANCE_REASON = "nemo 的 infra 将在近日进行维护，暂时下线 agent 功能"


class SystemControl:
    NAMESPACE = "system_control"
    SCOPE = "global"

    def __init__(self, state_store: StateStore | None = None):
        self.state_store = state_store

    def _get(self, key: str, default: Any = None) -> Any:
        if not self.state_store:
            return default
        try:
            return self.state_store.get(self.NAMESPACE, self.SCOPE, key, default=default)
        except Exception as e:
            logger.warning("Failed to read system_control state '%s': %s", key, e)
            return default

    def _set(self, key: str, value: Any) -> None:
        if self.state_store:
            try:
                self.state_store.set(self.NAMESPACE, self.SCOPE, key, value)
            except Exception as e:
                logger.error("Failed to write system_control state '%s': %s", key, e)

    # ------------------------------------------------------------------
    # Status & Inspection
    # ------------------------------------------------------------------

    def is_master_agent_enabled(self) -> bool:
        """Global master switch for all agent capabilities."""
        return bool(self._get("agent_enabled", True))

    def is_agent_chat_enabled(self) -> bool:
        """Whether conversational agent (chat with LLM) is enabled."""
        if not self.is_master_agent_enabled():
            return False
        return bool(self._get("chat_enabled", True))

    def is_tagging_enabled(self) -> bool:
        """Whether background vision image tagging is enabled."""
        if not self.is_master_agent_enabled():
            return False
        return bool(self._get("tagging_enabled", True))

    def is_jobs_enabled(self) -> bool:
        """Whether scheduled background jobs (reflection, exploration, crons) are enabled."""
        if not self.is_master_agent_enabled():
            return False
        return bool(self._get("jobs_enabled", True))

    def is_group_whitelisted(self, group_id: str | int | None) -> bool:
        """Check if group_id is in maintenance exemption whitelist."""
        if not group_id:
            return False
        whitelist = self.get_whitelist_groups()
        return str(group_id).strip() in whitelist

    def get_whitelist_groups(self) -> list[str]:
        val = self._get("whitelist_groups", [])
        if isinstance(val, list):
            return [str(g).strip() for g in val if str(g).strip()]
        return []

    def add_whitelist_group(self, group_id: str | int) -> list[str]:
        gid = str(group_id).strip()
        groups = self.get_whitelist_groups()
        if gid and gid not in groups:
            groups.append(gid)
            self._set("whitelist_groups", groups)
            logger.info("[SystemControl] Group %s added to maintenance whitelist", gid)
        return groups

    def remove_whitelist_group(self, group_id: str | int) -> list[str]:
        gid = str(group_id).strip()
        groups = [g for g in self.get_whitelist_groups() if g != gid]
        self._set("whitelist_groups", groups)
        logger.info("[SystemControl] Group %s removed from maintenance whitelist", gid)
        return groups

    def clear_whitelist_groups(self) -> list[str]:
        self._set("whitelist_groups", [])
        logger.info("[SystemControl] Maintenance whitelist cleared")
        return []

    def get_maintenance_reason(self) -> str:
        """Get current maintenance notification text."""
        val = self._get("maintenance_reason", DEFAULT_MAINTENANCE_REASON)
        if isinstance(val, str) and val.strip():
            return val.strip()
        return DEFAULT_MAINTENANCE_REASON

    def set_maintenance_reason(self, reason: str) -> str:
        """Update maintenance notification text."""
        text = (reason or "").strip() or DEFAULT_MAINTENANCE_REASON
        self._set("maintenance_reason", text)
        logger.info("[SystemControl] Maintenance reason set: %r", text)
        return text

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def set_maintenance_mode(self, enabled: bool, reason: str | None = None) -> None:
        """
        Turn whole maintenance mode on/off:
        - When enabled (maintenance ON): all agent capabilities (chat, tagging, jobs) are suspended.
        - When disabled (maintenance OFF): all restored to active (True).
        """
        if enabled:
            self._set("agent_enabled", False)
            self._set("chat_enabled", False)
            self._set("tagging_enabled", False)
            self._set("jobs_enabled", False)
            if reason:
                self.set_maintenance_reason(reason)
            logger.info(
                "[SystemControl] Maintenance mode ENABLED (All agent features off). Reason: %s",
                self.get_maintenance_reason()
            )
        else:
            self._set("agent_enabled", True)
            self._set("chat_enabled", True)
            self._set("tagging_enabled", True)
            self._set("jobs_enabled", True)
            logger.info("[SystemControl] Maintenance mode DISABLED (All agent features restored).")

    def set_component_switch(self, component: str, enabled: bool) -> bool:
        """Toggle individual component switches."""
        comp = component.lower().strip()
        if comp in ("all", "agent", "master", "总控"):
            self._set("agent_enabled", enabled)
            logger.info("[SystemControl] Master agent switch set to %s", enabled)
            return True
        elif comp in ("chat", "agent_chat", "对话", "聊天"):
            self._set("chat_enabled", enabled)
            logger.info("[SystemControl] Chat agent switch set to %s", enabled)
            return True
        elif comp in ("tagging", "vision", "vision_tagger", "打标", "识图"):
            self._set("tagging_enabled", enabled)
            logger.info("[SystemControl] Vision tagging switch set to %s", enabled)
            return True
        elif comp in ("jobs", "job", "cron", "scheduler", "定时任务", "计划任务"):
            self._set("jobs_enabled", enabled)
            logger.info("[SystemControl] Scheduled jobs switch set to %s", enabled)
            return True
        return False

    def get_status(self) -> dict:
        """Get structured status summary."""
        return {
            "master_agent": self.is_master_agent_enabled(),
            "chat": self.is_agent_chat_enabled(),
            "tagging": self.is_tagging_enabled(),
            "jobs": self.is_jobs_enabled(),
            "reason": self.get_maintenance_reason(),
            "whitelist_groups": self.get_whitelist_groups(),
        }
