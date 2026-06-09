"""Tests for the generate_elevenlabs_voiceover tool — self-contained."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.config import Settings
from video_mcp.errors import ElevenLabsError
from video_mcp.tools import Deps
from video_mcp.tools.elevenlabs import register_elevenlabs_tools


def make_settings() -> Settings:
    s = Settings()
    s.piapi_key = "pk"
    s.elevenlabs_key = "ek"
    return s


def make_deps(eleven: AsyncMock) -> Deps:
    return Deps(settings=make_settings(), piapi=AsyncMock(), eleven=eleven)


async def get_tool(deps: Deps):
    mcp = FastMCP("test")
    register_elevenlabs_tools(mcp, deps)
    tool = await mcp.get_tool("generate_elevenlabs_voiceover")
    return tool.fn


async def test_with_timestamps_returns_alignment_and_path():
    eleven = AsyncMock()
    alignment = {"characters": ["h", "i"], "character_start_times_seconds": [0.0, 0.1]}
    eleven.tts_with_timestamps.return_value = (b"AUDIOBYTES", {"alignment": alignment})
    fn = await get_tool(make_deps(eleven))

    res = await fn(text="hi there", voice_id="v1", with_timestamps=True)

    assert os.path.exists(res["audio_path"])
    assert os.path.getsize(res["audio_path"]) > 0
    assert res["alignment"] == alignment
    assert res["characters"] == len("hi there")
    assert res["model_id"] == "eleven_multilingual_v2"
    assert res["output_format"] == "mp3_44100_128"
    eleven.tts_with_timestamps.assert_awaited_once()
    eleven.tts.assert_not_called()
    os.remove(res["audio_path"])


async def test_without_timestamps_uses_tts_and_no_alignment():
    eleven = AsyncMock()
    eleven.tts.return_value = b"PLAINAUDIO"
    fn = await get_tool(make_deps(eleven))

    res = await fn(text="hello", voice_id="v1", with_timestamps=False)

    assert res["alignment"] is None
    assert res["characters"] == 5
    assert os.path.exists(res["audio_path"])
    eleven.tts.assert_awaited_once()
    eleven.tts_with_timestamps.assert_not_called()
    os.remove(res["audio_path"])


async def test_hebrew_language_forces_eleven_v3():
    eleven = AsyncMock()
    eleven.tts.return_value = b"HEBAUDIO"
    fn = await get_tool(make_deps(eleven))

    res = await fn(text="שלום", voice_id="v1", language="he", with_timestamps=False)

    assert res["model_id"] == "eleven_v3"
    os.remove(res["audio_path"])


async def test_provider_error_becomes_toolerror():
    eleven = AsyncMock()
    eleven.tts_with_timestamps.side_effect = ElevenLabsError("voice not found", code=422)
    fn = await get_tool(make_deps(eleven))

    with pytest.raises(ToolError):
        await fn(text="x", voice_id="bad")


async def test_invalid_request_becomes_toolerror():
    fn = await get_tool(make_deps(AsyncMock()))
    with pytest.raises(ToolError):
        await fn(text="", voice_id="v1")  # min_length violation
