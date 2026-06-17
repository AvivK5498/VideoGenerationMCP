"""Tests for video_mcp.utils.media and the assembly tools (stitch/split/frame)."""

from __future__ import annotations

import os
import shutil
import subprocess
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.config import Settings
from video_mcp.errors import MediaError
from video_mcp.tools import Deps
from video_mcp.tools.media import register_media_tools
from video_mcp.utils.carrier import make_black_carrier
from video_mcp.utils.media import detect_beats, extract_frame, probe_duration, split_audio, stitch_videos

_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
ffmpeg_required = pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg/ffprobe not installed")


def _tone(path: str, seconds: float) -> str:
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-acodec", "libmp3lame", path],
        capture_output=True, check=True,
    )
    return path


# ------------------------------------------------------------------------ utils

@ffmpeg_required
def test_stitch_videos_durations_add_up(tmp_path):
    a = make_black_carrier(1, str(tmp_path / "a.mp4"))
    b = make_black_carrier(2, str(tmp_path / "b.mp4"))
    out = stitch_videos([a, b], str(tmp_path / "out.mp4"))
    assert abs(probe_duration(out) - 3.0) < 0.6


def test_stitch_videos_rejects_single_clip(tmp_path):
    with pytest.raises(MediaError):
        stitch_videos([str(tmp_path / "only.mp4")], str(tmp_path / "out.mp4"))


def test_stitch_videos_missing_clip(tmp_path):
    with pytest.raises(MediaError):
        stitch_videos(["/nope/a.mp4", "/nope/b.mp4"], str(tmp_path / "out.mp4"))


@ffmpeg_required
def test_split_audio_segments(tmp_path):
    src = _tone(str(tmp_path / "vo.mp3"), 3.0)
    segs = split_audio(src, [1.0, 2.0], str(tmp_path))
    assert len(segs) == 3
    assert [s["start_s"] for s in segs] == [0.0, 1.0, 2.0]
    for s in segs:
        assert os.path.getsize(s["path"]) > 0
        assert abs(probe_duration(s["path"]) - s["duration_s"]) < 0.3


@ffmpeg_required
def test_split_audio_rejects_bad_points(tmp_path):
    src = _tone(str(tmp_path / "vo.mp3"), 2.0)
    with pytest.raises(MediaError):
        split_audio(src, [], str(tmp_path))
    with pytest.raises(MediaError):
        split_audio(src, [1.5, 1.0], str(tmp_path))
    with pytest.raises(MediaError):
        split_audio(src, [5.0], str(tmp_path))  # outside the audio


@ffmpeg_required
def test_extract_frame_last_and_timed(tmp_path):
    vid = make_black_carrier(2, str(tmp_path / "v.mp4"))
    last = extract_frame(vid, str(tmp_path / "last.png"))
    timed = extract_frame(vid, str(tmp_path / "t.png"), time_s=0.5)
    assert os.path.getsize(last) > 0
    assert os.path.getsize(timed) > 0


def test_extract_frame_missing_video(tmp_path):
    with pytest.raises(MediaError):
        extract_frame("/nope/v.mp4", str(tmp_path / "f.png"))


# ------------------------------------------------------------------------ tools

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


async def test_stitch_tool_downloads_urls(monkeypatch, tmp_path):
    dl = AsyncMock()
    monkeypatch.setattr("video_mcp.tools.media.download", dl)
    stitch = MagicMock(return_value=str(tmp_path / "out.mp4"))
    monkeypatch.setattr("video_mcp.tools.media.media_mod.stitch_videos", stitch)
    monkeypatch.setattr("video_mcp.tools.media.media_mod.probe_duration", MagicMock(return_value=9.9))
    fn = await get_media_tool("stitch_videos")

    res = await fn(videos=["https://x/a.mp4", "/local/b.mp4"], output_path=str(tmp_path / "out.mp4"))
    dl.assert_awaited_once()  # only the URL is downloaded
    assert stitch.call_args.args[0][1] == "/local/b.mp4"  # local path passed through
    assert res == {"output_path": str(tmp_path / "out.mp4"), "duration_s": 9.9, "clips": 2}


async def test_stitch_tool_wraps_media_error(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "video_mcp.tools.media.media_mod.stitch_videos", MagicMock(side_effect=MediaError("boom"))
    )
    fn = await get_media_tool("stitch_videos")
    with pytest.raises(ToolError):
        await fn(videos=["/a.mp4", "/b.mp4"], output_path=str(tmp_path / "o.mp4"))


