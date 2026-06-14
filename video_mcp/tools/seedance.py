"""FastMCP tool: Seedance 2.0 video generation (generate_seedance_video).

The crown jewel is the Hebrew BVAC auto-chain. Per the seedance2 / bvac skills:
- speech is synthesized (eleven_v3, he) and MUXED into a black 9:16 carrier video;
- the carrier is referenced as @video1 with the plain-language lip-sync mechanism
  sentence + the ROMANIZED transcript embedded in the prompt (Seedance reads Latin
  more reliably than Hebrew script);
- two audio gates run via ElevenLabs Scribe: the source MP3 and the generated-video
  audio. 100% match = pass, 85-99% = warning, <85% = error (raises).
"""

from __future__ import annotations

import os
import tempfile
from typing import Any

import httpx
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from video_mcp.content_gate import assert_prompt_clean
from video_mcp.errors import VideoMCPError
from video_mcp.logging_config import get_logger, redact
from video_mcp.moderation import is_moderation_failure
from video_mcp.qa import compare_transcripts
from video_mcp.routing import is_hebrew_request, round_duration_to_allowed
from video_mcp.schemas.elevenlabs import HEBREW_MODEL, VoiceoverRequest
from video_mcp.schemas.seedance import SeedanceVideoRequest
from video_mcp.tools import Deps
from video_mcp.utils import carrier as carrier_mod
from video_mcp.utils import media as media_mod
from video_mcp.utils import uploader as uploader_mod
from video_mcp.utils.transliterate import has_hebrew, transliterate_hebrew, validate_phonemic

logger = get_logger(__name__)

_MECHANISM = (
    "Use @Video1 only as an audio-timing and lip-sync reference; ignore its black visuals. "
    "The character speaks the audio from @Video1 in perfect lip-sync, matching every word."
)

# Default role sentences when the caller does not supply image_roles. All framed as a
# fictional adult creator, references explicitly "not a direct copy".
_DEFAULT_IMAGE_ROLES = [
    "an identity and grounded personal-style reference, not a direct copy, for the fictional adult "
    "creator's face, hair, body proportions, styling, and vibe",
    "body continuity and natural posture for the same fictional adult creator",
    "fast persuasive expressions for the same fictional adult creator: direct eye contact, slight "
    "smirk, small eyebrow raises, controlled hand gestures",
]


_OTHER_ROLE = "a scene/environment reference for location, props, lighting, and spatial continuity"


def _compose_reference_lines(
    humans: list[str], others: list[str],
    image_roles: list[str] | None, other_roles: list[str] | None,
) -> str:
    """'Use @ImageN as <role>.' per reference. Humans first (positions 1..H), then others.

    Fixed human-then-other ordering keeps the @ImageN tags stable across bypass
    resubmissions (only the human refs are re-processed)."""
    lines, idx = [], 1
    for i in range(len(humans)):
        if image_roles and i < len(image_roles):
            role = image_roles[i]
        elif i < len(_DEFAULT_IMAGE_ROLES):
            role = _DEFAULT_IMAGE_ROLES[i]
        else:
            role = "an additional grounded personal-style reference, not a direct copy, for the fictional adult creator"
        lines.append(f"Use @Image{idx} as {role}.")
        idx += 1
    for j in range(len(others)):
        role = other_roles[j] if other_roles and j < len(other_roles) else _OTHER_ROLE
        lines.append(f"Use @Image{idx} as {role}.")
        idx += 1
    return " ".join(lines)


def _require_asset_humans(humans: list[str], auto_upload: bool) -> None:
    """Generated people must be private assets: human refs must be asset:// ids."""
    if auto_upload:
        return
    bad = [u for u in humans if not u.startswith("asset://")]
    if bad:
        raise ToolError(
            "human (person) references must be private assets — pass asset://<id> values "
            f"(register them with upload_asset first). Got non-asset refs: {bad}. "
            "Or set auto_upload_assets=true to ingest them per-job."
        )


