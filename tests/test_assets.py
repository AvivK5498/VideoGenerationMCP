"""Tests for the asset tools (upload_asset / list / get / delete)."""

from __future__ import annotations

import os
import tempfile
from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.config import Settings
from video_mcp.tools import Deps
from video_mcp.tools.assets import register_asset_tools


def _deps(piapi=None) -> Deps:
    return Deps(settings=Settings(piapi_key="pk", elevenlabs_key="ek"),
                piapi=piapi or AsyncMock(), eleven=AsyncMock())


def _tools(deps):
    return register_asset_tools(FastMCP("t"), deps)


async def test_upload_asset_url_waits_active(monkeypatch):
    piapi = AsyncMock()
    piapi.create_asset.return_value = {"asset_id": "asset-9", "status": "Processing", "expires_at": "2026-06-16"}
    piapi.wait_for_asset.return_value = {"asset_id": "asset-9", "status": "Active", "expires_at": "2026-06-16", "name": "hila"}
    tools = _tools(_deps(piapi))

    out = await tools["upload_asset"](image="https://x/face.png", name="hila", asset_type="Image")
    assert out["asset_id"] == "asset-9"
    assert out["asset_ref"] == "asset://asset-9"
    assert out["status"] == "Active"
    piapi.create_asset.assert_awaited_once()
    piapi.wait_for_asset.assert_awaited_once()


async def test_upload_asset_local_path_uploads_first(monkeypatch):
    piapi = AsyncMock()
    piapi.create_asset.return_value = {"asset_id": "asset-1", "status": "Active"}
    piapi.wait_for_asset.return_value = {"asset_id": "asset-1", "status": "Active"}
    up = AsyncMock(return_value="https://tmpfiles.org/dl/x/face.png")
    monkeypatch.setattr("video_mcp.tools.assets.uploader.upload_file", up)
    tools = _tools(_deps(piapi))

    await tools["upload_asset"](image="/tmp/face.png", name="hila")
    up.assert_awaited_once()  # local path uploaded to a public host first
    assert piapi.create_asset.await_args.kwargs["url"] == "https://tmpfiles.org/dl/x/face.png"


async def test_upload_asset_records_to_obsidian(monkeypatch):
    fd, page = tempfile.mkstemp(suffix=".md")
    with open(fd, "w", encoding="utf-8") as fh:
        fh.write("# Hila\n")
    piapi = AsyncMock()
    piapi.create_asset.return_value = {"asset_id": "asset-5", "status": "Active", "expires_at": "2026-06-16"}
    piapi.wait_for_asset.return_value = {"asset_id": "asset-5", "status": "Active", "expires_at": "2026-06-16", "name": "hila-identity"}
    tools = _tools(_deps(piapi))

    out = await tools["upload_asset"](image="https://x/f.png", name="hila-identity", influencer_page=page)
    assert "asset://asset-5" in out["recorded"]
    assert "asset://asset-5" in open(page, encoding="utf-8").read()


async def test_list_get_delete(monkeypatch):
    piapi = AsyncMock()
    piapi.list_assets.return_value = {"items": [], "quota": {"used": 0, "limit": 500}}
    piapi.get_asset.return_value = {"asset_id": "a1", "status": "Active"}
    piapi.delete_asset.return_value = True
    tools = _tools(_deps(piapi))

    assert "quota" in (await tools["list_assets"]())
    assert (await tools["get_asset"](asset_id="a1"))["status"] == "Active"
    assert (await tools["delete_asset"](asset_id="a1"))["deleted"] == "a1"
