"""Upload local files to tmpfiles.org and return a direct-download URL.

tmpfiles returns a *page* URL like https://tmpfiles.org/<id>/<name>; we rewrite
it to the direct form https://tmpfiles.org/dl/<id>/<name> so providers can fetch
the raw bytes.
"""

from __future__ import annotations

import os

import httpx

from video_mcp.errors import UploadError
from video_mcp.logging_config import get_logger

logger = get_logger(__name__)


def _to_direct_url(page_url: str) -> str:
    """Insert "/dl/" after the host of a tmpfiles page URL."""
    marker = "tmpfiles.org/"
    idx = page_url.find(marker)
    if idx == -1:
        raise UploadError(f"unexpected tmpfiles url: {page_url!r}")
    head = page_url[: idx + len(marker)]
    tail = page_url[idx + len(marker) :]
    return f"{head}dl/{tail}"


async def upload_file(
    path: str,
    *,
    upload_url: str,
    client: httpx.AsyncClient | None = None,
) -> str:
    """POST `path` to tmpfiles `upload_url`; return the direct /dl/ URL.

    Creates a temporary AsyncClient if none is provided. Raises UploadError on
    HTTP failure or a missing url in the response.
    """
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient()

    try:
        with open(path, "rb") as fh:
            files = {"file": (os.path.basename(path), fh)}
            resp = await client.post(upload_url, files=files)

        if resp.status_code >= 400:
            raise UploadError(f"tmpfiles upload failed: HTTP {resp.status_code}")

        try:
            body = resp.json()
        except Exception as exc:  # noqa: BLE001
            raise UploadError(f"tmpfiles returned non-JSON: {exc}") from exc

        logger.info("tmpfiles upload status=%s", body.get("status"))
        page_url = (body.get("data") or {}).get("url")
        if not page_url:
            raise UploadError(f"tmpfiles response missing data.url: {body!r}")

        return _to_direct_url(page_url)
    finally:
        if owns_client:
            await client.aclose()