def register_seedance_tools(mcp: FastMCP, deps: Deps) -> None:
    """Register the Seedance video tool on `mcp`."""

    @mcp.tool
    async def generate_seedance_video(
        prompt: str,
        language: str = "en",
        task_type: str = "seedance-2-less-restriction",
        mode: str | None = None,
        duration: int = 5,
        resolution: str = "720p",
        aspect_ratio: str | None = None,
        image_urls: list[str] | None = None,
        human_image_urls: list[str] | None = None,
        other_image_urls: list[str] | None = None,
        video_urls: list[str] | None = None,
        audio_urls: list[str] | None = None,
        text: str | None = None,
        voice_id: str | None = None,
        audio_path: str | None = None,
        romanized_text: str | None = None,
        image_roles: list[str] | None = None,
        other_roles: list[str] | None = None,
        auto_upload_assets: bool = False,
        asset_retention_hours: int = 3,
        service_mode: str | None = None,
        verify_speech: bool = True,
        content_check: bool = True,
        wait: bool = False,
    ) -> dict[str, Any]:
        """Generate a Seedance video; auto-chain Hebrew BVAC lipsync when language is Hebrew.

        HEBREW (language="he") — this tool runs the ENTIRE BVAC chain itself; do NOT
        pre-build anything:
        - Speech: synthesized from `text` (keep it Hebrew) with ElevenLabs eleven_v3 and
          `voice_id` — OR pass `audio_path` (local mp3) to use a pre-approved take and
          skip TTS. Audition flow: generate_elevenlabs_voiceover -> user approves ->
          pass its audio_path here. Never build a black carrier, upload audio, or
          register a carrier asset yourself; the tool does all of it and ignores yours.
        - Prompt: pass ONLY the scene description, Latin-only (transliterate_hebrew
          first). The "@ImageN is ..." / "@Video1 ..." reference lines and the lip-sync
          mechanism are composed server-side — do not write them yourself (customize
          via image_roles / other_roles).
        - `romanized_text`: ALWAYS supply your own PHONEMIC RESPELLING of `text` —
          spell the Hebrew the way an English reader sounds it out, because Seedance
          picks visemes from this text with an English-dominant classifier (linguistic
          romanization makes it mouth English: chazir -> "church"). Form: syllable-
          hyphenated, stressed syllable in CAPS, ' for schwa — חזיר -> khah-ZEER (NOT
          chazir); גבר, קום מהספה -> GEH-ver, koom meh-hah-SAH-pah; כושר -> KOH-sher.
          Every syllable sayable; gender/morphology respected but rendered by English
          sound; English/brand tokens byte-for-byte; sentence-final words with extra
          care (they drive the lip-sync hardest). A structural gate validates it; omit
          it and an LLM (OpenRouter-first) respells instead.
        - task_type is forced to seedance-2-less-restriction: the lower-moderation tier
          required for asset-backed fictional personas. Requesting another type has no
          effect; this is intentional, not an error.
        - Scribe QA gates run on the source audio, and on the generated video when
          wait=true.

        References split into human_image_urls (faces/people) and other_image_urls
        (product/room/scene). Generated people MUST be private assets: human refs have
        to be `asset://<id>` (register them with upload_asset first) unless
        auto_upload_assets=true. `image_urls` is a legacy alias for human_image_urls.
        """
        humans = human_image_urls or image_urls or []
        others = other_image_urls or []
        _require_asset_humans(humans, auto_upload_assets)

        if is_hebrew_request(language):
            return await _hebrew_chain(
                deps,
                prompt=prompt,
                text=text,
                voice_id=voice_id,
                audio_path=audio_path,
                romanized_text=romanized_text,
                humans=humans,
                others=others,
                image_roles=image_roles,
                other_roles=other_roles,
                auto_upload_assets=auto_upload_assets,
                asset_retention_hours=asset_retention_hours,
                duration=duration,
                resolution=resolution,
                aspect_ratio=aspect_ratio or "9:16",  # UGC vertical
                service_mode=service_mode,
                verify_speech=verify_speech,
                content_check=content_check,
                wait=wait,
            )

        try:
            await assert_prompt_clean(prompt, deps.settings, use_llm=content_check)
            req = SeedanceVideoRequest(
                prompt=prompt,
                task_type=task_type,  # type: ignore[arg-type]
                mode=mode,  # type: ignore[arg-type]
                duration=duration,
                resolution=resolution,  # type: ignore[arg-type]
                aspect_ratio=aspect_ratio or "16:9",  # type: ignore[arg-type]
                image_urls=(humans + others) or None,
                video_urls=video_urls,
                audio_urls=audio_urls,
                auto_upload_assets=auto_upload_assets,
                asset_retention_hours=asset_retention_hours,
                service_mode=service_mode,  # type: ignore[arg-type]
            )
        except (ValidationError, VideoMCPError) as exc:
            raise ToolError(str(exc)) from exc

        return await _submit(deps, req, wait=wait)

    @mcp.tool
    async def verify_generated_audio(
        text: str,
        task_id: str | None = None,
        video_url: str | None = None,
    ) -> dict[str, Any]:
        """Run the generated-video Scribe QA gate on a finished Seedance task.

        Use this after an async (wait=false) Hebrew lipsync job completes: pass the
        original spoken `text` (Hebrew) plus the `task_id` (or a direct `video_url`).
        Downloads the video, extracts its audio, transcribes with ElevenLabs Scribe,
        and judges against `text` (100% pass / 85-99% warning / <85% raises).
        Do not substitute local whisper or other ASR — this is the canonical gate.
        """
        if not video_url:
            if not task_id:
                raise ToolError("provide `task_id` or `video_url`.")
            try:
                result = await deps.piapi.get_task(task_id)
            except VideoMCPError as err:
                raise ToolError(str(err)) from err
            video_url = result.video_url
            if not video_url:
                raise ToolError(
                    f"task {task_id} has no video yet (status={result.status}). "
                    "Keep polling with get_task until it completes."
                )

        gfd, gen_video = tempfile.mkstemp(suffix=".mp4", prefix="seedance_gen_")
        os.close(gfd)
        gen_audio = gen_video.replace(".mp4", ".mp3")
        try:
            await _download(video_url, gen_video)
            carrier_mod.extract_audio(gen_video, gen_audio, ffmpeg_bin=deps.settings.ffmpeg_bin)
        except (VideoMCPError, httpx.HTTPError) as err:
            raise ToolError(f"generated-video gate: could not fetch/extract audio: {err}") from err
        verdict = await _scribe_gate(deps, gen_audio, text, label="generated-video gate")
        return {**verdict, "video_url": video_url}


