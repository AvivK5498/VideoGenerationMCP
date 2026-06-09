"""Tests for video_mcp.utils.transliterate (LLM-backed)."""

from __future__ import annotations

import httpx
import pytest
import respx

from video_mcp.config import Settings
from video_mcp.errors import TransliterationError
from video_mcp.utils.transliterate import _clean, has_hebrew, transliterate_hebrew

LMSTUDIO = "http://localhost:1234/v1"
OPENROUTER = "https://openrouter.ai/api/v1"


def _settings(**kw) -> Settings:
    base = dict(
        lmstudio_base_url=LMSTUDIO,
        lmstudio_model="google/gemma-4-e4b",
        openrouter_base_url=OPENROUTER,
        openrouter_api_key="or-test-key",
        openrouter_model="nvidia/llama-3.1-nemotron-70b-instruct",
        transliterate_max_tokens=512,
        transliterate_timeout_s=30,
    )
    base.update(kw)
    return Settings(**base)


def _chat_response(content: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})


# ---- has_hebrew (pure) ----

def test_has_hebrew_true():
    assert has_hebrew("שלום") is True
    assert has_hebrew("hello שלום") is True


def test_has_hebrew_false():
    assert has_hebrew("hello world") is False
    assert has_hebrew("123 !?.,") is False
    assert has_hebrew("") is False


# ---- _clean (pure) ----

def test_clean_strips_think_and_quotes():
    assert _clean("<think>reasoning here</think>\n  shalom olam ") == "shalom olam"
    assert _clean('"shalom olam"') == "shalom olam"
    assert _clean("shalom olam") == "shalom olam"


# ---- transliterate_hebrew ----

async def test_passthrough_non_hebrew_makes_no_call():
    # No respx routes registered -> any HTTP call would raise. None should happen.
    text = "Hello, world! 123 (test) - ok."
    assert await transliterate_hebrew(text, _settings()) == text


@respx.mock
async def test_lmstudio_success():
    route = respx.post(f"{LMSTUDIO}/chat/completions").mock(
        return_value=_chat_response("shalom olam, knu achshav")
    )
    result = await transliterate_hebrew("שלום עולם, קנו עכשיו", _settings())
    assert result == "shalom olam, knu achshav"
    assert has_hebrew(result) is False
    assert route.called
    # No Authorization header to the local server.
    assert "authorization" not in {k.lower() for k in route.calls.last.request.headers}


@respx.mock
async def test_falls_back_to_openrouter_when_lmstudio_unreachable():
    respx.post(f"{LMSTUDIO}/chat/completions").mock(side_effect=httpx.ConnectError("refused"))
    or_route = respx.post(f"{OPENROUTER}/chat/completions").mock(
        return_value=_chat_response("shalom olam")
    )
    result = await transliterate_hebrew("שלום עולם", _settings())
    assert result == "shalom olam"
    assert or_route.called
    assert or_route.calls.last.request.headers["authorization"] == "Bearer or-test-key"


@respx.mock
async def test_raises_when_both_providers_fail():
    respx.post(f"{LMSTUDIO}/chat/completions").mock(side_effect=httpx.ConnectError("refused"))
    respx.post(f"{OPENROUTER}/chat/completions").mock(return_value=httpx.Response(500))
    with pytest.raises(TransliterationError):
        await transliterate_hebrew("שלום", _settings())


@respx.mock
async def test_no_openrouter_key_and_lmstudio_down_raises():
    respx.post(f"{LMSTUDIO}/chat/completions").mock(side_effect=httpx.ConnectError("refused"))
    with pytest.raises(TransliterationError):
        await transliterate_hebrew("שלום", _settings(openrouter_api_key=None))


@respx.mock
async def test_raises_when_result_still_hebrew():
    # Model echoes Hebrew back -> must not be accepted; both providers fail this way.
    respx.post(f"{LMSTUDIO}/chat/completions").mock(return_value=_chat_response("שלום"))
    respx.post(f"{OPENROUTER}/chat/completions").mock(return_value=_chat_response("שלום"))
    with pytest.raises(TransliterationError):
        await transliterate_hebrew("שלום", _settings())
