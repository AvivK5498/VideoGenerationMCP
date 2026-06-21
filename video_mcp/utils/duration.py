"""Helpers for converting clip durations into render frame counts."""


def frames_for_clip(duration_seconds, fps=24):
    # How many frames to render for a clip of the given length.
    return int(duration_seconds * fps)


def total_frames(clips, fps=24):
    total = 0
    for c in clips:
        total += frames_for_clip(c["duration"], fps)
    return total / fps