async def _submit(deps: Deps, req: SeedanceVideoRequest, *, wait: bool, extra: dict | None = None) -> dict[str, Any]:
    config = {"service_mode": req.service_mode} if req.service_mode else None
    try:
        result = await deps.piapi.create_task(
            model="seedance", task_type=req.task_type, input=req.to_piapi_input(), config=config,
        )
        if wait:
            result = await deps.piapi.wait_for_task(result.task_id)
    except VideoMCPError as err:
        raise ToolError(str(err)) from err

    out: dict[str, Any] = {
        "task_id": result.task_id,
        "status": result.status,
        "video_url": result.video_url,
        "mode": req.mode,
        "task_type": req.task_type,
        "aspect_ratio": req.aspect_ratio,
    }
    if result.is_failed:
        out["failure_reason"] = "moderation" if is_moderation_failure(result.error_message) else "other"
        out["provider_message"] = result.error_message
    if extra:
        out.update(extra)
    return out


async def _download(url: str, path: str) -> str:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        with open(path, "wb") as fh:
            fh.write(resp.content)
    return path


async def _scribe_gate(deps: Deps, audio_path: str, expected_text: str, *, label: str) -> dict[str, Any]:
    """Transcribe `audio_path` with Scribe and judge it against `expected_text`.

    Raises ToolError when the verdict is `fail` (garbled / wrong-language / <85%).
    Returns the verdict dict otherwise (verdict may be `pass` or `warning`).
    """
    try:
        scribe = await deps.eleven.transcribe(audio_path, language_code="he")
    except VideoMCPError as err:
        raise ToolError(f"{label}: Scribe transcription failed: {err}") from err
    verdict = compare_transcripts(expected_text, scribe.get("text", ""))
    logger.info("%s scribe gate: %s", label, redact(verdict.as_dict()))
    if verdict.is_garbled:
        raise ToolError(f"{label} FAILED: {verdict.notes}. transcript={verdict.transcript!r}")
    return {**verdict.as_dict(), "gate": label}


