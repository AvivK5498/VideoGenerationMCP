"""FastMCP tool: generate_kling_video (Kling Omni via PiAPI)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from video_mcp.content_gate import assert_prompt_clean
from video_mcp.errors import VideoMCPError
from video_mcp.logging_config import get_logger, redact
from video_mcp.schemas.kling import KlingVideoRequest
from video_mcp.tools import Deps

logger = get_logger(__name__)


def register_kling_tools(mcp: FastMCP, deps: Deps):
    """Register `generate_kling_video` and return the underlying function (for tests)."""

    @mcp.tool
    async def generate_kling_video(
        prompt: str | None = None,
        shots: list[dict[str, Any]] | None = None,
        version: str = "3.0",
        resolution: str = "720p",
        duration: int = 5,
        aspect_ratio: str = "16:9",
        enable_audio: bool = True,
        images: list[str] | None = None,
        video: str | None = None,
        keep_original_audio: bool = False,
        service_mode: str | None = None,
        content_check: bool = True,
        wait: bool = False,
    ) -> dict[str, Any]:
        """Generate a Kling Omni video (single prompt or multi-shot)."""
        # If a video reference is set, force enable_audio off unless the caller
        # explicitly wants to keep the original audio track.
        if video is not None and not keep_original_audio:
            enable_audio = False

        scanned = " ".join(filter(None, [prompt] + [s.get("prompt", "") for s in (shots or [])]))
        try:
            await assert_prompt_clean(scanned, deps.settings, use_llm=content_check)
            req = KlingVideoRequest(
                prompt=prompt,
                shots=shots,
                version=version,
                resolution=resolution,
                duration=duration,
                aspect_ratio=aspect_ratio,
                enable_audio=enable_audio,
                images=images,
                video=video,
                keep_original_audio=keep_original_audio,
                service_mode=service_mode,
            )
        except (ValidationError, VideoMCPError) as exc:
            raise ToolError(str(exc)) from exc

        config = {"service_mode": req.service_mode} if req.service_mode else None
        try:
            result = await deps.piapi.create_task(
                model="kling",
                task_type="omni_video_generation",
                input=req.to_piapi_input(),
                config=config,
            )
            if wait:
                result = await deps.piapi.wait_for_task(result.task_id)
        except VideoMCPError as exc:
            raise ToolError(str(exc)) from exc

        echo = redact(req.model_dump())
        logger.info("generate_kling_video -> %s", result.task_id)
        return {
            "task_id": result.task_id,
            "status": result.status,
            "video_url": result.video_url,
            "request_echo": echo,
        }

    return generate_kling_video
