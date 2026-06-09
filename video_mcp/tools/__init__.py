"""Tool registration package.

`Deps` bundles the constructed clients + settings so tools are testable with
injected mocks. Tool modules import `Deps` from here and expose
`register_<area>_tools(mcp, deps)`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid import cycle / hard dep at module import time
    from video_mcp.clients.elevenlabs import ElevenLabsClient
    from video_mcp.clients.piapi import PiapiClient
    from video_mcp.config import Settings


@dataclass
class Deps:
    settings: "Settings"
    piapi: "PiapiClient"
    eleven: "ElevenLabsClient"
