"""FastMCP tool: burn word-timed captions onto a generated video (burn_captions).

Pipeline: resolve video (path / URL / task_id) -> extract audio -> ElevenLabs
Scribe word timestamps -> group into caption chunks -> PIL overlays (vault
styling, bidi-correct Hebrew) -> ffmpeg burn. Captions reflect what is ACTUALLY
spoken in the generated audio, not the script.
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
from video_mcp.utils import captions as captions_mod
from video_mcp.utils import carrier as carrier_mod
from video_mcp.utils import media as media_mod
from video_mcp.utils.download import download

logger = get_logger(__name__)


def register_caption_tools(mcp: FastMCP, deps: Deps) -> None:
    """Register the captioning tool on `mcp`."""

    @mcp.tool
    async def burn_captions(
        video: str | None = None,
        task_id: str | None = None,
        language: str = "he",
        captions: list[dict] | None = None,
        max_words: int = 4,
        style: dict | None = None,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Burn word-timed captions onto a video (local path, URL, or PiAPI task_id).

        Default flow transcribes the video's OWN audio with ElevenLabs Scribe (word
        timestamps), groups words into short chunks (max_words per caption), and
        burns styled overlays: white bold, black stroke, drop shadow, centered
        low-third, Hebrew rendered in correct RTL visual order (English/brand
        tokens stay LTR). Pass `captions` ([{text, start, end}]) to skip Scribe and
        burn exact chunks; `style` overrides (font_px, y_pct, fill, crf, font_path...).
        Run AFTER verify_generated_audio passes and BEFORE stitch_videos.
        """
        if not video and not task_id:
            raise ToolError("provide `video` (path/URL) or `task_id`.")
        if not video:
            try:
                result = await deps.piapi.get_task(task_id)
            except VideoMCPError as err:
                raise ToolError(str(err)) from err
            video = result.video_url
            if not video:
                raise ToolError(f"task {task_id} has no video yet (status={result.status}).")
        if video.startswith(("http://", "https://")):
            vfd, local = tempfile.mkstemp(suffix=".mp4", prefix="caption_src_")
            os.close(vfd)
            await download(video, local)
            video = local
        if not os.path.isfile(video):
            raise ToolError(f"video not found: {video}")

        if captions is None:
            afd, audio = tempfile.mkstemp(suffix=".mp3", prefix="caption_audio_")
            os.close(afd)
            try:
                carrier_mod.extract_audio(video, audio, ffmpeg_bin=deps.settings.ffmpeg_bin)
                scribe = await deps.eleven.transcribe(audio, language_code=language)
            except VideoMCPError as err:
                raise ToolError(str(err)) from err
            captions = captions_mod.group_words(scribe.get("words") or [], max_words=max_words)
            if not captions:
                raise ToolError("Scribe returned no words — nothing to caption.")

        try:
            width, height, _fps = media_mod.probe_video_spec(video, ffprobe_bin=deps.settings.ffprobe_bin)
        except VideoMCPError as err:
            raise ToolError(str(err)) from err

        st = style or {}
        overlay_dir = tempfile.mkdtemp(prefix="caption_overlays_")
        overlays = []
        try:
            for i, cap in enumerate(captions, start=1):
                png = os.path.join(overlay_dir, f"{i:02d}.png")
                captions_mod.render_caption_overlay(width, height, cap["text"], st, png)
                overlays.append({"png": png, "start": cap["start"], "end": cap["end"]})

            if not output_path:
                ofd, output_path = tempfile.mkstemp(suffix=".mp4", prefix="captioned_")
                os.close(ofd)
            captions_mod.burn_caption_overlays(
                video, overlays, output_path,
                crf=int(st.get("crf", captions_mod.DEFAULT_STYLE["crf"])),
                ffmpeg_bin=deps.settings.ffmpeg_bin,
            )
        except VideoMCPError as err:
            raise ToolError(str(err)) from err

        return {"output_path": output_path, "captions": captions, "caption_count": len(captions)}
