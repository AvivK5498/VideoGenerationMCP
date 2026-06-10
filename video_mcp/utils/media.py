"""Multi-clip assembly helpers via ffmpeg: probe, stitch, split, frame-extract.

A 30s ad is several provider jobs (Seedance caps at 15s/clip); these utilities
own the local assembly steps so agents never improvise shell ffmpeg.
"""

from __future__ import annotations

import os
import subprocess

from video_mcp.errors import MediaError
from video_mcp.logging_config import get_logger

logger = get_logger(__name__)


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"{what} failed (exit {proc.returncode}): {(proc.stderr or '')[-2000:]}")
    return proc


def probe_duration(path: str, *, ffprobe_bin: str = "ffprobe") -> float:
    """Media duration in seconds (ffprobe)."""
    proc = _run(
        [ffprobe_bin, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        "ffprobe duration",
    )
    try:
        return float(proc.stdout.strip())
    except ValueError as exc:
        raise MediaError(f"ffprobe returned no duration for {path}") from exc


def probe_video_spec(path: str, *, ffprobe_bin: str = "ffprobe") -> tuple[int, int, str]:
    """(width, height, fps) of the first video stream. fps as ffmpeg rate string."""
    proc = _run(
        [ffprobe_bin, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,r_frame_rate",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        "ffprobe stream",
    )
    lines = proc.stdout.strip().splitlines()
    if len(lines) < 3:
        raise MediaError(f"ffprobe returned no video stream for {path}")
    return int(lines[0]), int(lines[1]), lines[2]


def stitch_videos(
    paths: list[str],
    out_path: str,
    *,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> str:
    """Concatenate clips into `out_path` with hard cuts.

    Every clip is normalized (scale + pad + SAR + fps + audio resample) to the
    FIRST clip's spec, so mixed resolutions/framerates concat cleanly. Re-encodes
    x264 + AAC. Raises MediaError on <2 clips or ffmpeg failure.
    """
    if len(paths) < 2:
        raise MediaError(f"stitch needs >= 2 clips, got {len(paths)}")
    for p in paths:
        if not os.path.isfile(p):
            raise MediaError(f"clip not found: {p}")

    width, height, fps = probe_video_spec(paths[0], ffprobe_bin=ffprobe_bin)
    cmd = [ffmpeg_bin, "-y"]
    for p in paths:
        cmd += ["-i", p]
    filters = []
    for i in range(len(paths)):
        filters.append(
            f"[{i}:v]scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,setsar=1,fps={fps}[v{i}];"
            f"[{i}:a]aresample=44100[a{i}]"
        )
    pairs = "".join(f"[v{i}][a{i}]" for i in range(len(paths)))
    filters.append(f"{pairs}concat=n={len(paths)}:v=1:a=1[v][a]")
    cmd += [
        "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", out_path,
    ]
    logger.info("Stitching %d clips -> %s (%dx%d@%s)", len(paths), out_path, width, height, fps)
    _run(cmd, "ffmpeg stitch")
    return out_path


def split_audio(
    audio_path: str,
    split_points_s: list[float],
    out_dir: str,
    *,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> list[dict]:
    """Cut `audio_path` at `split_points_s` into len(points)+1 mp3 segments.

    Points must be strictly increasing and inside the audio. Returns
    [{path, start_s, end_s, duration_s}, ...] in order.
    """
    if not os.path.isfile(audio_path):
        raise MediaError(f"audio not found: {audio_path}")
    total = probe_duration(audio_path, ffprobe_bin=ffprobe_bin)
    points = list(split_points_s)
    if not points:
        raise MediaError("split_points_s is empty — nothing to split")
    if any(b <= a for a, b in zip(points, points[1:])):
        raise MediaError(f"split points must be strictly increasing, got {points}")
    if points[0] <= 0 or points[-1] >= total:
        raise MediaError(f"split points must be inside (0, {total:.2f}), got {points}")

    bounds = [0.0, *points, total]
    base = os.path.splitext(os.path.basename(audio_path))[0]
    segments = []
    for i, (start, end) in enumerate(zip(bounds, bounds[1:]), start=1):
        seg = os.path.join(out_dir, f"{base}-seg{i:02d}.mp3")
        _run(
            [ffmpeg_bin, "-y", "-i", audio_path, "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
             "-acodec", "libmp3lame", "-q:a", "2", seg],
            f"ffmpeg split segment {i}",
        )
        segments.append({"path": seg, "start_s": round(start, 3), "end_s": round(end, 3),
                         "duration_s": round(end - start, 3)})
    return segments


def mix_music_into_video(
    video_path: str,
    music_path: str,
    out_path: str,
    *,
    music_gain_db: float = -20.0,
    duck: bool = True,
    ffmpeg_bin: str = "ffmpeg",
) -> str:
    """Mix a music bed under `video_path`'s existing audio into `out_path`.

    The music loops to cover the full video, sits at `music_gain_db` (default
    -20 dB — a barely-there bed under speech), and with `duck=True` is
    side-chain compressed by the speech so it dips further whenever someone
    talks. Output ends with the video; the video stream is copied untouched.
    """
    for p, what in ((video_path, "video"), (music_path, "music")):
        if not os.path.isfile(p):
            raise MediaError(f"{what} not found: {p}")
    if duck:
        # Speech (0:a) drives a sidechain compressor on the gained music bed.
        af = (
            f"[1:a]volume={music_gain_db}dB[m];"
            "[0:a]asplit=2[voice][sc];"
            "[m][sc]sidechaincompress=threshold=0.02:ratio=8:attack=5:release=400[duck];"
            "[voice][duck]amix=inputs=2:duration=first:normalize=0[a]"
        )
    else:
        af = (
            f"[1:a]volume={music_gain_db}dB[m];"
            "[0:a][m]amix=inputs=2:duration=first:normalize=0[a]"
        )
    cmd = [
        ffmpeg_bin, "-y", "-i", video_path, "-stream_loop", "-1", "-i", music_path,
        "-filter_complex", af, "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-shortest", out_path,
    ]
    logger.info("Mixing music under %s -> %s (%.1f dB, duck=%s)", video_path, out_path, music_gain_db, duck)
    _run(cmd, "ffmpeg music mix")
    return out_path


def extract_frame(
    video_path: str,
    out_path: str,
    *,
    time_s: float | None = None,
    ffmpeg_bin: str = "ffmpeg",
) -> str:
    """Save one frame of `video_path` as an image at `out_path`.

    `time_s=None` grabs the LAST frame (for first/last-frame clip bridging);
    otherwise the frame at `time_s` seconds.
    """
    if not os.path.isfile(video_path):
        raise MediaError(f"video not found: {video_path}")
    if time_s is None:
        cmd = [ffmpeg_bin, "-y", "-sseof", "-0.2", "-i", video_path,
               "-frames:v", "1", "-update", "1", out_path]
    else:
        cmd = [ffmpeg_bin, "-y", "-ss", f"{time_s:.3f}", "-i", video_path,
               "-frames:v", "1", out_path]
    _run(cmd, "ffmpeg frame extract")
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise MediaError(f"no frame written to {out_path} (time_s={time_s})")
    return out_path
