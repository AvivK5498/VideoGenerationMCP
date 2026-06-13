"""Tests for the voiceover-fit primitives: trim_video, retime_video, mix_narration.

Covers the Pydantic schemas (pure), the ffmpeg-backed utils (ffmpeg-gated), and
the FastMCP tool wiring + validation errors (mocked, no ffmpeg).
"""

from __future__ import annotations

import shutil
import subprocess
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from video_mcp.config import Settings
from video_mcp.errors import MediaError
from video_mcp.schemas.media import MixNarrationRequest, RetimeVideoRequest, TrimVideoRequest
from video_mcp.tools import Deps
from video_mcp.tools.media import register_media_tools
from video_mcp.utils.carrier import make_black_carrier
from video_mcp.utils.media import (
    has_audio,
    mix_narration,
    probe_duration,
    retime_video,
    trim_video,
)

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_required = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def _silent_video(path: str, seconds: float) -> str:
    """A video with NO audio stream (color source only)."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"color=c=black:s=320x240:r=24:d={seconds}",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", path],
        capture_output=True, check=True,
    )
    return path


def _tone(path: str, seconds: float) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-acodec", "libmp3lame", path],
        capture_output=True, check=True,
    )
    return path


# =========================================================================== schemas

def test_trim_schema_requires_one_mode():
    with pytest.raises(ValidationError):
        TrimVideoRequest(video_path="v", output_path="o")  # neither
    with pytest.raises(ValidationError):
        TrimVideoRequest(video_path="v", output_path="o", duration_s=5, start_s=1, end_s=2)  # both


def test_trim_schema_duration_must_be_positive():
    with pytest.raises(ValidationError):
        TrimVideoRequest(video_path="v", output_path="o", duration_s=0)
    with pytest.raises(ValidationError):
        TrimVideoRequest(video_path="v", output_path="o", duration_s=-1)


def test_trim_schema_span_bounds():
    with pytest.raises(ValidationError):
        TrimVideoRequest(video_path="v", output_path="o", start_s=2, end_s=2)  # end<=start
    with pytest.raises(ValidationError):
        TrimVideoRequest(video_path="v", output_path="o", start_s=-1, end_s=3)  # start<0


def test_trim_schema_span_resolution():
    assert TrimVideoRequest(video_path="v", output_path="o", duration_s=4).span == (0.0, 4)
    assert TrimVideoRequest(video_path="v", output_path="o", start_s=1, end_s=3).span == (1, 3)


def test_retime_schema_requires_exactly_one():
    with pytest.raises(ValidationError):
        RetimeVideoRequest(video_path="v", output_path="o")  # neither
    with pytest.raises(ValidationError):
        RetimeVideoRequest(video_path="v", output_path="o", target_duration_s=5, speed=1.0)  # both


def test_retime_schema_ranges():
    with pytest.raises(ValidationError):
        RetimeVideoRequest(video_path="v", output_path="o", target_duration_s=0)
    with pytest.raises(ValidationError):
        RetimeVideoRequest(video_path="v", output_path="o", speed=0.4)
    with pytest.raises(ValidationError):
        RetimeVideoRequest(video_path="v", output_path="o", speed=2.5)
    assert RetimeVideoRequest(video_path="v", output_path="o", speed=2.0).speed == 2.0


def test_mix_narration_schema_rejects_negative_db():
    with pytest.raises(ValidationError):
        MixNarrationRequest(video_path="v", voiceover_path="vo", output_path="o", bed_below_voice_db=-1)
    ok = MixNarrationRequest(video_path="v", voiceover_path="vo", output_path="o")
    assert ok.bed_below_voice_db == 14.0


# ============================================================================= utils

@ffmpeg_required
def test_trim_video_by_duration(tmp_path):
    src = make_black_carrier(3, str(tmp_path / "src.mp4"))
    out, dur = trim_video(src, str(tmp_path / "out.mp4"), duration_s=1.5)
    assert abs(dur - 1.5) < 0.2
    assert abs(probe_duration(out) - 1.5) < 0.2


@ffmpeg_required
def test_trim_video_by_span(tmp_path):
    src = make_black_carrier(4, str(tmp_path / "src.mp4"))
    out, dur = trim_video(src, str(tmp_path / "out.mp4"), start_s=1.0, end_s=2.5)
    assert abs(dur - 1.5) < 0.2


@ffmpeg_required
def test_trim_video_silent_input_silent_output(tmp_path):
    src = _silent_video(str(tmp_path / "silent.mp4"), 3)
    assert has_audio(src) is False
    out, dur = trim_video(src, str(tmp_path / "out.mp4"), duration_s=1.0)
    assert abs(dur - 1.0) < 0.2
    assert has_audio(out) is False  # never errors on missing audio


@ffmpeg_required
def test_trim_video_missing_file(tmp_path):
    with pytest.raises(MediaError):
        trim_video("/nope/v.mp4", str(tmp_path / "o.mp4"), duration_s=1.0)


@ffmpeg_required
def test_trim_video_beyond_source(tmp_path):
    src = make_black_carrier(2, str(tmp_path / "src.mp4"))
    with pytest.raises(MediaError):
        trim_video(src, str(tmp_path / "o.mp4"), duration_s=5.0)


@ffmpeg_required
def test_retime_video_to_target_duration(tmp_path):
    src = make_black_carrier(2, str(tmp_path / "src.mp4"))
    out, dur, speed = retime_video(src, str(tmp_path / "out.mp4"), target_duration_s=3.0)
    assert abs(dur - 3.0) < 0.3
    assert abs(speed - (2.0 / 3.0)) < 0.05  # source/target


@ffmpeg_required
def test_retime_video_explicit_speed(tmp_path):
    src = make_black_carrier(2, str(tmp_path / "src.mp4"))
    out, dur, speed = retime_video(src, str(tmp_path / "out.mp4"), speed=2.0)
    assert speed == 2.0
    assert abs(dur - 1.0) < 0.2  # 2x faster => half as long


@ffmpeg_required
def test_retime_video_speed_out_of_range(tmp_path):
    src = make_black_carrier(2, str(tmp_path / "src.mp4"))
    with pytest.raises(MediaError):
        retime_video(src, str(tmp_path / "o.mp4"), speed=3.0)
    # target that implies speed > 2.0 (2s source -> 0.5s target => speed 4)
    with pytest.raises(MediaError):
        retime_video(src, str(tmp_path / "o.mp4"), target_duration_s=0.5)


@ffmpeg_required
def test_retime_video_missing_file(tmp_path):
    with pytest.raises(MediaError):
        retime_video("/nope/v.mp4", str(tmp_path / "o.mp4"), speed=1.5)


@ffmpeg_required
def test_mix_narration_no_bed(tmp_path):
    video = _silent_video(str(tmp_path / "v.mp4"), 3)
    vo = _tone(str(tmp_path / "vo.mp3"), 2)
    out, dur = mix_narration(video, vo, str(tmp_path / "out.mp4"))
    assert abs(dur - 3.0) < 0.3  # output runs the VIDEO length (VO padded)
    assert has_audio(out) is True


@ffmpeg_required
def test_mix_narration_with_bed(tmp_path):
    video = _silent_video(str(tmp_path / "v.mp4"), 2)
    vo = _tone(str(tmp_path / "vo.mp3"), 2)
    bed = _tone(str(tmp_path / "bed.mp3"), 1)  # shorter; loops under VO
    out, dur = mix_narration(video, vo, str(tmp_path / "out.mp4"), bed_path=bed)
    assert abs(dur - 2.0) < 0.3
    assert has_audio(out) is True


@ffmpeg_required
def test_mix_narration_missing_inputs(tmp_path):
    video = _silent_video(str(tmp_path / "v.mp4"), 2)
    with pytest.raises(MediaError):
        mix_narration("/nope/v.mp4", str(tmp_path / "vo.mp3"), str(tmp_path / "o.mp4"))
    with pytest.raises(MediaError):
        mix_narration(video, "/nope/vo.mp3", str(tmp_path / "o.mp4"))


# ============================================================================= tools

def make_deps() -> Deps:
    s = Settings()
    s.piapi_key = "pk"
    s.elevenlabs_key = "ek"
    return Deps(settings=s, piapi=AsyncMock(), eleven=AsyncMock())


async def get_media_tool(name: str):
    mcp = FastMCP("test")
    register_media_tools(mcp, make_deps())
    tool = await mcp.get_tool(name)
    return tool.fn


async def test_trim_tool_resolves_span_and_returns(monkeypatch):
    trim = MagicMock(return_value=("/out.mp4", 5.0))
    monkeypatch.setattr("video_mcp.tools.media.media_mod.trim_video", trim)
    fn = await get_media_tool("trim_video")
    res = await fn(video_path="/v.mp4", output_path="/out.mp4", duration_s=5)
    assert trim.call_args.kwargs["start_s"] == 0.0
    assert trim.call_args.kwargs["end_s"] == 5
    assert res == {"output_path": "/out.mp4", "duration_s": 5.0}


async def test_trim_tool_validation_error():
    fn = await get_media_tool("trim_video")
    with pytest.raises(ToolError):
        await fn(video_path="/v.mp4", output_path="/o.mp4")  # neither mode
    with pytest.raises(ToolError):
        await fn(video_path="/v.mp4", output_path="/o.mp4", duration_s=0)


async def test_trim_tool_wraps_media_error(monkeypatch):
    monkeypatch.setattr(
        "video_mcp.tools.media.media_mod.trim_video", MagicMock(side_effect=MediaError("boom"))
    )
    fn = await get_media_tool("trim_video")
    with pytest.raises(ToolError):
        await fn(video_path="/v.mp4", output_path="/o.mp4", duration_s=2)


async def test_retime_tool_returns_speed(monkeypatch):
    retime = MagicMock(return_value=("/out.mp4", 3.0, 0.6667))
    monkeypatch.setattr("video_mcp.tools.media.media_mod.retime_video", retime)
    fn = await get_media_tool("retime_video")
    res = await fn(video_path="/v.mp4", output_path="/out.mp4", target_duration_s=3)
    assert res == {"output_path": "/out.mp4", "duration_s": 3.0, "speed": 0.6667}


async def test_retime_tool_rejects_out_of_range_speed():
    fn = await get_media_tool("retime_video")
    with pytest.raises(ToolError):
        await fn(video_path="/v.mp4", output_path="/o.mp4", speed=5.0)
    with pytest.raises(ToolError):
        await fn(video_path="/v.mp4", output_path="/o.mp4")  # neither target nor speed


async def test_retime_tool_wraps_media_error(monkeypatch):
    monkeypatch.setattr(
        "video_mcp.tools.media.media_mod.retime_video", MagicMock(side_effect=MediaError("boom"))
    )
    fn = await get_media_tool("retime_video")
    with pytest.raises(ToolError):
        await fn(video_path="/v.mp4", output_path="/o.mp4", speed=1.5)


async def test_mix_narration_tool_returns(monkeypatch):
    mix = MagicMock(return_value=("/out.mp4", 10.0))
    monkeypatch.setattr("video_mcp.tools.media.media_mod.mix_narration", mix)
    fn = await get_media_tool("mix_narration")
    res = await fn(video_path="/v.mp4", voiceover_path="/vo.mp3", output_path="/out.mp4", bed_path="/b.mp3")
    assert mix.call_args.kwargs["bed_path"] == "/b.mp3"
    assert res == {"output_path": "/out.mp4", "duration_s": 10.0}


async def test_mix_narration_tool_validation_error():
    fn = await get_media_tool("mix_narration")
    with pytest.raises(ToolError):
        await fn(video_path="/v.mp4", voiceover_path="/vo.mp3", output_path="/o.mp4",
                 bed_below_voice_db=-5)


async def test_mix_narration_tool_wraps_media_error(monkeypatch):
    monkeypatch.setattr(
        "video_mcp.tools.media.media_mod.mix_narration", MagicMock(side_effect=MediaError("boom"))
    )
    fn = await get_media_tool("mix_narration")
    with pytest.raises(ToolError):
        await fn(video_path="/v.mp4", voiceover_path="/vo.mp3", output_path="/o.mp4")
