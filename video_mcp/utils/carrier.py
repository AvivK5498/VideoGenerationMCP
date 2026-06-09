"""Black-video audio carrier (BVAC) generation + audio extraction via ffmpeg.

A BVAC is a black MP4 whose visuals are ignored and whose audio drives Seedance
lip-sync. The Hebrew speech MP3 is muxed INTO the black video; the carrier is then
referenced as @video1 in the prompt ("use only as audio-timing/lip-sync reference;
ignore its black visuals"). Default frame size is 720x1280 (9:16, vertical UGC).
"""

from __future__ import annotations

import subprocess

from video_mcp.errors import CarrierError
from video_mcp.logging_config import get_logger

logger = get_logger(__name__)

_MAX_DURATION_S = 15


def make_black_carrier(
    duration_s: int | float,
    out_path: str,
    *,
    audio_path: str | None = None,
    ffmpeg_bin: str = "ffmpeg",
    width: int = 720,
    height: int = 1280,
    fps: int = 24,
) -> str:
    """Generate a black MP4 of `duration_s` seconds at `out_path`.

    If `audio_path` is given, its audio is muxed in as the carrier track (true
    BVAC); otherwise the carrier is silent. The video always runs the full
    `duration_s` (the look holds after the speech ends). `duration_s` must be > 0
    and <= 15. Raises CarrierError on bad duration or non-zero ffmpeg exit.
    """
    if duration_s <= 0 or duration_s > _MAX_DURATION_S:
        raise CarrierError(f"duration_s must be > 0 and <= {_MAX_DURATION_S}, got {duration_s}")

    dur = str(duration_s)
    color = f"color=c=black:s={width}x{height}:r={fps}:d={dur}"
    cmd = [ffmpeg_bin, "-y", "-f", "lavfi", "-i", color]
    if audio_path:
        # Mux the speech track in; no -shortest so the black video holds full duration.
        cmd += ["-i", audio_path, "-map", "0:v", "-map", "1:a", "-t", dur]
    else:
        cmd += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", dur, "-shortest"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", out_path]

    logger.info("Generating black carrier: duration=%s audio=%s out=%s", dur, bool(audio_path), out_path)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise CarrierError(f"ffmpeg failed (exit {proc.returncode}): {(proc.stderr or '')[-2000:]}")
    return out_path


def extract_audio(video_path: str, out_path: str, *, ffmpeg_bin: str = "ffmpeg") -> str:
    """Extract the audio track of `video_path` to `out_path` (e.g. mp3) for QA.

    Raises CarrierError on a non-zero ffmpeg exit (e.g. the video has no audio).
    Returns `out_path`.
    """
    cmd = [ffmpeg_bin, "-y", "-i", video_path, "-vn", "-acodec", "libmp3lame", "-q:a", "2", out_path]
    logger.info("Extracting audio: %s -> %s", video_path, out_path)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise CarrierError(f"ffmpeg audio-extract failed (exit {proc.returncode}): {(proc.stderr or '')[-2000:]}")
    return out_path
