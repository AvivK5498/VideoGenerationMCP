"""FastMCP tools: local multi-clip assembly (stitch_videos, split_audio, extract_frame).

A 30s ad = several provider jobs (Seedance caps at 15s/clip). These tools own the
assembly steps so agents never shell out to ffmpeg themselves:
master VO -> split_audio at sentence boundaries -> one generate_seedance_video per
segment (audio_path) -> extract_frame to bridge clips -> stitch_videos for the final.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.errors import VideoMCPError
from video_mcp.logging_config import get_logger
from video_mcp.tools import Deps
from video_mcp.utils import media as media_mod
from video_mcp.utils import uploader as uploader_mod
from video_mcp.utils.download import download

logger = get_logger(__name__)


async def _localize(source: str, suffix: str) -> str:
    """Return a local path for `source`, downloading it when it is a URL."""
    if not source.startswith(("http://", "https://")):
        return source
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="media_dl_")
    os.close(fd)
    await download(source, path)
    return path


def register_media_tools(mcp: FastMCP, deps: Deps) -> None:
    """Register the local assembly tools on `mcp`."""

    @mcp.tool
    async def stitch_videos(
        videos: list[str],
        output_path: str,
    ) -> dict[str, Any]:
        """Concatenate >= 2 clips (local paths or URLs, in order) into one MP4.

        Hard cuts; every clip is normalized to the first clip's resolution/fps so
        mixed specs concat cleanly. Use this for the final assembly of a multi-clip
        ad — do not shell out to ffmpeg concat yourself.
        """
        try:
            paths = [await _localize(v, ".mp4") for v in videos]
            out = media_mod.stitch_videos(
                paths, output_path,
                ffmpeg_bin=deps.settings.ffmpeg_bin, ffprobe_bin=deps.settings.ffprobe_bin,
            )
            duration = media_mod.probe_duration(out, ffprobe_bin=deps.settings.ffprobe_bin)
        except VideoMCPError as err:
            raise ToolError(str(err)) from err
        return {"output_path": out, "duration_s": round(duration, 3), "clips": len(videos)}

    @mcp.tool
    async def split_audio(
        audio_path: str,
        split_points_s: list[float],
        output_dir: str | None = None,
    ) -> dict[str, Any]:
        """Cut a master voiceover mp3 at `split_points_s` (seconds, strictly increasing).

        Returns len(points)+1 ordered segments with paths and durations. Workflow for
        ads longer than one clip: generate ONE master VO with
        generate_elevenlabs_voiceover (with_timestamps=true), pick sentence-boundary
        timestamps, split here, then pass each segment's path as `audio_path` to its
        own generate_seedance_video call. Each segment must fit its clip duration.
        """
        out_dir = output_dir or tempfile.mkdtemp(prefix="vo_segments_")
        try:
            segments = media_mod.split_audio(
                audio_path, split_points_s, out_dir,
                ffmpeg_bin=deps.settings.ffmpeg_bin, ffprobe_bin=deps.settings.ffprobe_bin,
            )
        except VideoMCPError as err:
            raise ToolError(str(err)) from err
        return {"segments": segments, "output_dir": out_dir}

    @mcp.tool
    async def mix_music_into_video(
        video: str,
        music: str,
        output_path: str,
        music_gain_db: float = -20.0,
        duck: bool = True,
    ) -> dict[str, Any]:
        """Lay a music bed under a video's existing speech/ambience audio.

        The music loops to the video's length at `music_gain_db` (default -20 dB —
        barely-there), and with duck=true is side-chain compressed by the speech so
        it dips whenever someone talks. Music for speech ads is complementary, not
        the main event — keep the gain low. Video stream is copied untouched.
        Inputs may be URLs (downloaded first).
        """
        try:
            v = await _localize(video, ".mp4")
            m = await _localize(music, ".mp3")
            out = media_mod.mix_music_into_video(
                v, m, output_path, music_gain_db=music_gain_db, duck=duck,
                ffmpeg_bin=deps.settings.ffmpeg_bin,
            )
            duration = media_mod.probe_duration(out, ffprobe_bin=deps.settings.ffprobe_bin)
        except VideoMCPError as err:
            raise ToolError(str(err)) from err
        return {"output_path": out, "duration_s": round(duration, 3),
                "music_gain_db": music_gain_db, "duck": duck}

    @mcp.tool
    async def host_file(path: str) -> dict[str, Any]:
        """Host a local file on a temporary public URL (tmpfiles, ~1h retention).

        Use for non-asset references that need a provider-fetchable URL: a local
        ElevenLabs mp3 going into `audio_urls` (English reference-audio lip-sync),
        a product/room photo for `other_image_urls`, etc. Human/persona refs do NOT
        go here — register those with upload_asset instead.
        """
        if not os.path.isfile(path):
            raise ToolError(f"file not found: {path}")
        try:
            url = await uploader_mod.upload_file(path, upload_url=deps.settings.tmpfiles_upload_url)
        except VideoMCPError as err:
            raise ToolError(str(err)) from err
        return {"url": url, "path": path}

    @mcp.tool
    async def extract_frame(
        video: str,
        time_s: float | None = None,
        upload: bool = False,
    ) -> dict[str, Any]:
        """Save one frame of a video (local path or URL) as PNG; default = LAST frame.

        Use the last frame of clip N as `image_first` of clip N+1
        (generate_seedance_first_last) to bridge multi-clip continuity. With
        upload=true the frame is also hosted on a temporary public URL so it can be
        passed as a reference directly.
        """
        fd, frame_path = tempfile.mkstemp(suffix=".png", prefix="frame_")
        os.close(fd)
        try:
            local = await _localize(video, ".mp4")
            media_mod.extract_frame(local, frame_path, time_s=time_s, ffmpeg_bin=deps.settings.ffmpeg_bin)
        except VideoMCPError as err:
            raise ToolError(str(err)) from err
        out: dict[str, Any] = {"frame_path": frame_path, "time_s": time_s if time_s is not None else "last"}
        if upload:
            try:
                out["frame_url"] = await uploader_mod.upload_file(
                    frame_path, upload_url=deps.settings.tmpfiles_upload_url
                )
            except VideoMCPError as err:
                raise ToolError(str(err)) from err
        return out
