"""Tests for caption grouping, overlay rendering, and the burn_captions tool."""

from __future__ import annotations

import os
import shutil
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.config import Settings
from video_mcp.tools import Deps
from video_mcp.tools.captions import register_caption_tools
from video_mcp.utils.captions import _FONT_CANDIDATES, group_words, render_caption_overlay

_HAS_FONT = any(os.path.isfile(f) for f in _FONT_CANDIDATES)
_HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


# -------------------------------------------------------------------- grouping

def _w(text, start, end, type_="word"):
    return {"text": text, "start": start, "end": end, "type": type_}


def test_group_words_chunks_and_times():
    words = [_w("one", 0.0, 0.3), _w(" ", 0.3, 0.35, "spacing"), _w("two", 0.35, 0.6),
             _w("three", 0.6, 0.9), _w("four", 0.9, 1.2), _w("five", 1.25, 1.5)]
    chunks = group_words(words, max_words=4)
    assert [c["text"] for c in chunks] == ["one two three four", "five"]
    assert chunks[0]["start"] == 0.0
    assert chunks[0]["end"] <= chunks[1]["start"]  # no overlap


def test_group_words_splits_on_gap():
    words = [_w("hello", 0.0, 0.4), _w("world", 2.0, 2.4)]  # 1.6s gap
    chunks = group_words(words, max_words=4, max_gap_s=0.6)
    assert len(chunks) == 2


def test_group_words_min_duration():
    chunks = group_words([_w("hi", 1.0, 1.1)], min_dur_s=0.5)
    assert chunks[0]["end"] >= 1.5


def test_group_words_empty():
    assert group_words([]) == []


# -------------------------------------------------------------------- overlay

@pytest.mark.skipif(not _HAS_FONT, reason="no caption font on this system")
def test_render_overlay_hebrew_and_english(tmp_path):
    out = render_caption_overlay(720, 1280, "חופשה? Flycard", {}, str(tmp_path / "c.png"))
    assert os.path.getsize(out) > 0


@pytest.mark.skipif(not _HAS_FONT, reason="no caption font on this system")
def test_render_overlay_wraps_long_text(tmp_path):
    long = "a very long caption line that cannot possibly fit on one line " * 3
    out = render_caption_overlay(720, 1280, long, {"font_px": 64}, str(tmp_path / "c.png"))
    assert os.path.getsize(out) > 0


# ----------------------------------------------------------------------- tool

def make_deps(eleven=None, piapi=None) -> Deps:
    s = Settings()
    s.piapi_key = "pk"
    s.elevenlabs_key = "ek"
    return Deps(settings=s, piapi=piapi or AsyncMock(), eleven=eleven or AsyncMock())


async def get_tool(deps: Deps):
    mcp = FastMCP("test")
    register_caption_tools(mcp, deps)
    tool = await mcp.get_tool("burn_captions")
    return tool.fn


async def test_burn_captions_full_flow(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    eleven = AsyncMock()
    eleven.transcribe.return_value = {"words": [_w("שלום", 0.0, 0.5), _w("עולם", 0.5, 1.0)]}
    monkeypatch.setattr("video_mcp.tools.captions.carrier_mod.extract_audio", MagicMock())
    monkeypatch.setattr(
        "video_mcp.tools.captions.media_mod.probe_video_spec", MagicMock(return_value=(720, 1280, "24"))
    )
    render = MagicMock(side_effect=lambda w, h, t, s, p: p)
    monkeypatch.setattr("video_mcp.tools.captions.captions_mod.render_caption_overlay", render)
    burn = MagicMock(side_effect=lambda v, o, out, **kw: out)
    monkeypatch.setattr("video_mcp.tools.captions.captions_mod.burn_caption_overlays", burn)
    fn = await get_tool(make_deps(eleven=eleven))

    res = await fn(video=str(video), output_path=str(tmp_path / "out.mp4"))
    eleven.transcribe.assert_awaited_once()
    assert res["caption_count"] == 1  # two words, one chunk
    assert res["captions"][0]["text"] == "שלום עולם"
    assert burn.call_args.args[2] == str(tmp_path / "out.mp4")


async def test_burn_captions_explicit_captions_skip_scribe(monkeypatch, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"VID")
    eleven = AsyncMock()
    monkeypatch.setattr(
        "video_mcp.tools.captions.media_mod.probe_video_spec", MagicMock(return_value=(720, 1280, "24"))
    )
    monkeypatch.setattr(
        "video_mcp.tools.captions.captions_mod.render_caption_overlay",
        MagicMock(side_effect=lambda w, h, t, s, p: p),
    )
    monkeypatch.setattr(
        "video_mcp.tools.captions.captions_mod.burn_caption_overlays",
        MagicMock(side_effect=lambda v, o, out, **kw: out),
    )
    fn = await get_tool(make_deps(eleven=eleven))

    res = await fn(video=str(video), captions=[{"text": "hi", "start": 0, "end": 1}],
                   output_path=str(tmp_path / "out.mp4"))
    eleven.transcribe.assert_not_called()
    assert res["caption_count"] == 1


async def test_burn_captions_requires_video_or_task():
    fn = await get_tool(make_deps())
    with pytest.raises(ToolError) as ei:
        await fn()
    assert "task_id" in str(ei.value)


async def test_burn_captions_task_without_video_errors():
    piapi = AsyncMock()
    piapi.get_task.return_value = MagicMock(video_url=None, status="processing")
    fn = await get_tool(make_deps(piapi=piapi))
    with pytest.raises(ToolError) as ei:
        await fn(task_id="t1")
    assert "no video yet" in str(ei.value)
