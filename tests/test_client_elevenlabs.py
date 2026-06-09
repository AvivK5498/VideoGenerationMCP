"""Tests for ElevenLabsClient — self-contained (own fixtures, respx mocks)."""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import respx

from video_mcp.clients.elevenlabs import ElevenLabsClient
from video_mcp.config import Settings
from video_mcp.errors import ElevenLabsError

BASE = "https://api.elevenlabs.test/v1"


def make_settings() -> Settings:
    s = Settings()
    s.elevenlabs_key = "test-xi-key"
    s.elevenlabs_base = BASE
    return s


def make_client(http: httpx.AsyncClient) -> ElevenLabsClient:
    return ElevenLabsClient(make_settings(), client=http)


@dataclass
class StubReq:
    """Minimal stand-in for VoiceoverRequest (schemas/elevenlabs.py built elsewhere)."""

    voice_id: str = "voice-1"
    output_format: str = "mp3_44100_128"
    text: str = "hello world"
    model_id: str = "eleven_multilingual_v2"
    _body: dict[str, Any] = field(default_factory=dict)

    def to_body(self) -> dict[str, Any]:
        return self._body or {"text": self.text, "model_id": self.model_id}


@respx.mock
async def test_tts_returns_bytes():
    audio = b"\x00\x01RAWAUDIO"
    route = respx.post(f"{BASE}/text-to-speech/voice-1").mock(
        return_value=httpx.Response(200, content=audio)
    )
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        out = await client.tts(StubReq())
    assert out == audio
    assert route.calls.last.request.headers["xi-api-key"] == "test-xi-key"
    assert "output_format=mp3_44100_128" in str(route.calls.last.request.url)


@respx.mock
async def test_tts_with_timestamps_decodes_base64():
    audio = b"timestamped-bytes"
    payload = {
        "audio_base64": base64.b64encode(audio).decode(),
        "alignment": {"characters": ["h"], "character_start_times_seconds": [0.0]},
        "normalized_alignment": {"characters": ["h"]},
    }
    respx.post(f"{BASE}/text-to-speech/voice-1/with-timestamps").mock(
        return_value=httpx.Response(200, json=payload)
    )
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        out_bytes, out_json = await client.tts_with_timestamps(StubReq())
    assert out_bytes == audio
    assert out_json["alignment"]["characters"] == ["h"]


@respx.mock
async def test_list_voices_returns_list():
    voices = {"voices": [{"voice_id": "v1", "name": "Aria"}, {"voice_id": "v2", "name": "Roger"}]}
    respx.get(f"{BASE}/voices").mock(return_value=httpx.Response(200, json=voices))
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        out = await client.list_voices()
    assert [v["voice_id"] for v in out] == ["v1", "v2"]


@respx.mock
async def test_tts_422_error():
    err = {"detail": {"message": "voice_id not found", "status": "voice_not_found"}}
    respx.post(f"{BASE}/text-to-speech/voice-1").mock(return_value=httpx.Response(422, json=err))
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        with pytest.raises(ElevenLabsError) as ei:
            await client.tts(StubReq())
    assert "voice_id not found" in str(ei.value)
    assert ei.value.code == 422


@respx.mock
async def test_tts_with_timestamps_422_error():
    err = {"detail": "bad request"}
    respx.post(f"{BASE}/text-to-speech/voice-1/with-timestamps").mock(
        return_value=httpx.Response(422, json=err)
    )
    async with httpx.AsyncClient() as http:
        client = make_client(http)
        with pytest.raises(ElevenLabsError) as ei:
            await client.tts_with_timestamps(StubReq())
    assert "bad request" in str(ei.value)
