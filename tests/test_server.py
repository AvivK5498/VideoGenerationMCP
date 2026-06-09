"""Tests for video_mcp.server.build_server."""

from __future__ import annotations

from fastmcp import FastMCP

from video_mcp.config import Settings
from video_mcp.server import build_server

EXPECTED_TOOLS = {
    "generate_kling_video",
    "generate_seedance_video",
    "generate_seedance_first_last",
    "generate_elevenlabs_voiceover",
    "list_voices",
    "get_task",
    "transliterate_hebrew",
    "upload_asset",
    "list_assets",
    "get_asset",
    "delete_asset",
}


def _dummy_settings() -> Settings:
    return Settings(piapi_key="dummy-piapi", elevenlabs_key="dummy-eleven")


def test_build_server_returns_fastmcp() -> None:
    mcp = build_server(_dummy_settings())
    assert isinstance(mcp, FastMCP)
    assert mcp.name == "video-mcp"


def test_build_server_defaults_to_get_settings() -> None:
    # settings=None must not raise (build does not touch the keys).
    mcp = build_server()
    assert isinstance(mcp, FastMCP)


async def test_build_server_registers_expected_tools() -> None:
    mcp = build_server(_dummy_settings())
    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"
