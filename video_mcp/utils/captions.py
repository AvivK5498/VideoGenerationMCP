"""Word-timed caption overlays: Scribe words -> grouped chunks -> PIL PNGs -> ffmpeg burn.

Styling ports the proven vault renderer (white Arial Bold, black stroke, drop
shadow, centered low-third, shrink-to-fit). Hebrew/RTL is handled with pure-python
bidi reordering (Hebrew needs no contextual shaping), so no libraqm dependency.
"""

from __future__ import annotations

import math
import os
from typing import Any

from bidi.algorithm import get_display
from PIL import Image, ImageDraw, ImageFont

from video_mcp.errors import MediaError
from video_mcp.logging_config import get_logger
from video_mcp.utils.media import _run
from video_mcp.utils.transliterate import has_hebrew

logger = get_logger(__name__)

_FONT_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",      # macOS
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",   # debian/ubuntu
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",            # fedora
]

DEFAULT_STYLE: dict[str, Any] = {
    "font_px": 64,
    "min_font_px": 36,
    "stroke_px": 6,
    "fill": "white",
    "stroke": "black",
    "shadow_alpha": 120,
    "shadow_offset_px": 2,
    "line_spacing": 1.08,
    "max_width_pct": 0.84,
    "y_pct": 0.76,
    "crf": 18,
}


def _resolve_font(style: dict) -> str:
    path = style.get("font_path") or os.getenv("CAPTION_FONT")
    candidates = [path] if path else _FONT_CANDIDATES
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise MediaError(
        "no caption font found — set style.font_path or CAPTION_FONT to a bold .ttf"
    )


def group_words(
    words: list[dict],
    *,
    max_words: int = 4,
    max_gap_s: float = 0.6,
    min_dur_s: float = 0.5,
    tail_s: float = 0.15,
) -> list[dict]:
    """Group Scribe word entries into caption chunks: {text, start, end}.

    Splits on chunk size or a speech gap > max_gap_s. Chunk end gets a small
    tail and is clamped so chunks never overlap.
    """
    toks = [w for w in words if (w.get("type") in (None, "word")) and (w.get("text") or "").strip()]
    if not toks:
        return []
    chunks: list[list[dict]] = []
    cur: list[dict] = []
    for w in toks:
        if cur and (len(cur) >= max_words or float(w["start"]) - float(cur[-1]["end"]) > max_gap_s):
            chunks.append(cur)
            cur = []
        cur.append(w)
    chunks.append(cur)

    out: list[dict] = []
    for c in chunks:
        start = float(c[0]["start"])
        end = max(float(c[-1]["end"]) + tail_s, start + min_dur_s)
        out.append({"text": " ".join(w["text"].strip() for w in c), "start": start, "end": end})
    for i in range(len(out) - 1):
        out[i]["end"] = min(out[i]["end"], out[i + 1]["start"] - 0.01)
    return out


def _display(line: str) -> str:
    """Logical -> visual order for RTL lines; LTR lines pass through."""
    return get_display(line) if has_hebrew(line) else line


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont,
          max_width: int, stroke: int) -> list[str]:
    """Wrap on LOGICAL words; bidi reordering happens per-line at draw time."""
    words = text.split()
    if not words:
        return [""]
    lines, cur = [], words[0]
    for w in words[1:]:
        trial = f"{cur} {w}"
        box = draw.textbbox((0, 0), _display(trial), font=font, stroke_width=stroke)
        if box[2] - box[0] <= max_width:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines


def render_caption_overlay(width: int, height: int, text: str, style: dict, out_path: str) -> str:
    """Render one full-frame transparent PNG with the caption text styled + centered."""
    st = {**DEFAULT_STYLE, **style}
    font_file = _resolve_font(st)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    max_width = int(width * float(st["max_width_pct"]))

    size = int(st["font_px"])
    while size >= int(st["min_font_px"]):
        font = ImageFont.truetype(font_file, size)
        lines = _wrap(draw, text, font, max_width, int(st["stroke_px"]))
        widths = [draw.textbbox((0, 0), _display(ln), font=font, stroke_width=int(st["stroke_px"]))[2]
                  for ln in lines]
        if all(w <= max_width for w in widths):
            break
        size -= 2
    else:
        font = ImageFont.truetype(font_file, int(st["min_font_px"]))
        lines = _wrap(draw, text, font, max_width, int(st["stroke_px"]))

    line_step = int(math.ceil(font.size * float(st["line_spacing"])))
    block_h = line_step * (len(lines) - 1) + font.size
    y0 = int(height * float(st["y_pct"])) - block_h // 2
    shadow_off = int(st["shadow_offset_px"])

    for i, line in enumerate(lines):
        visual = _display(line)
        cy = y0 + i * line_step + font.size // 2
        kwargs = dict(font=font, anchor="mm", align="center",
                      stroke_width=int(st["stroke_px"]), stroke_fill=st["stroke"])
        draw.text((width / 2 + shadow_off, cy + shadow_off), visual,
                  fill=(0, 0, 0, int(st["shadow_alpha"])), **kwargs)
        draw.text((width / 2, cy), visual, fill=st["fill"], **kwargs)

    image.save(out_path)
    return out_path


def burn_caption_overlays(
    video_path: str,
    overlays: list[dict],
    out_path: str,
    *,
    crf: int = 18,
    ffmpeg_bin: str = "ffmpeg",
) -> str:
    """Composite timed PNG overlays ({png, start, end}) onto the video; audio copied."""
    if not overlays:
        raise MediaError("no caption overlays to burn")
    cmd = [ffmpeg_bin, "-y", "-i", video_path]
    for ov in overlays:
        cmd += ["-i", ov["png"]]
    prev, parts = "[0:v]", []
    for i, ov in enumerate(overlays, start=1):
        out = f"[v{i}]"
        parts.append(
            f"{prev}[{i}:v]overlay=0:0:enable='between(t,{float(ov['start']):.3f},{float(ov['end']):.3f})'{out}"
        )
        prev = out
    cmd += [
        "-filter_complex", ";".join(parts), "-map", prev, "-map", "0:a?",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart", out_path,
    ]
    logger.info("Burning %d caption overlays -> %s", len(overlays), out_path)
    _run(cmd, "ffmpeg caption burn")
    return out_path
