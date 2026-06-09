"""FastMCP misc tools: list_voices, get_task, transliterate_hebrew."""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.errors import VideoMCPError
from video_mcp.logging_config import get_logger
from video_mcp.moderation import is_moderation_failure
from video_mcp.tools import Deps
from video_mcp.utils.transliterate import has_hebrew as _has_hebrew
from video_mcp.utils.transliterate import transliterate_hebrew as _transliterate

logger = get_logger(__name__)


def register_misc_tools(mcp: FastMCP, deps: Deps):
    """Register the misc tools and return them as a dict (for tests)."""

    @mcp.tool
    async def list_voices() -> dict[str, Any]:
        """List available ElevenLabs voices."""
        try:
            voices = await deps.eleven.list_voices()
        except VideoMCPError as exc:
            raise ToolError(str(exc)) from exc
        return {"voices": voices}

    @mcp.tool
    async def get_task(task_id: str) -> dict[str, Any]:
        """Fetch the current state of a PiAPI task."""
        try:
            result = await deps.piapi.get_task(task_id)
        except VideoMCPError as exc:
            raise ToolError(str(exc)) from exc
        out = {
            "task_id": result.task_id,
            "status": result.status,
            "video_url": result.video_url,
            "error": result.error,
            "output": result.output,
        }
        if result.is_failed:
            out["failure_reason"] = "moderation" if is_moderation_failure(result.error_message) else "other"
            out["provider_message"] = result.error_message
        return out

    @mcp.tool
    async def transliterate_hebrew(text: str) -> dict[str, Any]:
        """Transliterate Hebrew text to Latin (via LMStudio/OpenRouter LLM) for visual prompts."""
        try:
            latin = await _transliterate(text, deps.settings)
        except VideoMCPError as exc:
            raise ToolError(str(exc)) from exc
        return {
            "input": text,
            "latin": latin,
            "had_hebrew": _has_hebrew(text),
        }

    return {
        "list_voices": list_voices,
        "get_task": get_task,
        "transliterate_hebrew": transliterate_hebrew,
    }
