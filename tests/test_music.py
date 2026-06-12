"""Tests for Eleven Music composition and the music tools (generate + mix)."""

from __future__ import annotations

import json
import shutil
import subprocess
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.clients.elevenlabs import ElevenLabsClient
from video_mcp.config import Settings
from video_mcp.errors import ElevenLabsError, MediaError
from video_mcp.tools import Deps
from video_mcp.tools.elevenlabs import register_elevenlabs_tools
from video_mcp.tools.media import register_media_tools

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_required = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def make_settings() -> Settings:
    s = Settings()
    s.piapi_key = "pk"
    s.elevenlabs_key = "ek"
    return s


# ------------------------------------------------------------------- client

@respx.mock
async def test_compose_music_payload_and_bytes():
    route = respx.post("https://api.elevenlabs.io/v1/music").mock(
        return_value=httpx.Response(200, content=b"MUSICBYTES")
    )
    out = await ElevenLabsClient(make_settings()).compose_music(
        "warm corporate groove", music_length_ms=15000, force_instrumental=True
    )
    assert out == b"MUSICBYTES"
    req = route.calls[0].request
    assert "output_format=mp3_44100_128" in str(req.url)
    body = json.loads(req.content)
    assert body == {
        "prompt": "warm corporate groove",
        "music_length_ms": 15000,
        "model_id": "music_v1",
        "force_instrumental": True,
    }


@respx.mock
async def test_compose_music_error():
    respx.post("https://api.elevenlabs.io/v1/music").mock(
        return_value=httpx.Response(422, json={"detail": "bad plan"})
    )
    with pytest.raises(ElevenLabsError):
        await ElevenLabsClient(make_settings()).compose_music("x", music_length_ms=5000)


@respx.mock
async def test_generate_sound_effect_payload_and_bytes():
    route = respx.post("https://api.elevenlabs.io/v1/sound-generation").mock(
        return_value=httpx.Response(200, content=b"SFXBYTES")
    )
    out = await ElevenLabsClient(make_settings()).generate_sound_effect(
        "busy gym ambience", duration_seconds=15
    )
    assert out == b"SFXBYTES"
    req = route.calls[0].request
    assert "output_format=mp3_44100_128" in str(req.url)
    body = json.loads(req.content)
    assert body == {
        "text": "busy gym ambience",
        "duration_seconds": 15,
        "prompt_influence": 0.25,
        "loop": True,
        "model_id": "eleven_text_to_sound_v2",
    }


@respx.mock
async def test_generate_sound_effect_error():
    respx.post("https://api.elevenlabs.io/v1/sound-generation").mock(
        return_value=httpx.Response(422, json={"detail": "bad request"})
    )
    with pytest.raises(ElevenLabsError):
        await ElevenLabsClient(make_settings()).generate_sound_effect("x", duration_seconds=5)


# ------------------------------------------------------------------ mix util

@ffmpeg_required
def test_mix_music_into_video(tmp_path):
    from video_mcp.utils.carrier import make_black_carrier
    from video_mcp.utils.media import mix_music_into_video, probe_duration

    video = make_black_carrier(3, str(tmp_path / "v.mp4"))
    music = str(tmp_path / "m.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=1",
         "-acodec", "libmp3lame", music],
        capture_output=True, check=True,
    )
    out = mix_music_into_video(video, music, str(tmp_path / "out.mp4"))
    # music (1s) loops under the full 3s video; output duration follows the video
    assert abs(probe_duration(out) - 3.0) < 0.5


@ffmpeg_required
def test_mix_music_no_duck(tmp_path):
    from video_mcp.utils.carrier import make_black_carrier
    from video_mcp.utils.media import mix_music_into_video

    video = make_black_carrier(2, str(tmp_path / "v.mp4"))
    music = str(tmp_path / "m.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=2",
         "-acodec", "libmp3lame", music],
        capture_output=True, check=True,
    )
    out = mix_music_into_video(video, music, str(tmp_path / "out.mp4"), duck=False)
    assert subprocess.run(["ffprobe", "-v", "error", out], capture_output=True).returncode == 0


def test_mix_music_missing_inputs(tmp_path):
    from video_mcp.utils.media import mix_music_into_video

    with pytest.raises(MediaError):
        mix_music_into_video("/nope/v.mp4", "/nope/m.mp3", str(tmp_path / "o.mp4"))


# --------------------------------------------------------------------- tools

