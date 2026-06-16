"""Tests for video_mcp.routing — pure duration/mode/language helpers."""

from __future__ import annotations

import pytest

from video_mcp.routing import (
    ceil_audio_to_duration,
    infer_seedance_mode,
    is_hebrew_request,
)


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (6.6, 7),      # the live BVAC case
        (12.4, 13),    # ceil up, not nearest-round down (speech never truncated)
        (12.6, 13),
        (2.1, 4),      # below the API min -> clamp up to 4
        (0.5, 4),
        (1, 4),
        (4.0, 4),
        (5.0, 5),
        (7, 7),
        (14.99, 15),
        (15.0, 15),
    ],
)
def test_ceil_audio_to_duration_boundaries(seconds, expected):
    assert ceil_audio_to_duration(seconds) == expected


@pytest.mark.parametrize("seconds", [15.01, 16, 100, 0, -1])
def test_ceil_audio_to_duration_rejects(seconds):
    with pytest.raises(ValueError):
        ceil_audio_to_duration(seconds)


@pytest.mark.parametrize(
    "n_images,n_videos,n_audios,expected",
    [
        (0, 0, 0, "text_to_video"),
        (1, 0, 0, "first_last_frames"),
        (2, 0, 0, "first_last_frames"),
        (3, 0, 0, "omni_reference"),
        (1, 1, 0, "omni_reference"),
        (1, 0, 1, "omni_reference"),
        (0, 1, 0, "omni_reference"),
        (0, 0, 1, "omni_reference"),
        (12, 0, 0, "omni_reference"),
    ],
)
def test_infer_seedance_mode(n_images, n_videos, n_audios, expected):
    assert (
        infer_seedance_mode(n_images=n_images, n_videos=n_videos, n_audios=n_audios)
        == expected
    )


@pytest.mark.parametrize(
    "language,expected",
    [
        ("he", True),
        ("HE", True),
        ("He", True),
        ("heb", True),
        ("HEB", True),
        ("hebrew", True),
        ("Hebrew", True),
        ("iw", True),
        ("IW", True),
        (None, False),
        ("en", False),
        ("EN", False),
        ("english", False),
        ("", False),
    ],
)
def test_is_hebrew_request(language, expected):
    assert is_hebrew_request(language) is expected
