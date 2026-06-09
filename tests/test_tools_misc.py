"""Tests for tools/misc.py."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.config import Settings
from video_mcp.errors import PiapiError
from video_mcp.schemas.common import TaskResult
from video_mcp.tools import Deps
from video_mcp.tools.misc import register_misc_tools


def _settings() -> Settings:
    return Settings(piapi_key="pk", elevenlabs_key="ek")


def _deps() -> Deps:
    return Deps(settings=_settings(), piapi=AsyncMock(), eleven=AsyncMock())


def _tools(deps: Deps) -> dict:
    return register_misc_tools(FastMCP("test"), deps)


@respx.mock
async def test_transliterate_hebrew_with_hebrew():
    deps = _deps()
    tools = _tools(deps)
    respx.post(f"{deps.settings.lmstudio_base_url}/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "shalom world"}}]})
    )
    out = await tools["transliterate_hebrew"](text="שלום world")

    assert out["input"] == "שלום world"
    assert out["had_hebrew"] is True
    assert out["latin"] == "shalom world"
    # result must contain no Hebrew characters
    assert all(not (0x0590 <= ord(c) <= 0x05FF) for c in out["latin"])


async def test_transliterate_hebrew_no_hebrew():
    deps = _deps()
    tools = _tools(deps)
    out = await tools["transliterate_hebrew"](text="hello 123")
    assert out["had_hebrew"] is False
    assert out["latin"] == "hello 123"


async def test_get_task_maps_fields():
    deps = _deps()
    result = TaskResult(
        task_id="t-9", status="completed", model="kling",
        task_type="omni_video_generation",
        output={"video": "https://x/out.mp4"}, error=None, raw={},
    )
    deps.piapi.get_task = AsyncMock(return_value=result)
    tools = _tools(deps)
    out = await tools["get_task"](task_id="t-9")

    assert out["task_id"] == "t-9"
    assert out["status"] == "completed"
    assert out["video_url"] == "https://x/out.mp4"
    assert out["output"] == {"video": "https://x/out.mp4"}
    assert out["error"] is None
    deps.piapi.get_task.assert_awaited_once_with("t-9")


async def test_get_task_provider_error_raises_toolerror():
    deps = _deps()
    deps.piapi.get_task = AsyncMock(side_effect=PiapiError("boom", code=500))
    tools = _tools(deps)
    with pytest.raises(ToolError):
        await tools["get_task"](task_id="t-9")


async def test_list_voices():
    deps = _deps()
    voices = [{"voice_id": "v1", "name": "Alice"}, {"voice_id": "v2", "name": "Bob"}]
    deps.eleven.list_voices = AsyncMock(return_value=voices)
    tools = _tools(deps)
    out = await tools["list_voices"]()

    assert out["voices"] == voices
    deps.eleven.list_voices.assert_awaited_once()
