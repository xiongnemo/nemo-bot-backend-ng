# Compatibility shim: redirect to core.message_request
from core.message_request import MessageRequest  # noqa: F401

__all__ = ["MessageRequest"]
