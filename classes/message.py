# Compatibility shim: redirect to core.message
from core.message import Message  # noqa: F401

__all__ = ["Message"]
