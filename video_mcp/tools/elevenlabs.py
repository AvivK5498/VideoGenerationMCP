"""FastMCP tool: ElevenLabs voiceover synthesis (generate_elevenlabs_voiceover)."""

from __future__ import annotations

import os
import tempfile
from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from video_mcp.errors import VideoMCPError
from video_mcp.logging_config import get_logger, redact
from video_mcp.schemas.elevenlabs import VoiceSettings, VoiceoverRequest
from video_mcp.tools import Deps
from video_mcp.utils import media as media_mod

logger = get_logger(__name__)


def _suffix_for(output_format: str) -> str:
    """Best-effort file extension from an ElevenLabs output_format string."""
    fmt = output_format.lower()
    if fmt.startswith("mp3"):
        return ".mp3"
    if fmt.startswith("pcm"):
        return ".pcm"
    if fmt.startswith("ulaw") or fmt.startswith("mulaw"):
        return ".ulaw"
    if fmt.startswith("opus"):
        return ".opus"
    return ".bin"


def register_elevenlabs_tools(mcp: FastMCP, deps: Deps) -> None:
    """Register the ElevenLabs voiceover tool on `mcp`."""

    @mcp.tool
    async def generate_elevenlabs_voiceover(
        text: str,
        voice_id: str,
        language: str | None = None,
        model_id: str = "eleven_multilingual_v2",
        output_format: str = "mp3_44100_128",
        seed: int | None = None,
        previous_text: str | None = None,
        next_text: str | None = None,
        with_timestamps: bool = True,
        stability: float | None = None,
        similarity_boost: float | None = None,
        style: float | None = None,
        use_speaker_boost: bool | None = None,
        speed: float | None = None,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Synthesize speech with ElevenLabs and write the audio to a temp file."""
        voice_settings: VoiceSettings | None = None
        if any(v is not None for v in (stability, similarity_boost, style, use_speaker_boost, speed)):
            defaults = VoiceSettings()
            voice_settings = VoiceSettings(
                stability=stability if stability is not None else defaults.stability,
                similarity_boost=similarity_boost if similarity_boost is not None else defaults.similarity_boost,
                style=style if style is not None else defaults.style,
                use_speaker_boost=use_speaker_boost if use_speaker_boost is not None else defaults.use_speaker_boost,
                speed=speed if speed is not None else defaults.speed,
            )

        try:
            req = VoiceoverRequest(
                text=text,
                voice_id=voice_id,
                language=language,
                model_id=model_id,
                voice_settings=voice_settings,
                output_format=output_format,
                seed=seed,
                previous_text=previous_text,
                next_text=next_text,
                with_timestamps=with_timestamps,
            )
        except ValidationError as exc:
            raise ToolError(str(exc)) from exc

        try:
            alignment: dict[str, Any] | None
            if req.with_timestamps:
                audio, full = await deps.eleven.tts_with_timestamps(req)
                alignment = full.get("alignment")
            else:
                audio = await deps.eleven.tts(req)
                alignment = None
        except VideoMCPError as err:
            raise ToolError(str(err)) from err

        suffix = _suffix_for(req.output_format)
        if output_path is None:
            fd, output_path = tempfile.mkstemp(suffix=suffix, prefix="elevenlabs_")
            with open(fd, "wb") as fh:
                fh.write(audio)
        else:
            with open(output_path, "wb") as fh:
                fh.write(audio)

        logger.info(
            "voiceover written: %s",
            redact({"audio_path": output_path, "model_id": req.model_id}),
        )
        return {
            "audio_path": output_path,
            "output_format": req.output_format,
            "model_id": req.model_id,
            "alignment": alignment,
            "characters": len(text),
        }

    @mcp.tool
    async def generate_music(
        prompt: str,
        duration_s: float,
        force_instrumental: bool = True,
        model_id: str = "music_v1",
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Compose a music track with Eleven Music (3-600s) from a text prompt.

        For speech ads the bed must be COMPLEMENTARY, not the main event: prompt
        for minimal/low-key/background music ("soft, sparse, no melodic hook, low
        intensity"), keep force_instrumental=true so it never fights the voiceover,
        match duration_s to the video, then lay it under with mix_music_into_video
        (low gain + speech ducking).
        """
        if not 3 <= duration_s <= 600:
            raise ToolError(f"duration_s must be 3-600 seconds, got {duration_s}")
        try:
            audio = await deps.eleven.compose_music(
                prompt, music_length_ms=int(duration_s * 1000),
                force_instrumental=force_instrumental, model_id=model_id,
            )
        except VideoMCPError as err:
            raise ToolError(str(err)) from err
        if not output_path:
            fd, output_path = tempfile.mkstemp(suffix=".mp3", prefix="music_")
            os.close(fd)
        with open(output_path, "wb") as fh:
            fh.write(audio)
        try:
            duration = media_mod.probe_duration(output_path, ffprobe_bin=deps.settings.ffprobe_bin)
        except VideoMCPError:
            duration = None
        return {"audio_path": output_path, "duration_s": duration, "prompt": prompt}

    @mcp.tool
    async def generate_sound_effect(
        prompt: str,
        duration_seconds: float,
        prompt_influence: float = 0.25,
        loop: bool = True,
        output_path: str | None = None,
    ) -> dict[str, Any]:
        """Generate an ambient/diegetic sound-effect bed (0.5-30s) from a text prompt.

        Generation only — the caller mixes the bed onto the video locally with
        its own ducking recipe. Describe the soundscape concretely ("busy gym
        ambience: muffled crowd murmur, low machine hum"), pass the clip/ad
        runtime as duration_seconds, and keep loop=true for a seamless bed.
        """
        duration_seconds = max(0.5, min(30.0, duration_seconds))
        try:
            audio = await deps.eleven.generate_sound_effect(
                prompt, duration_seconds=duration_seconds,
                prompt_influence=prompt_influence, loop=loop,
            )
        except VideoMCPError as err:
            raise ToolError(str(err)) from err
        if not output_path:
            fd, output_path = tempfile.mkstemp(suffix=".mp3", prefix="sfx_")
            os.close(fd)
        with open(output_path, "wb") as fh:
            fh.write(audio)
        try:
            duration = media_mod.probe_duration(output_path, ffprobe_bin=deps.settings.ffprobe_bin)
        except VideoMCPError:
            duration = None
        return {"audio_path": output_path, "duration_s": duration, "prompt": prompt}
