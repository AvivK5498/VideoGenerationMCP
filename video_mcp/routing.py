"""Pure routing helpers — duration rounding and Hebrew/Seedance policy.

No I/O. These mirror the validation gates in schemas/seedance.py and encode the
Hebrew lipsync orchestration policy consumed by tools/seedance.py.
"""

from __future__ import annotations

_HEBREW_LANGS = {"he", "heb", "hebrew", "iw"}


def round_duration_to_allowed(seconds: float) -> int:
    """Round an audio length up to the nearest allowed Seedance duration.

    <=5 -> 5 ; >5 and <=10 -> 10 ; >10 and <=15 -> 15 ; >15 or <=0 -> ValueError.
    """
    if seconds <= 0:
        raise ValueError(f"duration must be > 0, got {seconds!r}")
    if seconds <= 5:
        return 5
    if seconds <= 10:
        return 10
    if seconds <= 15:
        return 15
    raise ValueError(f"duration {seconds!r} exceeds the maximum allowed (15s)")


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
