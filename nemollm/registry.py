"""Model registry for routing models to the correct client."""

from __future__ import annotations

import logging
from typing import Tuple

from .anthropic_client import AnthropicClient
from .base import BaseLLMClient
from .gemini_client import GeminiClient
from .openai_client import OpenAIClient
from .openai_responses_client import OpenAIResponsesClient

logger = logging.getLogger(__name__)


class ModelRegistry:
    """
    Instantiates and routes to different LLM providers based on
    config.json settings and model prefixes.
    """

    def __init__(self, config: dict):
        self.config = config
        self.providers: dict[str, BaseLLMClient] = {}
        self.fallback_models: list[str] = config.get("models", [])
        self._active_index: int = 0
        
        # Backward compatibility for old config
        if not self.fallback_models and "default_model" in config:
            self.fallback_models = [config["default_model"]]
            
        if not self.fallback_models:
            self.fallback_models = ["gemini:gemini-3.5-flash"]

        p_cfg = config.get("providers", {})
        global_timeout = config.get("timeout", 120)
        global_temperature = config.get("temperature", 0.7)
        for name, p_data in p_cfg.items():
            ptype = p_data.get("type", name)  # fallback to name if type missing
            timeout = p_data.get("timeout", global_timeout)
            temp = p_data.get("temperature", global_temperature)
            
            if ptype == "openai":
                self.providers[name] = OpenAIClient(
                    base_url=p_data.get("base_url", "https://api.openai.com/v1"),
                    api_key=p_data.get("api_key", ""),
                    timeout=timeout,
                    default_temperature=temp,
                )
            elif ptype == "openai-responses":
                self.providers[name] = OpenAIResponsesClient(
                    base_url=p_data.get("base_url", "https://api.openai.com/v1"),
                    api_key=p_data.get("api_key", ""),
                    timeout=timeout,
                    default_temperature=temp,
                )
            elif ptype == "anthropic":
                self.providers[name] = AnthropicClient(
                    base_url=p_data.get("base_url", "https://api.anthropic.com"),
                    api_key=p_data.get("api_key", ""),
                    timeout=timeout,
                    default_temperature=temp,
                )
            elif ptype == "gemini":
                self.providers[name] = GeminiClient(
                    base_url=p_data.get("base_url", "https://generativelanguage.googleapis.com"),
                    api_key=p_data.get("api_key", ""),
                    timeout=timeout,
                    default_temperature=temp,
                )
            else:
                logger.warning(f"Unknown provider type '{ptype}' for provider '{name}'")

    def get_models(self) -> list[Tuple[BaseLLMClient, str]]:
        """
        Return a list of (client, actual_model) tuples in order of fallback priority.
        """
        models = []
        for model_id in self.fallback_models:
            parts = model_id.split(":", 1)
            if len(parts) == 2:
                provider_name, actual_model = parts
            else:
                provider_name, actual_model = "openai", model_id

            client = self.providers.get(provider_name)
            if client:
                models.append((client, actual_model))
            else:
                logger.warning(f"Provider '{provider_name}' not found for model '{model_id}'")
        
        if not models:
            raise ValueError("No valid fallback models could be resolved from config.")
            
        if getattr(self, "_active_index", 0) > 0 and self._active_index < len(models):
            models = models[self._active_index:] + models[:self._active_index]
            
        return models

    def report_success(self, client: BaseLLMClient, actual_model: str) -> None:
        """Report that a model call succeeded, promoting it to be tried first in subsequent calls."""
        models = []
        for model_id in self.fallback_models:
            parts = model_id.split(":", 1)
            if len(parts) == 2:
                provider_name, mod = parts
            else:
                provider_name, mod = "openai", model_id
            c = self.providers.get(provider_name)
            if c:
                models.append((c, mod))
                
        for idx, (c, m) in enumerate(models):
            if c == client and m == actual_model:
                if getattr(self, "_active_index", 0) != idx:
                    logger.info(f"Promoting fallback model '{m}' (index {idx}) to primary try for next turn.")
                    self._active_index = idx
                break

    def get_client(self, model_id: str) -> Tuple[BaseLLMClient, str]:
        """Resolve a specific model_id (provider:model) to a client and actual model string."""
        parts = model_id.split(":", 1)
        if len(parts) == 2:
            provider_name, actual_model = parts
        else:
            provider_name, actual_model = "openai", model_id
            
        client = self.providers.get(provider_name)
        if not client:
            raise ValueError(f"Provider '{provider_name}' not found for model '{model_id}'")
        return client, actual_model


# Global singleton populated during app startup
_registry: ModelRegistry | None = None
_last_mtime: float = 0.0

def init_registry(llm_config: dict) -> None:
    global _registry
    _registry = ModelRegistry(llm_config)


def get_registry() -> ModelRegistry:
    global _registry, _last_mtime
    
    import os
    import yaml
    from config import _config_path
    
    try:
        if os.path.exists(_config_path):
            current_mtime = os.path.getmtime(_config_path)
            # If the config file was modified, hot-reload the registry
            if _last_mtime > 0 and current_mtime > _last_mtime:
                logger.info("Detected config.yml changes, hot-reloading LLM registry...")
                with open(_config_path, "r", encoding="utf-8") as f:
                    new_config = yaml.safe_load(f) or {}
                _registry = ModelRegistry(new_config.get("llm", {}))
                
            _last_mtime = current_mtime
    except Exception as e:
        logger.error(f"Failed to check/reload config for LLM registry: {e}")

    if not _registry:
        from config import backend_config
        _registry = ModelRegistry(backend_config.get("llm", {}))
        
    return _registry

def get_client(model_id: str) -> Tuple[BaseLLMClient, str]:
    return get_registry().get_client(model_id)
