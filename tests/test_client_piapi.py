"""Tests for PiapiClient — self-contained (own fixtures, respx mocks)."""

from __future__ import annotations

import httpx
import pytest
import respx

from video_mcp.clients.piapi import PiapiClient
from video_mcp.config import Settings
from video_mcp.errors import PiapiError

BASE = "https://api.piapi.test/api/v1"


def make_settings() -> Settings:
    s = Settings()
    s.piapi_key = "test-piapi-key"
    s.piapi_base = BASE
    s.poll_interval_s = 0.0
    s.poll_timeout_s = 5.0
    return s


def make_client(http: httpx.AsyncClient) -> PiapiClient:
    return PiapiClient(make_settings(), client=http)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr("video_mcp.clients.piapi.asyncio.sleep", AsyncMock())


def _task_body(status: str = "completed", *, with_video: bool = True) -> dict:
    output = {"video": "https://cdn.test/out.mp4"} if with_video else {}
    return {
        "code": 200,
        "message": "success",
        "data": {
            "task_id": "abc123",
            "status": status,
            "model": "kling",
            "task_type": "omni_video_generation",
            "output": output,
        },
    }


@respx.mock
async def test_create_task_success():
    respx.post(f"{BASE}/task").mock(return_value=httpx.Response(200, json=_task_body("pending")))
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        result = await client.create_task(
            model="kling", task_type="omni_video_generation", input={"prompt": "hi"}
        )
    assert result.task_id == "abc123"
    assert result.normalized_status == "pending"


@respx.mock
async def test_create_task_includes_config_and_headers():
    route = respx.post(f"{BASE}/task").mock(return_value=httpx.Response(200, json=_task_body()))
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        await client.create_task(
            model="kling", task_type="t", input={"p": 1}, config={"service_mode": "public"}
        )
    sent = route.calls.last.request
    assert sent.headers["x-api-key"] == "test-piapi-key"
    import json as _json

    body = _json.loads(sent.content)
    assert body["config"] == {"service_mode": "public"}


@respx.mock
async def test_create_task_retries_5xx_then_succeeds():
    route = respx.post(f"{BASE}/task").mock(side_effect=[
        httpx.Response(504, text="gateway timeout"),
        httpx.Response(502, text="bad gateway"),
        httpx.Response(200, json=_task_body(status="pending")),
    ])
    async with httpx.AsyncClient() as http:
        result = await make_client(http).create_task(model="kling", task_type="t", input={})
    assert result.task_id == "abc123"
    assert route.call_count == 3  # two 5xx retries, then success


@respx.mock
async def test_create_task_error_http_500_with_body_message():
    err = {"code": 500, "message": "internal boom", "data": None}
    respx.post(f"{BASE}/task").mock(return_value=httpx.Response(500, json=err))
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        with pytest.raises(PiapiError) as ei:
            await client.create_task(model="kling", task_type="t", input={})
    assert "internal boom" in str(ei.value)
    assert ei.value.code == 500


@respx.mock
async def test_create_task_error_code_not_200_with_data_error_message():
    err = {
        "code": 400,
        "message": "fallback",
        "data": {"error": {"message": "bad prompt"}},
    }
    respx.post(f"{BASE}/task").mock(return_value=httpx.Response(200, json=err))
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        with pytest.raises(PiapiError) as ei:
            await client.create_task(model="kling", task_type="t", input={})
    assert "bad prompt" in str(ei.value)


@respx.mock
async def test_get_task():
    respx.get(f"{BASE}/task/abc123").mock(return_value=httpx.Response(200, json=_task_body("completed")))
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        result = await client.get_task("abc123")
    assert result.is_terminal
    assert result.video_url == "https://cdn.test/out.mp4"


@respx.mock
async def test_wait_for_task_pending_then_completed():
    respx.get(f"{BASE}/task/abc123").mock(
        side_effect=[
            httpx.Response(200, json=_task_body("processing", with_video=False)),
            httpx.Response(200, json=_task_body("completed")),
        ]
    )
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        result = await client.wait_for_task("abc123", interval=0.0)
    assert result.is_terminal
    assert result.video_url == "https://cdn.test/out.mp4"


@respx.mock
async def test_wait_for_task_transient_parse_error_keeps_polling():
    # First a non-JSON / malformed body (parse error), then a completed task.
    respx.get(f"{BASE}/task/abc123").mock(
        side_effect=[
            httpx.Response(200, json={"data": {"no_task_id": True}}),
            httpx.Response(200, json=_task_body("completed")),
        ]
    )
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        result = await client.wait_for_task("abc123", interval=0.0)
    assert result.is_terminal


@respx.mock
async def test_wait_for_task_timeout():
    respx.get(f"{BASE}/task/abc123").mock(
        return_value=httpx.Response(200, json=_task_body("processing", with_video=False))
    )
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        with pytest.raises(PiapiError) as ei:
            await client.wait_for_task("abc123", interval=0.0, timeout=0.0)
    assert "Timed out" in str(ei.value)
    assert ei.value.code == "timeout"


# --- private assets ---

@respx.mock
async def test_create_asset_retries_5xx_then_202():
    route = respx.post(f"{BASE}/asset/upload").mock(side_effect=[
        httpx.Response(500, text="ark boom"),
        httpx.Response(202, json={"asset_id": "asset-1", "status": "Processing", "expires_at": "2026-06-16"}),
    ])
    async with httpx.AsyncClient() as http:
        out = await make_client(http).create_asset(url="https://x/a.png", asset_type="Image", name="a")
    assert out["asset_id"] == "asset-1"
    assert route.call_count == 2


@respx.mock
async def test_wait_for_asset_processing_then_active():
    respx.get(f"{BASE}/asset/asset-1").mock(side_effect=[
        httpx.Response(200, json={"asset_id": "asset-1", "status": "Processing"}),
        httpx.Response(200, json={"asset_id": "asset-1", "status": "Active"}),
    ])
    async with httpx.AsyncClient() as http:
        out = await make_client(http).wait_for_asset("asset-1", interval=0)
    assert out["status"] == "Active"


@respx.mock
async def test_wait_for_asset_failed_raises():
    respx.get(f"{BASE}/asset/asset-x").mock(
        return_value=httpx.Response(200, json={"asset_id": "asset-x", "status": "Failed",
                                               "error": {"message": "bad image"}}))
    async with httpx.AsyncClient() as http:
        with pytest.raises(PiapiError):
            await make_client(http).wait_for_asset("asset-x", interval=0)


@respx.mock
async def test_list_and_delete_asset():
    respx.get(f"{BASE}/asset/list").mock(return_value=httpx.Response(200, json={"items": [], "quota": {"used": 0}}))
    respx.delete(f"{BASE}/asset/asset-1").mock(return_value=httpx.Response(204))
    async with httpx.AsyncClient() as http:
        c = make_client(http)
        assert "quota" in await c.list_assets()
        assert await c.delete_asset("asset-1") is True
