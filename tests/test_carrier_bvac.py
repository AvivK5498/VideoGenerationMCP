"""Tests for carrier audio-muxing and audio extraction (real ffmpeg)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

import pytest

from video_mcp.utils.carrier import extract_audio, make_black_carrier

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _make_audio() -> str:
    """A 2s sine-tone mp3 to mux."""
    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", path],
        capture_output=True, check=True,
    )
    return path


def _has_audio_stream(path: str) -> bool:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1", path],
        capture_output=True, text=True,
    )
    return "audio" in out.stdout


def _probe_duration(path: str) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def test_carrier_muxes_audio():
    audio = _make_audio()
    fd, out = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    make_black_carrier(5, out, audio_path=audio)
    assert os.path.getsize(out) > 0
    assert _has_audio_stream(out)  # the speech track is muxed in


def test_carrier_at_vo_matched_duration_has_no_extra_silence():
    # When the caller passes a VO-matched duration_s (here 2s VO -> duration_s=2),
    # the carrier must equal the VO length, not pad beyond it.
    audio = _make_audio()  # 2s
    fd, out = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    make_black_carrier(2, out, audio_path=audio)
    assert abs(_probe_duration(out) - 2.0) < 0.2  # no trailing silence past the VO


def test_extract_audio_roundtrip():
    audio = _make_audio()
    fd, carrier = tempfile.mkstemp(suffix=".mp4")
    os.close(fd)
    make_black_carrier(5, carrier, audio_path=audio)

    fd2, extracted = tempfile.mkstemp(suffix=".mp3")
    os.close(fd2)
    extract_audio(carrier, extracted)
    assert os.path.getsize(extracted) > 0
