from __future__ import annotations

import pytest
from pydantic import ValidationError

from video_mcp.schemas.elevenlabs import (
    HEBREW_MODEL,
    VoiceoverRequest,
    VoiceSettings,
)


def test_defaults():
    req = VoiceoverRequest(text="hi", voice_id="v1")
    assert req.model_id == "eleven_multilingual_v2"
    assert req.with_timestamps is True


def test_empty_text_fails():
    with pytest.raises(ValidationError):
        VoiceoverRequest(text="", voice_id="v1")


def test_empty_voice_id_fails():
    with pytest.raises(ValidationError):
        VoiceoverRequest(text="hi", voice_id="")


def test_hebrew_forces_v3_from_default():
    req = VoiceoverRequest(text="shalom", voice_id="v1", language="he")
    assert req.model_id == HEBREW_MODEL


def test_hebrew_forces_v3_case_insensitive():
    req = VoiceoverRequest(text="shalom", voice_id="v1", language="HE")
    assert req.model_id == HEBREW_MODEL


def test_hebrew_explicit_v3_ok():
    req = VoiceoverRequest(text="shalom", voice_id="v1", language="he", model_id=HEBREW_MODEL)
    assert req.model_id == HEBREW_MODEL


def test_hebrew_explicit_non_v3_fails():
    with pytest.raises(ValidationError):
        VoiceoverRequest(
            text="shalom", voice_id="v1", language="he", model_id="eleven_turbo_v2"
        )


def test_non_hebrew_keeps_default_model():
    req = VoiceoverRequest(text="hi", voice_id="v1", language="en")
    assert req.model_id == "eleven_multilingual_v2"


def test_seed_out_of_range_fails():
    with pytest.raises(ValidationError):
        VoiceoverRequest(text="hi", voice_id="v1", seed=-1)
    with pytest.raises(ValidationError):
        VoiceoverRequest(text="hi", voice_id="v1", seed=4294967296)


def test_seed_in_range_ok():
    req = VoiceoverRequest(text="hi", voice_id="v1", seed=42)
    assert req.to_body()["seed"] == 42


def test_to_body_shape():
    req = VoiceoverRequest(
        text="hi",
        voice_id="v1",
        language="en",
        voice_settings=VoiceSettings(stability=0.3),
        previous_text="before",
        next_text="after",
    )
    body = req.to_body()
    assert body["text"] == "hi"
    assert body["model_id"] == "eleven_multilingual_v2"
    assert body["language_code"] == "en"
    assert body["voice_settings"]["stability"] == 0.3
    assert body["previous_text"] == "before"
    assert body["next_text"] == "after"
    assert "seed" not in body


def test_to_body_hebrew_uses_v3_and_language_code():
    req = VoiceoverRequest(text="shalom", voice_id="v1", language="he")
    body = req.to_body()
    assert body["model_id"] == HEBREW_MODEL
    assert body["language_code"] == "he"
