"""Logging with secret redaction for debugging API payloads.

Use `get_logger(__name__)` for a configured logger and `redact(obj)` before
logging any dict/headers that might contain credentials.
"""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

_SENSITIVE_KEYS = {
    "x-api-key",
    "xi-api-key",
    "authorization",
    "secret",
    "piapi_key",
    "elevenlabs_key",
    "api_key",
}

_CONFIGURED = False


def _configure_root() -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("video_mcp")
    root.setLevel(level)
    if not root.handlers:
        root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    _configure_root()
    if not name.startswith("video_mcp"):
        name = f"video_mcp.{name}"
    return logging.getLogger(name)


def redact(obj: Any) -> Any:
    """Deep-copy `obj`, masking values whose key looks sensitive.

    Safe to call on dicts, lists, and scalars. Never mutates the input.
    """
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in _SENSITIVE_KEYS:
                out[k] = "***REDACTED***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, tuple):
        return tuple(redact(v) for v in obj)
    return copy.copy(obj)
