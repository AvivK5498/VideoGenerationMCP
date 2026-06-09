"""FastMCP tool: generate_seedance_first_last (Seedance first/last frames)."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from video_mcp.errors import VideoMCPError
from video_mcp.logging_config import get_logger
from video_mcp.schemas.seedance import SeedanceVideoRequest
from video_mcp.tools import Deps

logger = get_logger(__name__)


def register_seedance_flf_tools(mcp: FastMCP, deps: Deps):
    """Register `generate_seedance_first_last` and return the underlying function."""

    @mcp.tool
    async def generate_seedance_first_last(
        prompt: str,
        image_first: str,
        image_last: str | None = None,
        duration: int = 5,
        resolution: str = "720p",
        task_type: str = "seedance-2",
        service_mode: str | None = None,
        wait: bool = False,
    ) -> dict[str, Any]:
        """Generate a Seedance video from a first (and optional last) frame image."""
        image_urls = [image_first] + ([image_last] if image_last else [])
        try:
            req = SeedanceVideoRequest(
                prompt=prompt,
                task_type=task_type,
                mode="first_last_frames",
                duration=duration,
                resolution=resolution,
                aspect_ratio="auto",
                image_urls=image_urls,
                service_mode=service_mode,
            )
        except ValidationError as exc:
            raise ToolError(str(exc)) from exc

        config = {"service_mode": req.service_mode} if req.service_mode else None
        try:
            result = await deps.piapi.create_task(
                model="seedance",
                task_type=req.task_type,
                input=req.to_piapi_input(),
                config=config,
            )
            if wait:
                result = await deps.piapi.wait_for_task(result.task_id)
        except VideoMCPError as exc:
            raise ToolError(str(exc)) from exc

        logger.info("generate_seedance_first_last -> %s", result.task_id)
        return {
            "task_id": result.task_id,
            "status": result.status,
            "video_url": result.video_url,
            "mode": req.mode,
            "task_type": req.task_type,
        }

    return generate_seedance_first_last
