"""Demo: a single-shot Kling Omni clip through the MCP tools.

Uploads a reference image to a temporary public host, then generates a 5s Kling Omni
clip referencing it as @image_1.

Env:
  PIAPI_KEY                - required
  REFERENCE_IMAGE          - path or public URL to a reference image (required)

Run: uv run python scripts/demo_kling.py
"""

import asyncio
import os

from fastmcp import Client

from video_mcp.clients.piapi import PiapiClient
from video_mcp.config import get_settings
from video_mcp.server import build_server
from video_mcp.utils.download import download
from video_mcp.utils.uploader import upload_file

REFERENCE_IMAGE = os.environ["REFERENCE_IMAGE"]
PROMPT = ("Use @image_1 as the identity and style reference, not a direct copy, for a fictional adult "
          "creator: a confident adult woman in her late twenties. Vertical 9:16 self-shot UGC beat in "
          "a warmly lit apartment at dusk; she glances at the camera with a slight smile. Natural "
          "phone-recorded room tone; no music, no speech. Static medium close-up.")


def log(*a):
    print(*a, flush=True)


async def main() -> None:
    s = get_settings()
    mcp = build_server(s)
    ref = REFERENCE_IMAGE
    if not ref.startswith(("http://", "https://")):
        ref = await upload_file(ref, upload_url=s.tmpfiles_upload_url)
    async with Client(mcp) as c:
        sub = (await c.call_tool("generate_kling_video", {
            "prompt": PROMPT, "images": [ref], "resolution": "720p",
            "duration": 5, "aspect_ratio": "9:16", "enable_audio": True, "wait": False})).data
        log("task:", sub["task_id"], "status:", sub["status"])

        pc = PiapiClient(s)
        for _ in range(160):
            r = await pc.get_task(sub["task_id"])
            log(f"  status={r.normalized_status} video={r.video_url} err={r.error_message}")
            if r.is_terminal:
                if r.video_url:
                    await download(r.video_url, "/tmp/demo_kling.mp4")
                    log("saved /tmp/demo_kling.mp4")
                break
            await asyncio.sleep(15)


asyncio.run(main())