async def test_split_tool_returns_segments(monkeypatch):
    segs = [{"path": "/d/s1.mp3", "start_s": 0.0, "end_s": 1.0, "duration_s": 1.0}]
    monkeypatch.setattr("video_mcp.tools.media.media_mod.split_audio", MagicMock(return_value=segs))
    fn = await get_media_tool("split_audio")
    res = await fn(audio_path="/d/vo.mp3", split_points_s=[1.0], output_dir="/d")
    assert res == {"segments": segs, "output_dir": "/d"}


async def test_extract_frame_tool_uploads(monkeypatch):
    monkeypatch.setattr("video_mcp.tools.media.media_mod.extract_frame", MagicMock(return_value="/tmp/f.png"))
    up = AsyncMock(return_value="https://tmpfiles.org/dl/9/f.png")
    monkeypatch.setattr("video_mcp.tools.media.uploader_mod.upload_file", up)
    fn = await get_media_tool("extract_frame")
    res = await fn(video="/local/v.mp4", upload=True)
    assert res["frame_url"] == "https://tmpfiles.org/dl/9/f.png"
    assert res["time_s"] == "last"


async def test_host_file_uploads(monkeypatch, tmp_path):
    f = tmp_path / "vo.mp3"
    f.write_bytes(b"AUDIO")
    up = AsyncMock(return_value="https://tmpfiles.org/dl/3/vo.mp3")
    monkeypatch.setattr("video_mcp.tools.media.uploader_mod.upload_file", up)
    fn = await get_media_tool("host_file")
    res = await fn(path=str(f))
    assert res == {"url": "https://tmpfiles.org/dl/3/vo.mp3", "path": str(f)}


async def test_host_file_missing(monkeypatch):
    fn = await get_media_tool("host_file")
    with pytest.raises(ToolError):
        await fn(path="/nope/vo.mp3")


# --------------------------------------------------------------- detect_beats

def _click_track(path: str, bpm: float, seconds: float, *, sr: int = 22050, silent: bool = False) -> str:
    """Write a mono 16-bit WAV: a 1kHz percussive click on every beat (or silence)."""
    import wave

    import numpy as np

    n = int(seconds * sr)
    y = np.zeros(n, dtype=np.float32)
    if not silent:
        clen = int(0.012 * sr)
        env = np.exp(-np.linspace(0.0, 7.0, clen)).astype(np.float32)
        click = (np.sin(2 * np.pi * 1000.0 * np.arange(clen) / sr).astype(np.float32) * env)
        period = 60.0 / bpm
        t = 0.0
        while t < seconds:
            i = int(t * sr)
            seg = min(clen, n - i)
            if seg > 0:
                y[i : i + seg] += click[:seg]
            t += period
    pcm = (np.clip(y, -1.0, 1.0) * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return path


@ffmpeg_required
def test_detect_beats_click_track_100bpm(tmp_path):
    src = _click_track(str(tmp_path / "click100.wav"), bpm=100.0, seconds=8.0)
    bpm, beats = detect_beats(src)
    assert abs(bpm - 100.0) <= 3.0                       # tempo within +/-3
    assert len(beats) >= 10                              # covers the whole 8s file
    assert beats == sorted(beats)                        # ascending
    diffs = [b - a for a, b in zip(beats, beats[1:])]
    median = sorted(diffs)[len(diffs) // 2]
    assert abs(median - 60.0 / 100.0) <= 0.04            # spacing ~= 60/bpm = 0.6s


@ffmpeg_required
def test_detect_beats_reports_lower_octave(tmp_path):
    # Clicks at 172 BPM with the default [80,160] window must fold to ~86, not 172.
    src = _click_track(str(tmp_path / "click172.wav"), bpm=172.0, seconds=8.0)
    bpm, beats = detect_beats(src)
    assert 80.0 <= bpm <= 160.0
    assert abs(bpm - 86.0) <= 5.0
    assert len(beats) >= 8


@ffmpeg_required
def test_detect_beats_silence(tmp_path):
    src = _click_track(str(tmp_path / "silence.wav"), bpm=120.0, seconds=4.0, silent=True)
    assert detect_beats(src) == (0.0, [])


def test_detect_beats_missing_file():
    with pytest.raises(MediaError):
        detect_beats("/nope/track.wav")


@ffmpeg_required
async def test_detect_beats_tool_shape(tmp_path):
    src = _click_track(str(tmp_path / "click.wav"), bpm=120.0, seconds=6.0)
    fn = await get_media_tool("detect_beats")
    res = await fn(audio_path=src)
    assert set(res) == {"bpm", "beats"}
    assert isinstance(res["bpm"], float) and res["bpm"] > 0
    assert isinstance(res["beats"], list) and all(isinstance(t, float) for t in res["beats"])


async def test_detect_beats_tool_missing_file():
    fn = await get_media_tool("detect_beats")
    with pytest.raises(ToolError):
        await fn(audio_path="/nope/track.wav")
