"""Tests for tools/kling.py and tools/seedance_flf.py."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.config import Settings
from video_mcp.schemas.common import TaskResult
from video_mcp.tools import Deps
from video_mcp.tools.kling import register_kling_tools


@pytest.fixture(autouse=True)
def _stub_llm_gate(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr("video_mcp.content_gate.chat_with_fallback", AsyncMock(return_value="OK"))
from video_mcp.tools.seedance_flf import register_seedance_flf_tools


def _settings() -> Settings:
    return Settings(piapi_key="pk", elevenlabs_key="ek")


def _result(**kw) -> TaskResult:
    base = dict(task_id="task-123", status="pending", model="kling",
                task_type="omni_video_generation", output=None, error=None, raw={})
    base.update(kw)
    return TaskResult(**base)


def _deps(create_return: TaskResult | None = None) -> Deps:
    piapi = AsyncMock()
    piapi.create_task = AsyncMock(return_value=create_return or _result())
    eleven = AsyncMock()
    return Deps(settings=_settings(), piapi=piapi, eleven=eleven)


def _register_kling(deps: Deps):
    return register_kling_tools(FastMCP("test"), deps)


async def test_single_shot_success():
    deps = _deps()
    tool = _register_kling(deps)
    out = await tool(prompt="a cat on a skateboard", duration=5)

    assert out["task_id"] == "task-123"
    assert out["status"] == "pending"
    deps.piapi.create_task.assert_awaited_once()
    kwargs = deps.piapi.create_task.await_args.kwargs
    assert kwargs["model"] == "kling"
    assert kwargs["task_type"] == "omni_video_generation"
    assert kwargs["input"]["prompt"] == "a cat on a skateboard"
    assert kwargs["input"]["duration"] == 5
    assert "multi_shots" not in kwargs["input"]


async def test_multi_shot_success():
    deps = _deps()
    tool = _register_kling(deps)
    shots = [{"prompt": "shot one", "duration": 5}, {"prompt": "shot two", "duration": 5}]
    out = await tool(shots=shots)

    assert out["task_id"] == "task-123"
    kwargs = deps.piapi.create_task.await_args.kwargs
    ms = kwargs["input"]["multi_shots"]
    assert len(ms) == 2
    assert ms[0] == {"prompt": "shot one", "duration": 5}
    assert "prompt" not in kwargs["input"]


async def test_multi_shot_too_many_shots_raises():
    deps = _deps()
    tool = _register_kling(deps)
    shots = [{"prompt": f"shot {i}", "duration": 1} for i in range(7)]
    with pytest.raises(ToolError):
        await tool(shots=shots)
    deps.piapi.create_task.assert_not_awaited()


async def test_multi_shot_sum_exceeds_15_raises():
    deps = _deps()
    tool = _register_kling(deps)
    shots = [{"prompt": f"shot {i}", "duration": 8} for i in range(2)]  # sum 16
    with pytest.raises(ToolError):
        await tool(shots=shots)
    deps.piapi.create_task.assert_not_awaited()


async def test_video_forces_audio_off_unless_keep_original():
    deps = _deps()
    tool = _register_kling(deps)
    await tool(prompt="scene @video", video="https://x/v.mp4")
    kwargs = deps.piapi.create_task.await_args.kwargs
    assert kwargs["input"]["enable_audio"] is False


async def test_video_keep_original_audio_keeps_audio():
    deps = _deps()
    tool = _register_kling(deps)
    await tool(prompt="scene @video", video="https://x/v.mp4", keep_original_audio=True, enable_audio=True)
    kwargs = deps.piapi.create_task.await_args.kwargs
    assert kwargs["input"]["enable_audio"] is True
    assert kwargs["input"]["keep_original_audio"] is True


async def test_no_prompt_no_shots_raises():
    deps = _deps()
    tool = _register_kling(deps)
    with pytest.raises(ToolError):
        await tool()


async def test_seedance_flf_success():
    deps = _deps(_result(task_type="video_generation", model="seedance"))
    tool = register_seedance_flf_tools(FastMCP("test"), deps)
    out = await tool(prompt="walk forward", image_first="https://x/a.png",
                     image_last="https://x/b.png", duration=10)

    assert out["task_id"] == "task-123"
    assert out["mode"] == "first_last_frames"
    assert out["task_type"] == "seedance-2"
    kwargs = deps.piapi.create_task.await_args.kwargs
    # FLF must route under the Seedance model task_type, NOT a hardcoded value.
    assert kwargs["task_type"] == "seedance-2"
    assert "task_type" not in kwargs["input"]
    assert kwargs["input"]["image_urls"] == ["https://x/a.png", "https://x/b.png"]
    assert kwargs["input"]["mode"] == "first_last_frames"


async def test_seedance_flf_bad_duration_raises():
    deps = _deps()
    tool = register_seedance_flf_tools(FastMCP("test"), deps)
    with pytest.raises(ToolError):
        await tool(prompt="p", image_first="https://x/a.png", duration=7)
