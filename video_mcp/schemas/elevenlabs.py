"""Request schemas for ElevenLabs text-to-speech voiceover."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

TextNormalization = Literal["auto", "on", "off"]
HEBREW_MODEL = "eleven_v3"


class VoiceSettings(BaseModel):
    stability: float = 0.5
    similarity_boost: float = 0.75
    style: float = 0.0
    use_speaker_boost: bool = True
    speed: float = 1.0


class VoiceoverRequest(BaseModel):
    text: str = Field(min_length=1)
    voice_id: str = Field(min_length=1)
    language: str | None = None
    model_id: str = "eleven_multilingual_v2"
    voice_settings: VoiceSettings | None = None
    output_format: str = "mp3_44100_128"
    seed: int | None = None
    previous_text: str | None = None
    next_text: str | None = None
    with_timestamps: bool = True

    @model_validator(mode="after")
    def _validate(self) -> "VoiceoverRequest":
        if self.language is not None and self.language.lower() == "he":
            if self.model_id == "eleven_multilingual_v2":
                self.model_id = HEBREW_MODEL
            elif self.model_id != HEBREW_MODEL:
                raise ValueError(
                    f"Hebrew (language='he') requires model_id '{HEBREW_MODEL}', "
                    f"got '{self.model_id}'"
                )
        if self.seed is not None and not (0 <= self.seed <= 4294967295):
            raise ValueError("seed must be in range 0..4294967295")
        return self

    def to_body(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "text": self.text,
            "model_id": self.model_id,
        }
        if self.voice_settings is not None:
            out["voice_settings"] = self.voice_settings.model_dump()
        if self.language is not None:
            out["language_code"] = self.language
        if self.seed is not None:
            out["seed"] = self.seed
        if self.previous_text is not None:
            out["previous_text"] = self.previous_text
        if self.next_text is not None:
            out["next_text"] = self.next_text
        return out
