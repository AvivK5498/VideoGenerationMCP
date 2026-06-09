"""Tests for moderation-failure classification (used for failure_reason reporting)."""

from __future__ import annotations

from video_mcp.moderation import is_moderation_failure


def test_is_moderation_failure_signals():
    assert is_moderation_failure("input image may contain a real person")
    assert is_moderation_failure("Content restriction triggered")
    assert is_moderation_failure("violates community guidelines")
    assert is_moderation_failure("flagged by moderation")


def test_is_moderation_failure_negatives():
    assert not is_moderation_failure(None)
    assert not is_moderation_failure("")
    assert not is_moderation_failure("internal server error 500")
