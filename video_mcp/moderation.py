"""Classify a terminal PiAPI failure as content-moderation vs other (for reporting)."""

from __future__ import annotations

_SIGNALS = (
    "real person",
    "content restriction",
    "community guidelin",
    "moderat",
    "sensitive content",
)


def is_moderation_failure(message: str | None) -> bool:
    """True if a terminal failure message looks like a content-moderation rejection."""
    if not message:
        return False
    m = message.lower()
    return any(sig in m for sig in _SIGNALS)
