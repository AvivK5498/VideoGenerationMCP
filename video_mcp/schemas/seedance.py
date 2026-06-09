"""Request schemas for Seedance 2.0 video generation (PiAPI)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from video_mcp.utils.references import validate_references

from .common import ServiceMode

SeedanceTaskType = Literal[
    "seedance-2", "seedance-2-fast",
    "seedance-2-less-restriction", "seedance-2-fast-less-restriction",
]
SeedanceMode = Literal["text_to_video", "first_last_frames", "omni_reference"]
SeedanceResolution = Literal["480p", "720p", "1080p"]
SeedanceAspectRatio = Literal["21:9", "16:9", "4:3", "1:1", "3:4", "9:16", "auto"]

ALLOWED_DURATIONS = (5, 10, 15)
LESS_RESTRICTION_TYPES = {"seedance-2-less-restriction", "seedance-2-fast-less-restriction"}
FAST_TYPES = {"seedance-2-fast", "seedance-2-fast-less-restriction"}


def _is_asset(url: str) -> bool:
    return url.startswith("asset://")


class SeedanceVideoRequest(BaseModel):
    prompt: str = Field(max_length=4000)
    task_type: SeedanceTaskType = "seedance-2-less-restriction"
    mode: SeedanceMode | None = None
    duration: int = 5
    resolution: SeedanceResolution = "720p"
    aspect_ratio: SeedanceAspectRatio = "16:9"
    image_urls: list[str] | None = None
    video_urls: list[str] | None = None
    audio_urls: list[str] | None = None
    auto_upload_assets: bool = False
    asset_retention_hours: int = 3
    service_mode: ServiceMode | None = None

    @model_validator(mode="after")
    def _validate(self) -> "SeedanceVideoRequest":
        if self.duration not in ALLOWED_DURATIONS:
            raise ValueError(f"duration must be one of {ALLOWED_DURATIONS}, got {self.duration}")
        if self.resolution == "1080p" and self.task_type in FAST_TYPES:
            raise ValueError(f"{self.task_type} (fast) does not support 1080p resolution")

        all_urls = (self.image_urls or []) + (self.video_urls or []) + (self.audio_urls or [])
        is_lr = self.task_type in LESS_RESTRICTION_TYPES
        # asset:// references and auto-upload require a -less-restriction task type (PiAPI 422/400).
        if any(_is_asset(u) for u in all_urls) and not is_lr:
            raise ValueError("asset:// references are only allowed on -less-restriction task types")
        if self.auto_upload_assets and not is_lr:
            raise ValueError("auto_upload_assets requires a -less-restriction task type")
        if self.auto_upload_assets and not (3 <= self.asset_retention_hours <= 8):
            raise ValueError("asset_retention_hours must be in 3..8")

        n_images = len(self.image_urls or [])
        n_videos = len(self.video_urls or [])
        n_audios = len(self.audio_urls or [])

        if n_images > 12:
            raise ValueError("image_urls exceeds max of 12")

        resolved = self.mode or self._infer_mode(n_images, n_videos, n_audios)

        if resolved == "text_to_video":
            if n_images or n_videos or n_audios:
                raise ValueError("text_to_video accepts no reference images/videos/audio")
        elif resolved == "first_last_frames":
            if not (1 <= n_images <= 2):
                raise ValueError("first_last_frames requires 1-2 images")
            if n_videos or n_audios:
                raise ValueError("first_last_frames accepts no video or audio references")
        elif resolved == "omni_reference":
            total = n_images + n_videos + n_audios
            if not (1 <= total <= 12):
                raise ValueError("omni_reference requires 1-12 total references")
            if n_audios and not (n_images or n_videos):
                raise ValueError("omni_reference audio requires at least one image or video")

        self.mode = resolved

        # @-tag references must match supplied arrays (Seedance: @imageN/@videoN/@audioN).
        # first_last_frames images are positional, so exempt them from the
        # must-be-referenced direction (dangling tags are still rejected).
        validate_references(
            self.prompt,
            n_images=n_images,
            n_videos=n_videos,
            n_audios=n_audios,
            style="seedance",
            require_referenced=(resolved != "first_last_frames"),
        )
        return self

    @staticmethod
    def _infer_mode(n_images: int, n_videos: int, n_audios: int) -> SeedanceMode:
        if n_images == 0 and n_videos == 0 and n_audios == 0:
            return "text_to_video"
        if 1 <= n_images <= 2 and n_videos == 0 and n_audios == 0:
            return "first_last_frames"
        return "omni_reference"

    def to_piapi_input(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "prompt": self.prompt,
            "mode": self.mode,
            "duration": self.duration,
            "resolution": self.resolution,
            "aspect_ratio": self.aspect_ratio,
        }
        if self.image_urls:
            out["image_urls"] = self.image_urls
        if self.video_urls:
            out["video_urls"] = self.video_urls
        if self.audio_urls:
            out["audio_urls"] = self.audio_urls
        if self.auto_upload_assets:
            out["auto_upload_assets"] = True
            out["asset_retention_hours"] = self.asset_retention_hours
        return out
