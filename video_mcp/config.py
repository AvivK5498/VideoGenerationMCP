"""Runtime configuration, sourced from environment variables.

Env vars:
    PIAPI_KEY            - PiAPI key, sent as the `x-api-key` header (Kling + Seedance).
    ELEVENLABS_KEY       - ElevenLabs key, sent as the `xi-api-key` header.
    PIAPI_BASE           - default https://api.piapi.ai/api/v1
    ELEVENLABS_BASE      - default https://api.elevenlabs.io/v1
    TMPFILES_UPLOAD_URL  - default https://tmpfiles.org/api/v1/upload
    POLL_INTERVAL_S      - poll cadence for wait=True (default 5)
    POLL_TIMEOUT_S       - max wait for wait=True (default 1800)
    FFMPEG_BIN           - ffmpeg binary (default "ffmpeg")
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from .errors import ConfigError


def _env(name: str, default: str) -> str:
    return os.getenv(name, default)


@dataclass
class Settings:
    piapi_key: str | None = field(default_factory=lambda: os.getenv("PIAPI_KEY"))
    elevenlabs_key: str | None = field(default_factory=lambda: os.getenv("ELEVENLABS_KEY"))
    piapi_base: str = field(default_factory=lambda: _env("PIAPI_BASE", "https://api.piapi.ai/api/v1"))
    elevenlabs_base: str = field(default_factory=lambda: _env("ELEVENLABS_BASE", "https://api.elevenlabs.io/v1"))
    tmpfiles_upload_url: str = field(
        default_factory=lambda: _env("TMPFILES_UPLOAD_URL", "https://tmpfiles.org/api/v1/upload")
    )
    poll_interval_s: float = field(default_factory=lambda: float(_env("POLL_INTERVAL_S", "5")))
    poll_timeout_s: float = field(default_factory=lambda: float(_env("POLL_TIMEOUT_S", "1800")))
    # Per-request HTTP timeout for PiAPI calls (slow peak-hour submits). 40 min.
    http_timeout_s: float = field(default_factory=lambda: float(_env("PIAPI_HTTP_TIMEOUT_S", "2400")))
    ffmpeg_bin: str = field(default_factory=lambda: _env("FFMPEG_BIN", "ffmpeg"))
    ffprobe_bin: str = field(default_factory=lambda: _env("FFPROBE_BIN", "ffprobe"))

    # Hebrew transliteration via LLM: local LMStudio first, OpenRouter fallback.
    lmstudio_base_url: str = field(default_factory=lambda: _env("LMSTUDIO_BASE_URL", "http://localhost:1234/v1"))
    lmstudio_model: str = field(default_factory=lambda: _env("LMSTUDIO_MODEL", "google/gemma-4-e4b"))
    openrouter_base_url: str = field(default_factory=lambda: _env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"))
    openrouter_api_key: str | None = field(default_factory=lambda: os.getenv("OPENROUTER_API_KEY"))
    openrouter_model: str = field(
        default_factory=lambda: _env("OPENROUTER_MODEL", "nvidia/llama-3.1-nemotron-70b-instruct")
    )
    # gemma-4-e4b is non-reasoning; transliteration output is ~1:1 with input, so
    # 512 covers long prompts. Raise if you transliterate very long text.
    transliterate_max_tokens: int = field(default_factory=lambda: int(_env("TRANSLITERATE_MAX_TOKENS", "512")))
    transliterate_timeout_s: float = field(default_factory=lambda: float(_env("TRANSLITERATE_TIMEOUT_S", "60")))

    def require_piapi(self) -> str:
        if not self.piapi_key:
            raise ConfigError("PIAPI_KEY is not set")
        return self.piapi_key

    def require_elevenlabs(self) -> str:
        if not self.elevenlabs_key:
            raise ConfigError("ELEVENLABS_KEY is not set")
        return self.elevenlabs_key


def get_settings() -> Settings:
    """Return a fresh Settings read from the current environment."""
    return Settings()
