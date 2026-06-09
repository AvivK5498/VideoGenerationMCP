"""Tests for video_mcp.routing — pure duration/mode/language helpers."""

from __future__ import annotations

import pytest

from video_mcp.routing import (
    infer_seedance_mode,
    is_hebrew_request,
    round_duration_to_allowed,
)


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (5, 5),
        (5.0, 5),
        (1, 5),
        (4.9, 5),
        (6, 10),
        (10, 10),
        (9.5, 10),
        (11, 15),
        (15, 15),
        (12.3, 15),
    ],
)
def test_round_duration_to_allowed_boundaries(seconds, expected):
    assert round_duration_to_allowed(seconds) == expected


@pytest.mark.parametrize("seconds", [16, 15.01, 100, 0, -1])
def test_round_duration_to_allowed_rejects(seconds):
    with pytest.raises(ValueError):
        round_duration_to_allowed(seconds)


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
