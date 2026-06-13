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


def _fps_value(rate: str) -> float:
    """Numeric fps from an ffmpeg rate string like '24/1' or '30000/1001'."""
    if "/" in rate:
        num, den = rate.split("/", 1)
        den_f = float(den)
        return float(num) / den_f if den_f else 0.0
    return float(rate)


def has_audio(path: str, *, ffprobe_bin: str = "ffprobe") -> bool:
    """True if `path` has at least one audio stream (ffprobe)."""
    proc = _run(
        [ffprobe_bin, "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_type",
         "-of", "default=noprint_wrappers=1:nokey=1", path],
        "ffprobe audio",
    )
    return "audio" in proc.stdout


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


def measure_loudness(path: str, *, ffmpeg_bin: str = "ffmpeg") -> float:
    """Integrated loudness (LUFS) of a media file's audio via ebur128."""
    proc = subprocess.run(
        [ffmpeg_bin, "-i", path, "-af", "ebur128", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    lines = (proc.stderr or "").splitlines()
    for i, line in enumerate(lines):
        if "Integrated loudness" in line and i + 1 < len(lines):
            try:
                return float(lines[i + 1].split("I:")[1].split("LUFS")[0].strip())
            except (IndexError, ValueError):
                break
    raise MediaError(f"could not measure loudness of {path}")


def mix_music_into_video(
    video_path: str,
    music_path: str,
    out_path: str,
    *,
    music_gain_db: float | None = None,
    music_below_speech_db: float = 14.0,
    duck: bool = True,
    ffmpeg_bin: str = "ffmpeg",
) -> str:
    """Mix a music bed under `video_path`'s existing audio into `out_path`.

    Gain is ADAPTIVE by default: both tracks are loudness-measured and the music
    is placed `music_below_speech_db` LUFS below the speech (so a quiet master
    and a hot master land the same). Pass `music_gain_db` for a fixed gain
    instead. With `duck=True` a gentle side-chain (ratio 3) dips the bed a few
    dB further while someone talks. The music loops to cover the video; the
    video stream is copied untouched.
    """
    for p, what in ((video_path, "video"), (music_path, "music")):
        if not os.path.isfile(p):
            raise MediaError(f"{what} not found: {p}")
    if music_gain_db is None:
        speech_i = max(measure_loudness(video_path, ffmpeg_bin=ffmpeg_bin), -30.0)
        music_i = measure_loudness(music_path, ffmpeg_bin=ffmpeg_bin)
        music_gain_db = round((speech_i - music_below_speech_db) - music_i, 1)
    if duck:
        # Gentle duck: engages on speech (~-18 dBFS threshold), ~4-6 dB of dip.
        af = (
            f"[1:a]volume={music_gain_db}dB[m];"
            "[0:a]asplit=2[voice][sc];"
            "[m][sc]sidechaincompress=threshold=0.125:ratio=3:attack=20:release=500[duck];"
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


# Output-duration verification tolerance (s). Re-encode/PTS rounding lands the
# container a frame or two off the request; beyond this we treat it as a failure.
_DURATION_TOL_S = 0.2


def _verify_duration(path: str, expected: float, *, ffprobe_bin: str, what: str) -> float:
    """Probe `path`, assert its duration ~= expected, return the actual duration."""
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        raise MediaError(f"{what} produced no output at {path}")
    actual = probe_duration(path, ffprobe_bin=ffprobe_bin)
    if abs(actual - expected) > _DURATION_TOL_S:
        raise MediaError(
            f"{what} duration off: wanted ~{expected:.3f}s, got {actual:.3f}s"
        )
    return actual


def trim_video(
    video_path: str,
    out_path: str,
    *,
    duration_s: float | None = None,
    start_s: float | None = None,
    end_s: float | None = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> tuple[str, float]:
    """Frame-accurate cut of `video_path` to an exact span into `out_path`.

    Span is EITHER [0, duration_s] OR [start_s, end_s]. Re-encodes (x264) for
    frame accuracy rather than keyframe -c copy; resolution, fps and aspect ratio
    are preserved (no scaling). A silent source yields a silent output (audio is
    only re-encoded when present). Returns (out_path, actual_duration).
    """
    if not os.path.isfile(video_path):
        raise MediaError(f"video not found: {video_path}")
    start = 0.0 if duration_s is not None else (start_s or 0.0)
    end = duration_s if duration_s is not None else end_s
    if end is None or end <= start:
        raise MediaError(f"invalid trim span: start={start}, end={end}")
    src_dur = probe_duration(video_path, ffprobe_bin=ffprobe_bin)
    if end > src_dur + _DURATION_TOL_S:
        raise MediaError(f"requested span {end:.3f}s exceeds source duration {src_dur:.3f}s")

    # -ss/-to as OUTPUT options (after -i) => decode-accurate seek.
    cmd = [ffmpeg_bin, "-y", "-i", video_path, "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
           "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if has_audio(video_path, ffprobe_bin=ffprobe_bin):
        cmd += ["-c:a", "aac"]
    else:
        cmd += ["-an"]
    cmd += [out_path]
    logger.info("Trimming %s [%.3f, %.3f] -> %s", video_path, start, end, out_path)
    _run(cmd, "ffmpeg trim")
    actual = _verify_duration(out_path, end - start, ffprobe_bin=ffprobe_bin, what="trim")
    return out_path, actual


def retime_video(
    video_path: str,
    out_path: str,
    *,
    target_duration_s: float | None = None,
    speed: float | None = None,
    interpolate: bool = False,
    min_speed: float = 0.5,
    max_speed: float = 2.0,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> tuple[str, float, float]:
    """Stretch/compress `video_path` to a target duration (or explicit speed).

    speed = source_dur/target_dur (1.0 unchanged, 0.5 half-speed/2x longer).
    Implemented via PTS rescaling (setpts); `interpolate=True` adds motion
    interpolation (minterpolate) for smoother slow-mo instead of frame
    duplication. Audio, if present, is retimed with atempo. speed is clamped to
    [min_speed, max_speed] — outside that range raises MediaError. Returns
    (out_path, actual_duration, speed).
    """
    if not os.path.isfile(video_path):
        raise MediaError(f"video not found: {video_path}")
    src_dur = probe_duration(video_path, ffprobe_bin=ffprobe_bin)
    if speed is None:
        if target_duration_s is None or target_duration_s <= 0:
            raise MediaError(f"target_duration_s must be > 0, got {target_duration_s}")
        speed = src_dur / target_duration_s
    if not (min_speed <= speed <= max_speed):
        raise MediaError(
            f"speed {speed:.3f} out of range [{min_speed}, {max_speed}] "
            "(extreme retime looks broken)"
        )

    factor = 1.0 / speed  # setpts multiplier: >1 slower/longer, <1 faster/shorter
    if interpolate:
        _, _, rate = probe_video_spec(video_path, ffprobe_bin=ffprobe_bin)
        fps = _fps_value(rate) or 24.0
        vf = f"setpts={factor:.6f}*PTS,minterpolate=fps={fps:g}:mi_mode=mci:mc_mode=aobmc:vsbmc=1"
    else:
        vf = f"setpts={factor:.6f}*PTS"

    cmd = [ffmpeg_bin, "-y", "-i", video_path, "-vf", vf, "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if has_audio(video_path, ffprobe_bin=ffprobe_bin):
        cmd += ["-filter:a", f"atempo={speed:.6f}", "-c:a", "aac"]
    else:
        cmd += ["-an"]
    cmd += [out_path]
    logger.info("Retiming %s speed=%.4f interpolate=%s -> %s", video_path, speed, interpolate, out_path)
    _run(cmd, "ffmpeg retime")
    actual = _verify_duration(out_path, src_dur / speed, ffprobe_bin=ffprobe_bin, what="retime")
    return out_path, actual, round(speed, 4)


def mix_narration(
    video_path: str,
    voiceover_path: str,
    out_path: str,
    *,
    bed_path: str | None = None,
    bed_below_voice_db: float = 14.0,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> tuple[str, float]:
    """Lay `voiceover_path` as the primary audio over `video_path` into `out_path`.

    The VO plays at full level; the video stream is copied untouched. If
    `bed_path` is given it is mixed in `bed_below_voice_db` LUFS below the VO
    (adaptive, loudness-measured) with a gentle side-chain duck under the voice.
    Output runs the VIDEO's length: the audio is padded with silence if shorter
    and trimmed if longer. Returns (out_path, actual_duration).
    """
    for p, what in ((video_path, "video"), (voiceover_path, "voiceover")):
        if not os.path.isfile(p):
            raise MediaError(f"{what} not found: {p}")
    if bed_path is not None and not os.path.isfile(bed_path):
        raise MediaError(f"bed not found: {bed_path}")
    video_dur = probe_duration(video_path, ffprobe_bin=ffprobe_bin)

    if bed_path is None:
        cmd = [
            ffmpeg_bin, "-y", "-i", video_path, "-i", voiceover_path,
            "-filter_complex", "[1:a]apad[a]", "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-t", f"{video_dur:.3f}", out_path,
        ]
    else:
        vo_i = measure_loudness(voiceover_path, ffmpeg_bin=ffmpeg_bin)
        bed_i = measure_loudness(bed_path, ffmpeg_bin=ffmpeg_bin)
        bed_gain_db = round((vo_i - bed_below_voice_db) - bed_i, 1)
        af = (
            "[1:a]apad[vo];"
            f"[2:a]volume={bed_gain_db}dB[bedv];"
            "[vo]asplit=2[voice][sc];"
            "[bedv][sc]sidechaincompress=threshold=0.125:ratio=3:attack=20:release=500[duck];"
            "[voice][duck]amix=inputs=2:duration=first:normalize=0[a]"
        )
        cmd = [
            ffmpeg_bin, "-y", "-i", video_path, "-i", voiceover_path,
            "-stream_loop", "-1", "-i", bed_path,
            "-filter_complex", af, "-map", "0:v", "-map", "[a]",
            "-c:v", "copy", "-c:a", "aac", "-t", f"{video_dur:.3f}", out_path,
        ]
    logger.info("Mixing narration over %s (bed=%s) -> %s", video_path, bool(bed_path), out_path)
    _run(cmd, "ffmpeg narration mix")
    actual = _verify_duration(out_path, video_dur, ffprobe_bin=ffprobe_bin, what="narration mix")
    return out_path, actual
