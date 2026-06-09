"""Tests for video_mcp.utils.carrier."""

from __future__ import annotations

import os
import shutil
import subprocess

import pytest

from video_mcp.errors import CarrierError
from video_mcp.utils.carrier import make_black_carrier

_HAS_FFMPEG = shutil.which("ffmpeg") is not None
_HAS_FFPROBE = shutil.which("ffprobe") is not None


@pytest.mark.skipif(not _HAS_FFMPEG, reason="ffmpeg not installed")
def test_make_black_carrier_creates_nonempty_file(tmp_path):
    out = str(tmp_path / "carrier.mp4")
    result = make_black_carrier(1, out)
    assert result == out
    assert os.path.exists(out)
    assert os.path.getsize(out) > 0


@pytest.mark.skipif(
    not (_HAS_FFMPEG and _HAS_FFPROBE), reason="ffmpeg/ffprobe not installed"
)
def test_carrier_duration_is_about_one_second(tmp_path):
    out = str(tmp_path / "carrier.mp4")
    make_black_carrier(1, out)
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            out,
        ],
        capture_output=True,
        text=True,
    )
    duration = float(proc.stdout.strip())
    assert abs(duration - 1.0) < 0.5


def test_carrier_rejects_zero_duration(tmp_path):
    out = str(tmp_path / "carrier.mp4")
    with pytest.raises(CarrierError):
        make_black_carrier(0, out)


def test_carrier_rejects_over_max_duration(tmp_path):
    out = str(tmp_path / "carrier.mp4")
    with pytest.raises(CarrierError):
        make_black_carrier(16, out)


def test_carrier_rejects_negative_duration(tmp_path):
    out = str(tmp_path / "carrier.mp4")
    with pytest.raises(CarrierError):
        make_black_carrier(-1, out)


def test_carrier_bad_ffmpeg_bin_raises(tmp_path):
    out = str(tmp_path / "carrier.mp4")
    with pytest.raises((CarrierError, FileNotFoundError)):
        make_black_carrier(1, out, ffmpeg_bin="ffmpeg_does_not_exist_xyz")
