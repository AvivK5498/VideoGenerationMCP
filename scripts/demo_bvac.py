"""Demo: full Hebrew BVAC flow through the MCP tools.

upload_asset (register a persona reference as a private asset) ->
generate_seedance_video(language=he) on the non-fast less-restriction tier, with the
asset:// human reference, then poll to a finished clip.

Env:
  PIAPI_KEY, ELEVENLABS_KEY     - required
  REFERENCE_IMAGE              - path or public URL to a persona reference image (required)
  ELEVEN_VOICE_ID             - ElevenLabs voice id (required)
  INFLUENCER_PAGE             - optional .md path to record the asset id on
  HEBREW_TEXT                 - optional spoken line (Hebrew); a benign default is used

Run: uv run python scripts/demo_bvac.py
"""

import asyncio
import os

from fastmcp import Client

from video_mcp.clients.piapi import PiapiClient
from video_mcp.config import get_settings
from video_mcp.server import build_server
from video_mcp.utils.download import download

REFERENCE_IMAGE = os.environ["REFERENCE_IMAGE"]
VOICE = os.environ["ELEVEN_VOICE_ID"]
INFLUENCER_PAGE = os.getenv("INFLUENCER_PAGE")
HEBREW = os.getenv("HEBREW_TEXT") or (
    "היי חברים, רוצה לספר לכם על מקום חדש שגיליתי השבוע. אווירה מושלמת, מוזיקה טובה. שווה לבדוק."
)
ROLE = ("an identity reference, not a direct copy, for a fictional adult creator: a confident adult "
        "woman in her late twenties, wearing a fitted emerald-green satin top and delicate gold hoops")
SCENE = ("10-second vertical 9:16 self-shot UGC clip in a warmly lit apartment at dusk, plants behind, "
         "quiet room tone. Static medium close-up, a slight knowing smile, one controlled hand gesture.")


def log(*a):
    print(*a, flush=True)


async def main() -> None:
    s = get_settings()
    mcp = build_server(s)
    async with Client(mcp) as c:
        args = {"image": REFERENCE_IMAGE, "name": "persona-identity", "asset_type": "Image"}
        if INFLUENCER_PAGE:
            args["influencer_page"] = INFLUENCER_PAGE
        ref = (await c.call_tool("upload_asset", args)).data["asset_ref"]
        log("asset:", ref)

        sub = (await c.call_tool("generate_seedance_video", {
            "language": "he", "text": HEBREW, "voice_id": VOICE, "prompt": SCENE,
            "human_image_urls": [ref], "image_roles": [ROLE], "duration": 10,
            "resolution": "720p", "wait": False})).data
        log("task:", sub["task_id"], "|", sub["task_type"], sub["mode"], sub["aspect_ratio"])
        log("source_audio_qa:", sub.get("source_audio_qa"))

        pc = PiapiClient(s)
        for _ in range(160):
            r = await pc.get_task(sub["task_id"])
            log(f"  status={r.normalized_status} video={r.video_url} err={r.error_message}")
            if r.is_terminal:
                if r.video_url:
                    await download(r.video_url, "/tmp/demo_bvac.mp4")
                    log("saved /tmp/demo_bvac.mp4")
                break
            await asyncio.sleep(15)


asyncio.run(main())
