"""Shared OpenAI-compatible chat helper: local LMStudio first, OpenRouter fallback.

Used by the content gate (and available to any module needing a quick LLM call).
"""

from __future__ import annotations

import re

import httpx

from video_mcp.config import Settings
from video_mcp.logging_config import get_logger

logger = get_logger(__name__)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)


def _clean(content: str) -> str:
    return _THINK_RE.sub("", content or "").strip()


async def _one(base_url: str, model: str, messages: list[dict], *, api_key: str | None,
               max_tokens: int, timeout: float, client: httpx.AsyncClient | None) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {"model": model, "messages": messages, "temperature": 0, "max_tokens": max_tokens}
    owns = client is None
    client = client or httpx.AsyncClient(timeout=timeout)
    try:
        resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
    finally:
        if owns:
            await client.aclose()
    choices = data.get("choices") or []
    return _clean(choices[0].get("message", {}).get("content") or "") if choices else ""


async def chat_with_fallback(
    settings: Settings,
    messages: list[dict],
    *,
    max_tokens: int = 256,
    client: httpx.AsyncClient | None = None,
) -> str | None:
    """Return the assistant text, trying LMStudio then OpenRouter. None if both fail."""
    try:
        return await _one(settings.lmstudio_base_url, settings.lmstudio_model, messages,
                          api_key=None, max_tokens=max_tokens, timeout=settings.transliterate_timeout_s,
                          client=client)
    except (httpx.HTTPError, KeyError, ValueError) as exc:
        logger.debug("LMStudio chat failed: %s", exc)
    if settings.openrouter_api_key:
        try:
            return await _one(settings.openrouter_base_url, settings.openrouter_model, messages,
                              api_key=settings.openrouter_api_key, max_tokens=max_tokens,
                              timeout=settings.transliterate_timeout_s, client=client)
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            logger.debug("OpenRouter chat failed: %s", exc)
    return None
