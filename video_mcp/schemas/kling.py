"""Request schemas for Kling Omni video generation (PiAPI)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from video_mcp.utils.references import validate_references

from .common import ServiceMode

KlingResolution = Literal["720p", "1080p"]
KlingAspectRatio = Literal["16:9", "9:16", "1:1"]


class KlingShot(BaseModel):
    prompt: str = Field(min_length=1)
    duration: int = Field(default=3, ge=1, le=14)


class KlingVideoRequest(BaseModel):
    prompt: str | None = None
    shots: list[KlingShot] | None = None
    version: Literal["3.0"] = "3.0"
    resolution: KlingResolution = "720p"
    duration: int = Field(default=5, ge=3, le=15)
    aspect_ratio: KlingAspectRatio = "16:9"
    enable_audio: bool = True
    images: list[str] | None = None
    video: str | None = None
    keep_original_audio: bool = False
    service_mode: ServiceMode | None = None

    @model_validator(mode="after")
    def _validate(self) -> "KlingVideoRequest":
        if self.shots is not None and self.video is not None:
            raise ValueError("shots and video are mutually exclusive")
        if self.shots is not None:
            if not (1 <= len(self.shots) <= 6):
                raise ValueError("shots must contain between 1 and 6 items")
            if sum(s.duration for s in self.shots) > 15:
                raise ValueError("sum of shot durations must be <= 15")
        else:
            if not self.prompt:
                raise ValueError("prompt or shots required")
        if self.images is not None:
            limit = 4 if self.video is not None else 7
            if len(self.images) > limit:
                raise ValueError(f"images exceeds max of {limit} for this configuration")
        if self.keep_original_audio and self.video is None:
            raise ValueError("keep_original_audio requires a video reference")

        # @-tag references must match the supplied arrays (Kling: @image_N + bare @video).
        # Multi-shot prompts carry the tags; the top-level prompt is ignored by PiAPI.
        scanned = " ".join(filter(None, [self.prompt] + [s.prompt for s in (self.shots or [])]))
        validate_references(
            scanned,
            n_images=len(self.images or []),
            n_videos=1 if self.video else 0,
            style="kling",
        )
        return self

    def to_piapi_input(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "version": self.version,
            "resolution": self.resolution,
            "aspect_ratio": self.aspect_ratio,
            "enable_audio": self.enable_audio,
        }
        if self.shots is not None:
            out["multi_shots"] = [
                {"prompt": s.prompt, "duration": s.duration} for s in self.shots
            ]
        else:
            out["prompt"] = self.prompt
            out["duration"] = self.duration
        if self.images:
            out["images"] = self.images
        if self.video:
            out["video"] = self.video
        if self.keep_original_audio:
            out["keep_original_audio"] = self.keep_original_audio
        return out
