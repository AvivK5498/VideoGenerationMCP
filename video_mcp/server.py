"""FastMCP server assembly for video-mcp.

`build_server` constructs the runtime dependencies (Settings, the PiAPI and
ElevenLabs clients, the `Deps` bundle), instantiates a `FastMCP` instance, and
registers every tool group. `main` builds the server and runs it over stdio.
"""

from __future__ import annotations

from fastmcp import FastMCP

from video_mcp.clients.elevenlabs import ElevenLabsClient
from video_mcp.clients.piapi import PiapiClient
from video_mcp.config import Settings, get_settings
from video_mcp.logging_config import get_logger
from video_mcp.tools import Deps
from video_mcp.tools.elevenlabs import register_elevenlabs_tools
from video_mcp.tools.kling import register_kling_tools
from video_mcp.tools.assets import register_asset_tools
from video_mcp.tools.captions import register_caption_tools
from video_mcp.tools.media import register_media_tools
from video_mcp.tools.misc import register_misc_tools
from video_mcp.tools.seedance import register_seedance_tools
from video_mcp.tools.seedance_flf import register_seedance_flf_tools

logger = get_logger(__name__)


def build_server(settings: Settings | None = None) -> FastMCP:
    """Construct deps + a fully-registered FastMCP server instance."""
    settings = settings if settings is not None else get_settings()
    piapi = PiapiClient(settings)
    eleven = ElevenLabsClient(settings)
    deps = Deps(settings=settings, piapi=piapi, eleven=eleven)

    mcp = FastMCP("video-mcp")
    register_kling_tools(mcp, deps)
    register_seedance_tools(mcp, deps)
    register_seedance_flf_tools(mcp, deps)
    register_elevenlabs_tools(mcp, deps)
    register_misc_tools(mcp, deps)
    register_asset_tools(mcp, deps)
    register_media_tools(mcp, deps)
    register_caption_tools(mcp, deps)

    logger.info("video-mcp server built")
    return mcp


def main() -> None:
    """Build the server and run it over the default (stdio) transport."""
    mcp = build_server()
    mcp.run()


if __name__ == "__main__":
    main()
