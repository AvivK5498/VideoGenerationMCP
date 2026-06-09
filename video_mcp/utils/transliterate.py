"""Hebrew -> Latin transliteration for lip-sync prompts, via an LLM.

Rule-based letter mapping cannot recover the unwritten vowels of an abjad
(שלום has no letter for the `a` in "shalom"), so transliteration is delegated to
an LLM. Resolution order:

    1. local LMStudio server  (default model: nvidia/nemotron-3-nano-4b)
    2. OpenRouter             (fallback; needs OPENROUTER_API_KEY)

`has_hebrew` stays a cheap pure function used for detection/validation; only
`transliterate_hebrew` makes a network call.
"""

from __future__ import annotations

import re

import httpx

from video_mcp.config import Settings, get_settings
from video_mcp.errors import TransliterationError
from video_mcp.logging_config import get_logger, redact

logger = get_logger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)

_SYSTEM_PROMPT = (
    "You are a precise Hebrew-to-Latin phonetic transliterator for a video lip-sync "
    "engine. Convert the Hebrew the user sends into natural, readable phonetic Latin "
    "spelling. Keep punctuation, numbers, and non-Hebrew words unchanged. Output ONLY "
    "the romanized text on one line — no quotes, no notes, no Hebrew.\n\n"
    "Examples:\n"
    "שלום עולם -> shalom olam\n"
    "קנו עכשיו את המוצר שלנו -> knu achshav et hamutzar shelanu\n"
    "אני אוהב אותך -> ani ohev otach"
)


def has_hebrew(text: str) -> bool:
    """True if `text` contains any Hebrew-block char (U+0590..U+05FF, U+FB1D..U+FB4F)."""
    for ch in text:
        cp = ord(ch)
        if 0x0590 <= cp <= 0x05FF or 0xFB1D <= cp <= 0xFB4F:
            return True
    return False


def _clean(content: str) -> str:
    """Strip reasoning tags, surrounding quotes, and whitespace from model output."""
    content = _THINK_RE.sub("", content)
    content = content.strip()
    # Some models still wrap the answer in quotes despite instructions.
    if len(content) >= 2 and content[0] in "\"'" and content[-1] == content[0]:
        content = content[1:-1].strip()
    return content


def _messages(text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": text},
    ]


async def _chat(
    *, base_url: str, model: str, text: str, max_tokens: int, timeout: float,
    api_key: str | None, client: httpx.AsyncClient | None,
) -> str:
    """One OpenAI-compatible /chat/completions call. Returns cleaned content."""
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": _messages(text),
        "temperature": 0,
        "max_tokens": max_tokens,
    }
    logger.debug("transliterate request -> %s %s", url, redact({**payload, "headers": headers}))

    owns_client = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns_client:
            await client.aclose()

    choices = data.get("choices") or []
    if not choices:
        raise TransliterationError(f"no choices in response from {model}")
    return _clean(choices[0].get("message", {}).get("content") or "")


async def transliterate_hebrew(
    text: str,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> str:
    """Transliterate `text` to Latin via LMStudio, falling back to OpenRouter.

    Raises TransliterationError if both providers fail or the result still
    contains Hebrew characters (we never silently emit a bad romanization).
    """
    settings = settings or get_settings()
    if not has_hebrew(text):
        return text  # nothing to do; pass through Latin/punct/numbers unchanged

    errors: list[str] = []

    # 1. local LMStudio
    try:
        result = await _chat(
            base_url=settings.lmstudio_base_url, model=settings.lmstudio_model, text=text,
            max_tokens=settings.transliterate_max_tokens, timeout=settings.transliterate_timeout_s,
            api_key=None, client=client,
        )
        if result and not has_hebrew(result):
            logger.info("transliterated via LMStudio (%s)", settings.lmstudio_model)
            return result
        errors.append(f"LMStudio returned empty/Hebrew result: {result!r}")
    except (httpx.HTTPError, TransliterationError) as exc:
        errors.append(f"LMStudio: {exc}")

    # 2. OpenRouter fallback
    if settings.openrouter_api_key:
        try:
            result = await _chat(
                base_url=settings.openrouter_base_url, model=settings.openrouter_model, text=text,
                max_tokens=settings.transliterate_max_tokens, timeout=settings.transliterate_timeout_s,
                api_key=settings.openrouter_api_key, client=client,
            )
            if result and not has_hebrew(result):
                logger.info("transliterated via OpenRouter (%s)", settings.openrouter_model)
                return result
            errors.append(f"OpenRouter returned empty/Hebrew result: {result!r}")
        except (httpx.HTTPError, TransliterationError) as exc:
            errors.append(f"OpenRouter: {exc}")
    else:
        errors.append("OpenRouter: OPENROUTER_API_KEY not set")

    raise TransliterationError("Hebrew transliteration failed. " + " | ".join(errors))
