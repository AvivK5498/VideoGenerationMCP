"""Validate that prompt @-tags match the supplied reference arrays.

Two provider conventions:
  - kling:    @image_1 (underscore, 1-based, repeatable) + bare @video
  - seedance: @image1 / @video1 / @audio1 (no underscore, 1-based)

PiAPI rejects a prompt that references @image3 when only two images are supplied,
and a supplied-but-unreferenced image is wasted input — both are caught here
before submission.
"""

from __future__ import annotations

import re

# Tags are matched case-insensitively: @Image1 (skill convention) and @image1 both count.
_KLING = {
    "image": re.compile(r"@image_(\d+)", re.IGNORECASE),
    "video": re.compile(r"@video(?![\w])", re.IGNORECASE),  # bare @video, single reference
}
_SEEDANCE = {
    "image": re.compile(r"@image(\d+)", re.IGNORECASE),
    "video": re.compile(r"@video(\d+)", re.IGNORECASE),
    "audio": re.compile(r"@audio(\d+)", re.IGNORECASE),
}


def extract_tags(text: str, *, style: str) -> dict[str, set[int]]:
    """Return referenced indices per kind. Kling's bare @video maps to {1} if present."""
    text = text or ""
    if style == "kling":
        return {
            "image": {int(m) for m in _KLING["image"].findall(text)},
            "video": {1} if _KLING["video"].search(text) else set(),
            "audio": set(),
        }
    if style == "seedance":
        return {k: {int(m) for m in rx.findall(text)} for k, rx in _SEEDANCE.items()}
    raise ValueError(f"unknown tag style: {style}")


def _check_kind(kind: str, refs: set[int], n: int, *, require_referenced: bool, hint: str) -> None:
    if refs and min(refs) < 1:
        raise ValueError(f"{hint.replace('1', '0')} is invalid; reference indices start at 1")
    if refs and max(refs) > n:
        raise ValueError(f"prompt references @{kind}{max(refs)} but only {n} {kind}(s) were supplied")
    if require_referenced:
        missing = [i for i in range(1, n + 1) if i not in refs]
        if missing:
            raise ValueError(
                f"{kind}(s) {missing} supplied but never referenced in the prompt "
                f"(use {hint}). Every supplied reference must be tagged."
            )


# Per-style example tags shown in error messages.
_HINTS = {
    "kling": {"image": "@image_1", "video": "@video", "audio": "@audio1"},
    "seedance": {"image": "@image1", "video": "@video1", "audio": "@audio1"},
}


def validate_references(
    text: str,
    *,
    n_images: int = 0,
    n_videos: int = 0,
    n_audios: int = 0,
    style: str,
    require_referenced: bool = True,
) -> None:
    """Raise ValueError on dangling tags or (unless exempt) unreferenced supplied refs."""
    tags = extract_tags(text, style=style)
    hints = _HINTS[style]
    _check_kind("image", tags["image"], n_images, require_referenced=require_referenced, hint=hints["image"])
    _check_kind("video", tags["video"], n_videos, require_referenced=require_referenced, hint=hints["video"])
    _check_kind("audio", tags["audio"], n_audios, require_referenced=require_referenced, hint=hints["audio"])
