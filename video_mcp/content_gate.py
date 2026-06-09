"""Pre-submit content gate.

Two layers, run before any paid generation:
  1. Heuristic (always, deterministic): blocks young/minor descriptors and any
     reference-processing words (posterize/grid/dither) leaking into the prompt.
  2. LLM (optional, Gemma via LMStudio/OpenRouter): blocks prompts that describe a
     minor / young / underage person or a real, identifiable named person.

Personas must be framed as FICTIONAL ADULTS; references as "not a direct copy".
"""

from __future__ import annotations

import re

from video_mcp.config import Settings
from video_mcp.errors import ContentPolicyError
from video_mcp.logging_config import get_logger
from video_mcp.utils.llm import chat_with_fallback

logger = get_logger(__name__)

# Young / minor descriptors — never describe a subject this way; use "adult".
_AGE = re.compile(
    r"\b(?:young|younger|youthful|teen|teens|teenage[d]?|teenager|adolescent[s]?|minor[s]?|"
    r"under-?age[d]?|child(?:ren|like)?|kid[s]?|toddler|infant|bab(?:y|ies)|pre-?teen[s]?|"
    r"schoolgirl|schoolboy|lolita|jail-?bait|barely[ -]?legal)\b",
    re.IGNORECASE,
)
# Reference-processing terms must never appear in the paste-ready prompt.
_PROCESSING = re.compile(
    r"\b(?:posteriz\w*|dither\w*|halftone|grid(?:ded|s|lines?|line)?|"
    r"processed reference|reference plate|edited plate)\b",
    re.IGNORECASE,
)

_LLM_SYSTEM = (
    "You are a content-safety classifier for an AI video generator of FICTIONAL ADULT "
    "personas. Reply with EXACTLY one line. Reply 'BLOCK: <short reason>' if the prompt "
    "describes or implies a minor, young, teenage, or underage person, OR a real, "
    "identifiable, named real person (a celebrity or public figure). Otherwise reply 'OK'."
)


def heuristic_flags(prompt: str) -> dict[str, list[str]]:
    return {"age": _AGE.findall(prompt or ""), "processing": _PROCESSING.findall(prompt or "")}


def assert_heuristic_clean(prompt: str) -> None:
    flags = heuristic_flags(prompt)
    if flags["age"]:
        raise ContentPolicyError(
            f"prompt uses young/minor descriptor(s) {sorted(set(t.lower() for t in flags['age']))}; "
            "frame the subject as a fictional ADULT creator instead."
        )
    if flags["processing"]:
        raise ContentPolicyError(
            f"prompt mentions reference-processing {sorted(set(t.lower() for t in flags['processing']))}; "
            "keep the clean prompt and only swap image_urls — never describe grid/posterize in the prompt."
        )


async def assert_prompt_clean(prompt: str, settings: Settings, *, use_llm: bool = True) -> None:
    """Raise ContentPolicyError if `prompt` violates the content policy.

    Heuristic always runs. The LLM gate runs when `use_llm` and a model is reachable;
    if the LLM is unreachable it is skipped (the heuristic is the floor), not fatal.
    """
    assert_heuristic_clean(prompt)
    if not use_llm:
        return
    verdict = await chat_with_fallback(
        settings,
        [{"role": "system", "content": _LLM_SYSTEM}, {"role": "user", "content": prompt}],
        max_tokens=64,
    )
    if verdict is None:
        logger.warning("content LLM gate unreachable; relying on heuristic only")
        return
    if verdict.strip().upper().startswith("BLOCK"):
        raise ContentPolicyError(f"content gate: {verdict.strip()}")
