"""Hebrew -> Latin transliteration for lip-sync prompts, via an LLM + a structural gate.

Rule-based letter mapping cannot recover the unwritten vowels of an abjad
(שלום has no letter for the `a` in "shalom"), so transliteration is delegated to
an LLM. Hebrew morphology (gender endings, vowel recovery, hitpael clusters) is
where small local models fail, so the resolution order is:

    1. OpenRouter with a dedicated strong model  (default google/gemini-2.5-flash)
    2. local LMStudio                            (offline fallback)

(`TRANSLITERATE_PRIMARY=lmstudio` flips the order.)

Every candidate — LLM-generated or agent-supplied — must pass
`validate_romanization`: no Hebrew script, English tokens copied verbatim,
word counts aligned, no vowel-dropped/unpronounceable words. The gate is
structural; it cannot judge vowel *quality* — agents that wrote the Hebrew
should supply their own romanization (`romanized_text`) instead of trusting
the LLM.

`has_hebrew` stays a cheap pure function used for detection/validation.
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
    "spelling. Output ONLY the romanized text on one line — no quotes, no notes, no Hebrew.\n\n"
    "Rules:\n"
    "1. Keep punctuation, numbers, and non-Hebrew words EXACTLY unchanged (brand/CTA "
    "tokens like 'AI' or 'Flycard' are copied byte-for-byte).\n"
    "2. Every word must be pronounceable — never drop vowels: תקשיבו -> takshivu "
    "(NOT tkshivu).\n"
    "3. Respect gender agreement in verb/adjective endings: feminine subjects take -ah/-et "
    "— חברה רוצה -> chevra rotzah (NOT rotzeh).\n"
    "4. Keep audible consonant clusters: hitpael משתנה -> mishtaneh (NOT mistaneh).\n"
    "5. No epenthetic vowels: חברה -> chevra (NOT chevera).\n"
    "6. The LAST word of each sentence matters most for lip-sync — transliterate it with "
    "extra care.\n\n"
    "Examples:\n"
    "שלום עולם -> shalom olam\n"
    "קנו עכשיו את המוצר שלנו -> knu achshav et hamutzar shelanu\n"
    "תקשיבו, ההייטק הישראלי משתנה -> takshivu, hahaytek hayisraeli mishtaneh\n"
    "זה מה שכל חברה רוצה -> zeh ma shekol chevra rotzah\n"
    "AI זה כבר לא Buzzword -> AI zeh kvar lo Buzzword"
)

# Latin tokens embedded in the Hebrew source (brands, CTAs, acronyms).
_LATIN_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9'-]*")
# Digraphs that romanize ONE Hebrew consonant — collapsed before cluster checks.
_DIGRAPH_RE = re.compile(r"sh|ch|tz|ts|kh|zh", re.IGNORECASE)
_VOWELS_RE = re.compile(r"[aeiouy']")


def has_hebrew(text: str) -> bool:
    """True if `text` contains any Hebrew-block char (U+0590..U+05FF, U+FB1D..U+FB4F)."""
    for ch in text:
        cp = ord(ch)
        if 0x0590 <= cp <= 0x05FF or 0xFB1D <= cp <= 0xFB4F:
            return True
    return False


def validate_romanization(hebrew_text: str, romanized: str) -> list[str]:
    """Structural gate for a romanization of `hebrew_text`. Returns problems ([] = ok).

    Checks what is deterministically checkable: no Hebrew script, English tokens
    preserved verbatim, word-count alignment, and no vowel-dropped words
    (vowelless or 3+-consonant onsets after digraph collapsing). It cannot judge
    vowel QUALITY — that is on the model/agent that produced the romanization.
    """
    rom = (romanized or "").strip()
    if not rom:
        return ["romanization is empty"]
    problems: list[str] = []
    if has_hebrew(rom):
        problems.append("romanization still contains Hebrew characters")

    latin_tokens = _LATIN_TOKEN_RE.findall(hebrew_text)
    rom_words_lower = {w.lower() for w in re.findall(r"[A-Za-z0-9'-]+", rom)}
    for tok in latin_tokens:
        if tok.lower() not in rom_words_lower:
            problems.append(f"English token {tok!r} missing — copy it verbatim")

    n_he, n_rom = len(hebrew_text.split()), len(rom.split())
    if not (n_he * 0.7 - 1 <= n_rom <= n_he * 1.3 + 1):
        problems.append(f"word count mismatch: Hebrew has {n_he} words, romanization has {n_rom}")

    skip = {t.lower() for t in latin_tokens}
    for word in re.findall(r"[A-Za-z']+", rom):
        lw = word.lower()
        if lw in skip:
            continue
        if len(lw) >= 4 and not _VOWELS_RE.search(lw):
            problems.append(f"unpronounceable word {word!r} — a vowel was dropped")
            continue
        # Collapse digraphs (sh/ch/tz/...) to one symbol, then flag 3+-consonant onsets
        # (tkshivu) — legit shva onsets (knu, shtayim) are 2 consonants.
        collapsed = _DIGRAPH_RE.sub("S", lw)
        onset = re.match(r"[^aeiouy']+", collapsed)
        if onset and len(onset.group()) >= 3:
            problems.append(f"unpronounceable onset in {word!r} — a vowel was dropped")
    return problems


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
    """Transliterate `text` to Latin (OpenRouter-first by default, LMStudio fallback).

    Each provider's output must pass `validate_romanization`; a gate failure counts
    as a provider failure and the next provider is tried. Raises
    TransliterationError when every provider fails or is rejected.
    """
    settings = settings or get_settings()
    if not has_hebrew(text):
        return text  # nothing to do; pass through Latin/punct/numbers unchanged

    openrouter = (
        ("OpenRouter", settings.openrouter_base_url, settings.transliterate_openrouter_model,
         settings.openrouter_api_key)
        if settings.openrouter_api_key
        else None
    )
    lmstudio = ("LMStudio", settings.lmstudio_base_url, settings.lmstudio_model, None)
    providers = [openrouter, lmstudio] if settings.transliterate_primary == "openrouter" else [lmstudio, openrouter]

    errors: list[str] = []
    if openrouter is None:
        errors.append("OpenRouter: OPENROUTER_API_KEY not set")
    for provider in providers:
        if provider is None:
            continue
        name, base_url, model, api_key = provider
        try:
            result = await _chat(
                base_url=base_url, model=model, text=text,
                max_tokens=settings.transliterate_max_tokens,
                timeout=settings.transliterate_timeout_s,
                api_key=api_key, client=client,
            )
        except (httpx.HTTPError, TransliterationError) as exc:
            errors.append(f"{name}: {exc}")
            continue
        problems = validate_romanization(text, result)
        if not problems:
            logger.info("transliterated via %s (%s)", name, model)
            return result
        errors.append(f"{name} output rejected by gate: {'; '.join(problems)} (got {result!r})")

    raise TransliterationError("Hebrew transliteration failed. " + " | ".join(errors))
