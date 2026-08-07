import os
import yaml
import logging
from typing import Any

logger = logging.getLogger(__name__)

_config_path = os.path.join(os.path.dirname(__file__), "config.yml")

if os.path.exists(_config_path):
    with open(_config_path, "r", encoding="utf-8") as f:
        backend_config = yaml.safe_load(f) or {}
else:
    backend_config = {}


def get_superusers(frontend: str) -> list[str]:
    """获取指定前端的 superuser 列表。"""
    try:
        return backend_config["message_backend"][frontend]["superusers"]
    except KeyError:
        logger.warning("No superusers configured for frontend %s", frontend)
        return []


def is_superuser(frontend: str, user_id: Any) -> bool:
    """判断指定用户是否为 superuser。"""
    superusers = [str(u) for u in get_superusers(frontend)]
    return str(user_id) in superusers

def get_platform(frontend: str) -> str:
    """Normalize frontend/adapter names to semantic platform names."""
    mapping = {
        "onebot": "qq",
        "cqhttp": "qq",
        "cqhttp_ws": "qq",
        "botpy": "qq",
        "satori_http": "qq",
        "ntchat": "wechat",
        "telegram": "telegram",
        "console": "console"
    }
    return mapping.get(frontend.lower(), frontend.lower())

def get_rejection_phrases() -> list[str]:
    """获取全局黑名单拒绝回复短语列表"""
    try:
        return backend_config.get("acl", {}).get("rejection_phrases", ["Nemo 并不是很想跟你讲话。"])
    except Exception:
        return ["Nemo 并不是很想跟你讲话。"]

def get_webhook_tokens() -> list[str]:
    """获取合法的 webhook auth token 列表"""
    return backend_config.get("agent", {}).get("webhook_tokens", [])

def get_gatekeeper_model() -> list[str]:
    """获取守门员模型名称（支持 fallback 列表）"""
    val = backend_config.get("llm", {}).get("gatekeeper_model", [])
    if isinstance(val, str):
        return [val]
    return val if isinstance(val, list) else []

def get_reflection_model() -> list[str]:
    """获取反思引擎模型名称（支持 fallback 列表）"""
    val = backend_config.get("llm", {}).get("reflection_model", [])
    if isinstance(val, str):
        return [val]
    return val if isinstance(val, list) else []

def get_affinity_config() -> dict:
    """获取好感度系统静态配置（affinity 节）"""
    val = backend_config.get("affinity", {})
    return val if isinstance(val, dict) else {}

def get_reflection_retention_days() -> float:
    """conversations 表保留天数（反思任务清理用），0 = 不清理"""
    try:
        return float(backend_config.get("reflection", {}).get("retention_days", 14))
    except Exception:
        return 14.0

