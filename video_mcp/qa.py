"""BVAC audio-gate QA: compare a Scribe transcript against the intended speech.

The skill demands no semantic drift; full judgement is a human/LLM call, so this
module gives a deterministic heuristic verdict (token overlap + language check)
and surfaces both transcripts so a caller can escalate. Hard failures (empty /
wrong-language) are unambiguous; the middle band is `needs_human_review`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from video_mcp.utils.transliterate import has_hebrew

# Token-overlap bands against the intended transcript:
#   == 100%        -> pass (no errors)
#   85% .. <100%   -> warning
#   < 85%          -> fail (error)
_PASS_AT = 1.0
_FAIL_BELOW = 0.85

_NIQQUD = re.compile(r"[֑-ׇ]")
_PUNCT = re.compile(r"[^\w֐-׿]+", re.UNICODE)


@dataclass
class TranscriptVerdict:
    verdict: str          # "pass" | "warning" | "fail"
    overlap: float        # 0..1 token overlap with the intended text
    expected: str
    transcript: str
    notes: str

    @property
    def is_garbled(self) -> bool:
        return self.verdict == "fail"

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "overlap": round(self.overlap, 3),
            "expected": self.expected,
            "transcript": self.transcript,
            "notes": self.notes,
        }


def _tokens(text: str) -> list[str]:
    text = _NIQQUD.sub("", unicodedata.normalize("NFC", text))
    text = _PUNCT.sub(" ", text).lower()
    return [t for t in text.split() if t]


def _overlap(expected: str, actual: str) -> float:
    exp, act = _tokens(expected), _tokens(actual)
    if not exp:
        return 0.0
    act_set = set(act)
    hits = sum(1 for t in exp if t in act_set)
    return hits / len(exp)


def compare_transcripts(expected: str, transcript: str, *, expect_hebrew: bool = True) -> TranscriptVerdict:
    """Verdict on whether `transcript` (from Scribe) matches the intended `expected` speech."""
    t = (transcript or "").strip()
    if not t:
        return TranscriptVerdict("fail", 0.0, expected, transcript, "empty transcript / no speech detected")
    if expect_hebrew and not has_hebrew(t):
        return TranscriptVerdict("fail", 0.0, expected, t, "wrong language: no Hebrew detected in generated audio")

    ov = _overlap(expected, t)
    if ov >= _PASS_AT:
        return TranscriptVerdict("pass", ov, expected, t, "100% match — transcript matches intended speech")
    if ov < _FAIL_BELOW:
        return TranscriptVerdict("fail", ov, expected, t, f"garbled / drifted speech (token overlap {ov:.0%} < 85%)")
    return TranscriptVerdict("warning", ov, expected, t, f"minor drift (token overlap {ov:.0%}) — review before delivery")
