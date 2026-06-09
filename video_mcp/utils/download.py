"""Download a URL to a local path (async, follows redirects)."""

from __future__ import annotations

import httpx


async def download(url: str, path: str, *, timeout: float = 120) -> str:
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        with open(path, "wb") as fh:
            fh.write(resp.content)
    return path