def make_deps(eleven=None) -> Deps:
    return Deps(settings=make_settings(), piapi=AsyncMock(), eleven=eleven or AsyncMock())


async def get_tool(name: str, deps: Deps):
    mcp = FastMCP("test")
    register_elevenlabs_tools(mcp, deps)
    register_media_tools(mcp, deps)
    tool = await mcp.get_tool(name)
    return tool.fn


async def test_generate_music_tool(monkeypatch, tmp_path):
    eleven = AsyncMock()
    eleven.compose_music.return_value = b"MUSIC"
    monkeypatch.setattr("video_mcp.tools.elevenlabs.media_mod.probe_duration", MagicMock(return_value=15.0))
    fn = await get_tool("generate_music", make_deps(eleven=eleven))

    res = await fn(prompt="warm corporate groove, soft drums", duration_s=15)
    kwargs = eleven.compose_music.await_args.kwargs
    assert kwargs["music_length_ms"] == 15000
    assert kwargs["force_instrumental"] is True
    assert res["duration_s"] == 15.0
    with open(res["audio_path"], "rb") as fh:
        assert fh.read() == b"MUSIC"


async def test_generate_music_duration_bounds():
    fn = await get_tool("generate_music", make_deps())
    with pytest.raises(ToolError):
        await fn(prompt="x", duration_s=2)
    with pytest.raises(ToolError):
        await fn(prompt="x", duration_s=601)


async def test_generate_sound_effect_tool(monkeypatch, tmp_path):
    eleven = AsyncMock()
    eleven.generate_sound_effect.return_value = b"SFX"
    monkeypatch.setattr("video_mcp.tools.elevenlabs.media_mod.probe_duration", MagicMock(return_value=15.0))
    fn = await get_tool("generate_sound_effect", make_deps(eleven=eleven))

    res = await fn(prompt="busy gym ambience, low machine hum", duration_seconds=15)
    kwargs = eleven.generate_sound_effect.await_args.kwargs
    assert kwargs["duration_seconds"] == 15
    assert kwargs["prompt_influence"] == 0.25
    assert kwargs["loop"] is True
    assert res == {"audio_path": res["audio_path"], "duration_s": 15.0, "prompt": "busy gym ambience, low machine hum"}
    with open(res["audio_path"], "rb") as fh:
        assert fh.read() == b"SFX"


async def test_generate_sound_effect_clamps_duration(monkeypatch):
    eleven = AsyncMock()
    eleven.generate_sound_effect.return_value = b"SFX"
    monkeypatch.setattr("video_mcp.tools.elevenlabs.media_mod.probe_duration", MagicMock(return_value=None))
    fn = await get_tool("generate_sound_effect", make_deps(eleven=eleven))

    await fn(prompt="x", duration_seconds=0.1)
    assert eleven.generate_sound_effect.await_args.kwargs["duration_seconds"] == 0.5
    await fn(prompt="x", duration_seconds=99)
    assert eleven.generate_sound_effect.await_args.kwargs["duration_seconds"] == 30.0


async def test_generate_sound_effect_wraps_errors():
    eleven = AsyncMock()
    eleven.generate_sound_effect.side_effect = ElevenLabsError("boom")
    fn = await get_tool("generate_sound_effect", make_deps(eleven=eleven))
    with pytest.raises(ToolError):
        await fn(prompt="x", duration_seconds=10)


async def test_mix_tool_passes_args(monkeypatch, tmp_path):
    mix = MagicMock(side_effect=lambda v, m, out, **kw: out)
    monkeypatch.setattr("video_mcp.tools.media.media_mod.mix_music_into_video", mix)
    monkeypatch.setattr("video_mcp.tools.media.media_mod.probe_duration", MagicMock(return_value=15.0))
    fn = await get_tool("mix_music_into_video", make_deps())

    res = await fn(video="/v.mp4", music="/m.mp3", output_path=str(tmp_path / "o.mp4"),
                   music_gain_db=-24, duck=False)
    assert mix.call_args.kwargs["music_gain_db"] == -24
    assert mix.call_args.kwargs["duck"] is False
    assert res["output_path"] == str(tmp_path / "o.mp4")


async def test_mix_tool_wraps_errors(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "video_mcp.tools.media.media_mod.mix_music_into_video",
        MagicMock(side_effect=MediaError("boom")),
    )
    fn = await get_tool("mix_music_into_video", make_deps())
    with pytest.raises(ToolError):
        await fn(video="/v.mp4", music="/m.mp3", output_path=str(tmp_path / "o.mp4"))
