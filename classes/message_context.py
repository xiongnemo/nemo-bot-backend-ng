# Compatibility shim: redirect to core.message_context
from core.message_context import MessageContext  # noqa: F401

__all__ = ["MessageContext"]
