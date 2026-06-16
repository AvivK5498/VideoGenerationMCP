"""Pure routing helpers — duration rounding and Hebrew/Seedance policy.

No I/O. These mirror the validation gates in schemas/seedance.py and encode the
Hebrew lipsync orchestration policy consumed by tools/seedance.py.
"""

from __future__ import annotations

import math

_HEBREW_LANGS = {"he", "heb", "hebrew", "iw"}


def ceil_audio_to_duration(seconds: float) -> int:
    """Clip duration that fits `seconds` of audio: ceil to a whole second, clamped to [4, 15].

    Seedance accepts any integer duration 4-15s. We round UP so speech is never
    truncated (at most ~1s of trailing silent pad). Audio under 4s clamps up to the
    API minimum of 4. Audio that ceils past 15s can't fit one clip -> caller must split.
    """
    if seconds <= 0:
        raise ValueError(f"audio duration must be > 0, got {seconds!r}")
    rounded = math.ceil(seconds)
    if rounded > 15:
        raise ValueError(
            f"audio is {seconds:.2f}s but a single clip is at most 15s — split the audio "
            "(split_audio) across multiple clips."
        )
    return max(4, rounded)


def infer_seedance_mode(*, n_images: int, n_videos: int, n_audios: int) -> str:
    """Infer the Seedance mode from reference counts.

    0 refs -> text_to_video; exactly 1-2 images & no video/audio ->
    first_last_frames; otherwise -> omni_reference.
    """
    if n_images == 0 and n_videos == 0 and n_audios == 0:
        return "text_to_video"
    if 1 <= n_images <= 2 and n_videos == 0 and n_audios == 0:
        return "first_last_frames"
    return "omni_reference"


def is_hebrew_request(language: str | None) -> bool:
    """True iff `language` names Hebrew (case-insensitive he/heb/hebrew/iw)."""
    return language is not None and language.lower() in _HEBREW_LANGS
