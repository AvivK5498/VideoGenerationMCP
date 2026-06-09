"""Async ElevenLabs client for text-to-speech and voice listing."""

from __future__ import annotations

import base64
from typing import TYPE_CHECKING, Any

import httpx

from video_mcp.config import Settings
from video_mcp.errors import ElevenLabsError
from video_mcp.logging_config import get_logger, redact

if TYPE_CHECKING:  # schemas/elevenlabs.py is built by a sibling module
    from video_mcp.schemas.elevenlabs import VoiceoverRequest

logger = get_logger(__name__)


def _parse_detail(resp: httpx.Response) -> str:
    """Best-effort extraction of an ElevenLabs error message."""
    try:
        data = resp.json()
    except Exception:
        return resp.text or f"HTTP {resp.status_code}"
    if isinstance(data, dict):
        detail = data.get("detail")
        if isinstance(detail, dict):
            return str(detail.get("message") or detail)
        if detail is not None:
            return str(detail)
        if data.get("message"):
            return str(data["message"])
    return str(data)


class ElevenLabsClient:
    """Thin async wrapper over the ElevenLabs v1 API."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "xi-api-key": self._settings.require_elevenlabs(),
            "Content-Type": "application/json",
        }

    async def _post(self, url: str, json: dict[str, Any]) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(url, json=json, headers=self._headers())
        async with httpx.AsyncClient() as client:
            return await client.post(url, json=json, headers=self._headers())

    async def _get(self, url: str) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, headers=self._headers())
        async with httpx.AsyncClient() as client:
            return await client.get(url, headers=self._headers())

    async def tts(self, req: "VoiceoverRequest") -> bytes:
        url = f"{self._settings.elevenlabs_base}/text-to-speech/{req.voice_id}"
        body = req.to_body()
        logger.info("elevenlabs tts: %s", redact(body))
        resp = await self._post(f"{url}?output_format={req.output_format}", body)
        if resp.status_code >= 400:
            raise ElevenLabsError(_parse_detail(resp), code=resp.status_code, raw=resp.text)
        return resp.content

    async def tts_with_timestamps(self, req: "VoiceoverRequest") -> tuple[bytes, dict]:
        url = f"{self._settings.elevenlabs_base}/text-to-speech/{req.voice_id}/with-timestamps"
        body = req.to_body()
        logger.info("elevenlabs tts_with_timestamps: %s", redact(body))
        resp = await self._post(f"{url}?output_format={req.output_format}", body)
        if resp.status_code >= 400:
            raise ElevenLabsError(_parse_detail(resp), code=resp.status_code, raw=resp.text)
        data = resp.json()
        audio = base64.b64decode(data["audio_base64"])
        return audio, data

    async def list_voices(self) -> list[dict]:
        url = f"{self._settings.elevenlabs_base}/voices"
        resp = await self._get(url)
        if resp.status_code >= 400:
            raise ElevenLabsError(_parse_detail(resp), code=resp.status_code, raw=resp.text)
        return resp.json()["voices"]

    async def transcribe(
        self,
        audio_path: str,
        *,
        language_code: str | None = "he",
        model_id: str = "scribe_v2",
        timestamps_granularity: str = "word",
    ) -> dict:
        """Transcribe an audio file with ElevenLabs Scribe (speech-to-text).

        Multipart POST to /speech-to-text. Returns the full JSON (text + word
        timestamps). Used for the BVAC audio gates.
        """
        url = f"{self._settings.elevenlabs_base}/speech-to-text"
        data = {"model_id": model_id, "timestamps_granularity": timestamps_granularity, "tag_audio_events": "false"}
        if language_code:
            data["language_code"] = language_code
        headers = {"xi-api-key": self._settings.require_elevenlabs()}  # multipart: no JSON content-type
        logger.info("elevenlabs scribe: %s", redact({**data, "file": audio_path}))

        with open(audio_path, "rb") as fh:
            files = {"file": (audio_path.rsplit("/", 1)[-1], fh, "application/octet-stream")}
            if self._client is not None:
                resp = await self._client.post(url, data=data, files=files, headers=headers)
            else:
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(url, data=data, files=files, headers=headers)
        if resp.status_code >= 400:
            raise ElevenLabsError(_parse_detail(resp), code=resp.status_code, raw=resp.text)
        return resp.json()
