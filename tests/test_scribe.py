"""Tests for ElevenLabsClient.transcribe (Scribe speech-to-text)."""

from __future__ import annotations

import tempfile

import httpx
import respx

from video_mcp.config import Settings
from video_mcp.clients.elevenlabs import ElevenLabsClient

BASE = "https://api.elevenlabs.io/v1"


def _settings() -> Settings:
    return Settings(elevenlabs_key="ek", elevenlabs_base=BASE)


def _audio_file() -> str:
    fd, path = tempfile.mkstemp(suffix=".mp3")
    import os
    with open(fd, "wb") as fh:
        fh.write(b"ID3fakeaudio")
    return path


@respx.mock
async def test_transcribe_returns_json():
    route = respx.post(f"{BASE}/speech-to-text").mock(
        return_value=httpx.Response(200, json={"text": "שלום עולם", "words": [{"text": "שלום", "start": 0.0}]})
    )
    c = ElevenLabsClient(_settings())
    out = await c.transcribe(_audio_file(), language_code="he")
    assert out["text"] == "שלום עולם"
    assert route.called
    req = route.calls.last.request
    assert req.headers["xi-api-key"] == "ek"
    # multipart body carries model_id and language_code
    body = req.content.decode("utf-8", "ignore")
    assert "scribe_v2" in body
    assert "language_code" in body


@respx.mock
async def test_transcribe_error_raises():
    from video_mcp.errors import ElevenLabsError

    respx.post(f"{BASE}/speech-to-text").mock(return_value=httpx.Response(422, json={"detail": "bad audio"}))
    c = ElevenLabsClient(_settings())
    try:
        await c.transcribe(_audio_file())
        assert False, "expected ElevenLabsError"
    except ElevenLabsError as e:
        assert "bad audio" in str(e)
