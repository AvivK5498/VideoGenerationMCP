"""Exception hierarchy for the video MCP server.

Tool functions catch pydantic.ValidationError and these errors at the boundary
and re-raise as fastmcp.exceptions.ToolError with a clean, agent-readable message.
"""

from __future__ import annotations


class VideoMCPError(Exception):
    """Base class for all server-raised errors."""


class ConfigError(VideoMCPError):
    """Missing or invalid configuration (e.g. absent API key)."""


class ProviderError(VideoMCPError):
    """An upstream provider returned an error response.

    Attributes:
        message: human-readable message (already parsed from the provider envelope).
        code: provider error/status code if available.
        raw: the raw provider response body (dict or text) for debugging.
        provider: short provider name, e.g. "piapi" or "elevenlabs".
    """

    def __init__(
        self,
        message: str,
        *,
        code: int | str | None = None,
        raw: object | None = None,
        provider: str = "",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.raw = raw
        self.provider = provider

    def __str__(self) -> str:  # pragma: no cover - trivial
        prefix = f"[{self.provider}]" if self.provider else ""
        suffix = f" (code={self.code})" if self.code is not None else ""
        return f"{prefix} {self.message}{suffix}".strip()


class PiapiError(ProviderError):
    def __init__(self, message: str, *, code: int | str | None = None, raw: object | None = None) -> None:
        super().__init__(message, code=code, raw=raw, provider="piapi")


class ElevenLabsError(ProviderError):
    def __init__(self, message: str, *, code: int | str | None = None, raw: object | None = None) -> None:
        super().__init__(message, code=code, raw=raw, provider="elevenlabs")


class UploadError(VideoMCPError):
    """Failed to upload a local file to the public host."""


class CarrierError(VideoMCPError):
    """Failed to generate the black-video audio carrier (ffmpeg)."""


class TransliterationError(VideoMCPError):
    """LLM transliteration failed (both LMStudio and OpenRouter unavailable, or
    the model returned an empty / still-Hebrew result)."""


class ImageOpsError(VideoMCPError):
    """ImageMagick reference-processing (posterize/grid) failed."""


class ContentPolicyError(VideoMCPError):
    """Prompt describes a young/minor or real/identifiable person. Personas must be
    framed as fictional adults; references must be 'not a direct copy'."""
