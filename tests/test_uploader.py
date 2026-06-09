"""Tests for video_mcp.utils.uploader."""

from __future__ import annotations

import httpx
import pytest
import respx

from video_mcp.errors import UploadError
from video_mcp.utils.uploader import upload_file

UPLOAD_URL = "https://tmpfiles.org/api/v1/upload"


@respx.mock
async def test_upload_returns_direct_dl_url(tmp_path):
    f = tmp_path / "audio.mp3"
    f.write_bytes(b"fake audio bytes")

    respx.post(UPLOAD_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"url": "https://tmpfiles.org/12345/audio.mp3"},
            },
        )
    )

    url = await upload_file(str(f), upload_url=UPLOAD_URL)
    assert url == "https://tmpfiles.org/dl/12345/audio.mp3"


@respx.mock
async def test_upload_with_injected_client(tmp_path):
    f = tmp_path / "carrier.mp4"
    f.write_bytes(b"\x00\x01\x02")

    respx.post(UPLOAD_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"url": "https://tmpfiles.org/999/carrier.mp4"},
            },
        )
    )

    async with httpx.AsyncClient() as client:
        url = await upload_file(str(f), upload_url=UPLOAD_URL, client=client)
    assert url == "https://tmpfiles.org/dl/999/carrier.mp4"


@respx.mock
async def test_upload_http_error_raises(tmp_path):
    f = tmp_path / "audio.mp3"
    f.write_bytes(b"data")

    respx.post(UPLOAD_URL).mock(return_value=httpx.Response(500, text="boom"))

    with pytest.raises(UploadError):
        await upload_file(str(f), upload_url=UPLOAD_URL)


@respx.mock
async def test_upload_missing_url_raises(tmp_path):
    f = tmp_path / "audio.mp3"
    f.write_bytes(b"data")

    respx.post(UPLOAD_URL).mock(
        return_value=httpx.Response(200, json={"status": "success", "data": {}})
    )

    with pytest.raises(UploadError):
        await upload_file(str(f), upload_url=UPLOAD_URL)
