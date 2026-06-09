"""Tests for the pre-submit content gate (heuristic + LLM)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from video_mcp.config import Settings
from video_mcp.content_gate import assert_heuristic_clean, assert_prompt_clean, heuristic_flags
from video_mcp.errors import ContentPolicyError


def _settings() -> Settings:
    return Settings(openrouter_api_key=None)


# --- heuristic ---

@pytest.mark.parametrize("bad", [
    "a young woman talking to camera",
    "teenage girl on a couch",
    "portrait of a teen creator",
    "a child in the background",
])
def test_heuristic_blocks_age_terms(bad):
    with pytest.raises(ContentPolicyError):
        assert_heuristic_clean(bad)


@pytest.mark.parametrize("bad", [
    "use the posterized reference",
    "apply a grid over the face",
    "dithered reference plate",
])
def test_heuristic_blocks_processing_terms(bad):
    with pytest.raises(ContentPolicyError):
        assert_heuristic_clean(bad)


def test_heuristic_passes_adult_framing():
    assert_heuristic_clean(
        "Use @Image1 as an identity reference, not a direct copy, for the fictional adult creator. "
        "She speaks to the camera in a cafe."
    )


def test_flags_report_terms():
    flags = heuristic_flags("a young teen with a grid overlay")
    assert flags["age"] and flags["processing"]


# --- LLM layer ---

async def test_llm_block(monkeypatch):
    monkeypatch.setattr("video_mcp.content_gate.chat_with_fallback",
                        AsyncMock(return_value="BLOCK: depicts a named public figure"))
    with pytest.raises(ContentPolicyError):
        await assert_prompt_clean("an adult creator who looks exactly like <celebrity>", _settings())


async def test_llm_ok(monkeypatch):
    monkeypatch.setattr("video_mcp.content_gate.chat_with_fallback", AsyncMock(return_value="OK"))
    await assert_prompt_clean("an adult creator in a cafe", _settings())  # no raise


async def test_llm_unreachable_falls_back_to_heuristic(monkeypatch):
    monkeypatch.setattr("video_mcp.content_gate.chat_with_fallback", AsyncMock(return_value=None))
    # heuristic still blocks the obvious case even when the LLM is down
    with pytest.raises(ContentPolicyError):
        await assert_prompt_clean("a young woman", _settings())
    # ...and a clean prompt passes when the LLM is unreachable
    await assert_prompt_clean("an adult creator in a cafe", _settings())


async def test_use_llm_false_skips_network(monkeypatch):
    called = AsyncMock()
    monkeypatch.setattr("video_mcp.content_gate.chat_with_fallback", called)
    await assert_prompt_clean("an adult creator", _settings(), use_llm=False)
    called.assert_not_called()