async def _hebrew_chain(
    deps: Deps,
    *,
    prompt: str,
    text: str | None,
    voice_id: str | None,
    audio_path: str | None,
    romanized_text: str | None,
    humans: list[str],
    others: list[str],
    image_roles: list[str] | None,
    other_roles: list[str] | None,
    auto_upload_assets: bool,
    asset_retention_hours: int,
    duration: int,
    resolution: str,
    aspect_ratio: str,
    service_mode: str | None,
    verify_speech: bool,
    content_check: bool,
    wait: bool,
) -> dict[str, Any]:
    """Run the Hebrew BVAC lipsync auto-chain."""
    # The VISUAL prompt must be Latin; the spoken `text` is exempt.
    if has_hebrew(prompt):
        raise ToolError(
            "Hebrew detected in the visual `prompt`. Seedance prompts must be Latin-only — "
            "call transliterate_hebrew on the prompt first. (The spoken `text` may stay Hebrew.)"
        )
    if not text:
        raise ToolError("Hebrew lipsync requires the spoken `text` argument (Hebrew is correct here).")
    if not voice_id and not audio_path:
        raise ToolError(
            "Hebrew lipsync requires either `voice_id` (ElevenLabs TTS) or `audio_path` "
            "(a pre-approved local mp3 of the same `text`)."
        )
    if audio_path:
        if not os.path.isfile(audio_path):
            raise ToolError(f"audio_path not found: {audio_path}")
        try:
            resolved_for_audio = round_duration_to_allowed(duration)
            audio_len = media_mod.probe_duration(audio_path, ffprobe_bin=deps.settings.ffprobe_bin)
        except (ValueError, VideoMCPError) as exc:
            raise ToolError(str(exc)) from exc
        if audio_len > resolved_for_audio:
            raise ToolError(
                f"audio_path is {audio_len:.2f}s but the clip is {resolved_for_audio}s — the speech "
                "would be cut off. Use a longer duration (5/10/15) or split the audio "
                "(split_audio) across multiple clips."
            )

    # Phonemic transcript for the prompt: spell the Hebrew by ENGLISH SOUND so
    # Seedance's English-dominant viseme classifier mouths Hebrew (chazir mouths
    # "church"; khah-ZEER mouths correctly). An agent-supplied respelling beats
    # the LLM (the agent wrote the script and knows the morphology) — it just has
    # to pass the structural gate.
    if romanized_text:
        problems = validate_phonemic(text, romanized_text)
        if problems:
            raise ToolError(
                "romanized_text failed validation: " + "; ".join(problems) +
                ". Fix the phonemic respelling (spell by English sound — khah-ZEER, "
                "not chazir; every syllable sayable; English/brand tokens verbatim; "
                "one token per Hebrew word ± prefixes)."
            )
        romanized = romanized_text.strip()
    else:
        try:
            romanized = await transliterate_hebrew(text, deps.settings)
        except VideoMCPError as err:
            raise ToolError(f"phonemic respelling of transcript failed: {err}") from err

    # Compose the BVAC prompt and run the cheap gates NOW — before any paid
    # ElevenLabs/upload call. Role-mapped @ImageN refs (humans then others, adult
    # framing) + scene + mechanism (@Video1) + phonemic pronunciation guide.
    refs = humans + others
    subject_line = _compose_reference_lines(humans, others, image_roles, other_roles)
    parts = [p for p in (subject_line, prompt.strip()) if p]
    scene_prompt = " ".join(parts)
    bvac_prompt = (
        f"{scene_prompt}\n\n{_MECHANISM}\n"
        f"Pronunciation guide (spelled by English sound, NOT English words): \"{romanized}\""
    )

    if len(bvac_prompt) > 4000:
        overhead = len(bvac_prompt) - len(prompt.strip())
        raise ToolError(
            f"composed prompt is {len(bvac_prompt)} chars (limit 4000). The server adds "
            f"~{overhead} chars of reference/mechanism/transcript lines around your scene "
            f"prompt — shorten the scene prompt to under ~{4000 - overhead} chars."
        )

    # Content gate the SCENE PROMPT ONLY (subject lines + agent scene prompt) — NOT the
    # embedded phonemic pronunciation guide. The romanized guide is Hebrew spelled by
    # English sound; a Hebrew word like קדמית respells to "kid-MEET", and \bkid\b would
    # false-positive the age heuristic even though no minor is described. The romanized
    # guide carries no English scene semantics; the actual spoken Hebrew `text` is screened
    # upstream by the Spot harness's LLM classifier before spend. (Length is still checked
    # on the full bvac_prompt above.)
    try:
        await assert_prompt_clean(scene_prompt, deps.settings, use_llm=content_check)
    except VideoMCPError as err:
        raise ToolError(str(err)) from err

    if not audio_path:
        # Synthesize Hebrew speech (eleven_v3, language_code "he").
        try:
            voice_req = VoiceoverRequest(
                text=text, voice_id=voice_id, language="he", model_id=HEBREW_MODEL, with_timestamps=True
            )
        except ValidationError as exc:
            raise ToolError(str(exc)) from exc
        try:
            audio, _alignment = await deps.eleven.tts_with_timestamps(voice_req)
        except VideoMCPError as err:
            raise ToolError(str(err)) from err

        fd, audio_path = tempfile.mkstemp(suffix=".mp3", prefix="seedance_he_")
        with open(fd, "wb") as fh:
            fh.write(audio)

    # GATE 1 — source MP3 must be coherent Hebrew before we build the carrier.
    source_qa = None
    if verify_speech:
        source_qa = await _scribe_gate(deps, audio_path, text, label="source-mp3 gate")

    try:
        resolved_duration = round_duration_to_allowed(duration)
    except ValueError as exc:
        raise ToolError(str(exc)) from exc

    # Black 9:16 carrier with the Hebrew speech MUXED IN (true BVAC).
    cfd, carrier_path = tempfile.mkstemp(suffix=".mp4", prefix="seedance_carrier_")
    os.close(cfd)
    try:
        carrier_mod.make_black_carrier(
            resolved_duration, carrier_path, audio_path=audio_path, ffmpeg_bin=deps.settings.ffmpeg_bin
        )
        carrier_url = await uploader_mod.upload_file(carrier_path, upload_url=deps.settings.tmpfiles_upload_url)
    except VideoMCPError as err:
        raise ToolError(str(err)) from err

    try:
        req = SeedanceVideoRequest(
            prompt=bvac_prompt,
            task_type="seedance-2-less-restriction",
            mode="omni_reference",
            duration=resolved_duration,
            resolution=resolution,  # type: ignore[arg-type]
            aspect_ratio=aspect_ratio,  # type: ignore[arg-type]
            image_urls=refs or None,
            video_urls=[carrier_url],
            auto_upload_assets=auto_upload_assets,
            asset_retention_hours=asset_retention_hours,
            service_mode=service_mode,  # type: ignore[arg-type]
        )
    except ValidationError as exc:
        raise ToolError(str(exc)) from exc

    logger.info(
        "hebrew bvac chain: %s",
        redact({"carrier_url": carrier_url, "duration": resolved_duration, "romanized": romanized}),
    )
    result = await _submit(
        deps,
        req,
        wait=wait,
        extra={
            "carrier_url": carrier_url,
            "audio_path": audio_path,
            "carrier_path": carrier_path,
            "romanized_transcript": romanized,
            "bvac_prompt": bvac_prompt,
            "source_audio_qa": source_qa,
        },
    )

    # GATE 2 — generated-video audio. Only possible once we have a finished video.
    if verify_speech and wait and result.get("video_url"):
        gfd, gen_video = tempfile.mkstemp(suffix=".mp4", prefix="seedance_gen_")
        os.close(gfd)
        gen_audio = gen_video.replace(".mp4", ".mp3")
        try:
            await _download(result["video_url"], gen_video)
            carrier_mod.extract_audio(gen_video, gen_audio, ffmpeg_bin=deps.settings.ffmpeg_bin)
        except (VideoMCPError, httpx.HTTPError) as err:
            raise ToolError(f"generated-video gate: could not fetch/extract audio: {err}") from err
        result["generated_audio_qa"] = await _scribe_gate(deps, gen_audio, text, label="generated-video gate")
    elif verify_speech and not wait:
        result["generated_audio_qa"] = (
            "pending: once get_task reports completed, run verify_generated_audio"
            "(task_id=..., text=<the same Hebrew text>) to QA the generated speech"
        )

    return result
