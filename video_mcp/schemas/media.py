"""Request schemas for the local voiceover-fit media primitives.

These validate STATIC input shape (which fields are set, sign/range of the
numbers). File existence and probe-derived checks (span <= source duration,
computed-speed range) happen in utils/media.py against ffprobe and surface as
MediaError. Tools catch both ValidationError and MediaError at the boundary and
re-raise as ToolError.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

# A retime outside this range looks broken (judder / soup), so it is rejected.
MIN_SPEED = 0.5
MAX_SPEED = 2.0


class TrimVideoRequest(BaseModel):
    """Frame-accurate cut to an exact span.

    Provide EITHER `duration_s` (keep [0, duration_s]) OR `start_s` + `end_s`.
    """

    video_path: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    duration_s: float | None = None
    start_s: float | None = None
    end_s: float | None = None

    @model_validator(mode="after")
    def _validate(self) -> "TrimVideoRequest":
        by_duration = self.duration_s is not None
        by_span = self.start_s is not None or self.end_s is not None
        if by_duration and by_span:
            raise ValueError("provide EITHER duration_s OR start_s+end_s, not both")
        if not by_duration and not by_span:
            raise ValueError("provide duration_s, or start_s and end_s")
        if by_duration:
            if self.duration_s <= 0:
                raise ValueError(f"duration_s must be > 0, got {self.duration_s}")
        else:
            if self.start_s is None or self.end_s is None:
                raise ValueError("start_s and end_s are both required for a span cut")
            if self.start_s < 0:
                raise ValueError(f"start_s must be >= 0, got {self.start_s}")
            if self.end_s <= self.start_s:
                raise ValueError(f"end_s ({self.end_s}) must be > start_s ({self.start_s})")
        return self

    @property
    def span(self) -> tuple[float, float]:
        """Resolved (start_s, end_s)."""
        if self.duration_s is not None:
            return 0.0, self.duration_s
        return self.start_s, self.end_s  # type: ignore[return-value]


class RetimeVideoRequest(BaseModel):
    """Stretch/compress a clip. Provide EITHER `target_duration_s` OR `speed`.

    speed is source_dur/target_dur: 1.0 = unchanged, 0.5 = half-speed (2x longer).
    An explicit speed is range-checked here; a speed derived from
    target_duration_s is range-checked in the util once the source is probed.
    """

    video_path: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    target_duration_s: float | None = None
    speed: float | None = None
    interpolate: bool = False

    @model_validator(mode="after")
    def _validate(self) -> "RetimeVideoRequest":
        if (self.target_duration_s is None) == (self.speed is None):
            raise ValueError("provide EITHER target_duration_s OR speed, not both")
        if self.target_duration_s is not None and self.target_duration_s <= 0:
            raise ValueError(f"target_duration_s must be > 0, got {self.target_duration_s}")
        if self.speed is not None and not (MIN_SPEED <= self.speed <= MAX_SPEED):
            raise ValueError(f"speed must be in [{MIN_SPEED}, {MAX_SPEED}], got {self.speed}")
        return self


class MixNarrationRequest(BaseModel):
    """Lay a voiceover as the primary audio over a (silent) video.

    Optional `bed_path` is mixed ducked under the VO at `bed_below_voice_db`
    below it (distinct from mix_music_into_video, which ducks under EXISTING
    speech).
    """

    video_path: str = Field(min_length=1)
    voiceover_path: str = Field(min_length=1)
    output_path: str = Field(min_length=1)
    bed_path: str | None = None
    bed_below_voice_db: float = 14.0

    @model_validator(mode="after")
    def _validate(self) -> "MixNarrationRequest":
        if self.bed_below_voice_db < 0:
            raise ValueError(f"bed_below_voice_db must be >= 0, got {self.bed_below_voice_db}")
        return self
