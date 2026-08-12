"""
Shared helper: call the cheap reflection model for background compression jobs.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def call_cheap_model(system: str, user_text: str) -> str | None:
    """Call the configured reflection model (with fallback list). Returns text or None."""
    from config import get_reflection_model
    from nemollm.registry import get_client
    from nemollm import ChatMessage

    models = get_reflection_model()
    if not models:
        return None

    for model_str in models:
        try:
            client, actual_model = get_client(model_str)
        except Exception as e:
            logger.warning("[compress] could not load client %s: %s", model_str, e)
            continue
        try:
            resp = client.chat(
                model=actual_model,
                messages=[ChatMessage(role="user", content=user_text)],
                system=system,
            )
            if resp and resp.text:
                return resp.text.strip()
        except Exception as e:
            logger.warning("[compress] model %s failed: %s", actual_model, e)
            continue
    return None
