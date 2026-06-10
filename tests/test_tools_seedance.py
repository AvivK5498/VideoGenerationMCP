"""Tests for the generate_seedance_video tool — self-contained.

Patches carrier/uploader/transliterate/download where they are USED (in
tools.seedance) and injects AsyncMock clients via Deps.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.config import Settings
from video_mcp.schemas.common import TaskResult
from video_mcp.tools import Deps
from video_mcp.tools.seedance import register_seedance_tools


@pytest.fixture(autouse=True)
def _stub_llm_gate(monkeypatch):
    from unittest.mock import AsyncMock
    monkeypatch.setattr("video_mcp.content_gate.chat_with_fallback", AsyncMock(return_value="OK"))


def make_settings() -> Settings:
    s = Settings()
    s.piapi_key = "pk"
    s.elevenlabs_key = "ek"
    return s


def make_deps(piapi: AsyncMock, eleven: AsyncMock) -> Deps:
    return Deps(settings=make_settings(), piapi=piapi, eleven=eleven)


def make_task_result(task_id: str = "task-1", status: str = "pending", video: str | None = None) -> TaskResult:
    out = {"video": video} if video else None
    return TaskResult(task_id=task_id, status=status, model="seedance", task_type="seedance-2", output=out)


async def get_tool(deps: Deps):
    mcp = FastMCP("test")
    register_seedance_tools(mcp, deps)
    tool = await mcp.get_tool("generate_seedance_video")
    return tool.fn


def _patch_chain(monkeypatch, romanized: str = "shalom olam"):
    """Patch carrier + uploader + transliterate where the tool uses them."""
    carrier = MagicMock(return_value="/tmp/carrier.mp4")
    monkeypatch.setattr("video_mcp.tools.seedance.carrier_mod.make_black_carrier", carrier)
    upload = AsyncMock(return_value="https://tmpfiles.org/dl/2/carrier.mp4")
    monkeypatch.setattr("video_mcp.tools.seedance.uploader_mod.upload_file", upload)
    translit = AsyncMock(return_value=romanized)
    monkeypatch.setattr("video_mcp.tools.seedance.transliterate_hebrew", translit)
    return carrier, upload, translit


# ---------------------------------------------------------------- Hebrew chain

async def test_hebrew_chain_bvac_payload(monkeypatch):
    carrier, upload, translit = _patch_chain(monkeypatch)
    piapi = AsyncMock()
    piapi.create_task.return_value = make_task_result()
    eleven = AsyncMock()
    eleven.tts_with_timestamps.return_value = (b"HEBREW_AUDIO", {"alignment": {}})
    fn = await get_tool(make_deps(piapi, eleven))

    res = await fn(
        prompt="A woman speaking to camera, cafe ambience",
        language="he",
        text="שלום עולם",
        voice_id="v1",
        duration=10,
        verify_speech=False,
    )

    # TTS (with timestamps), transliteration, carrier (audio muxed), one upload.
    eleven.tts_with_timestamps.assert_awaited_once()
    translit.assert_awaited_once()
    carrier.assert_called_once()
    assert "audio_path" in carrier.call_args.kwargs  # audio muxed into the carrier
    assert upload.await_count == 1  # carrier only (no separate audio upload)

    kwargs = piapi.create_task.await_args.kwargs
    assert kwargs["model"] == "seedance"
    assert kwargs["task_type"] == "seedance-2-less-restriction"
    inp = kwargs["input"]
    assert inp["mode"] == "omni_reference"
    assert inp["aspect_ratio"] == "9:16"  # forced vertical UGC
    assert inp["video_urls"] == ["https://tmpfiles.org/dl/2/carrier.mp4"]
    assert "audio_urls" not in inp  # carrier carries the audio
    # BVAC prompt rules embedded.
    assert "@Video1" in inp["prompt"]
    assert "ignore its black visuals" in inp["prompt"]
    assert "shalom olam" in inp["prompt"]

    assert res["aspect_ratio"] == "9:16"
    assert res["carrier_url"] == "https://tmpfiles.org/dl/2/carrier.mp4"
    assert res["romanized_transcript"] == "shalom olam"


async def test_hebrew_forwards_face_image_with_tag(monkeypatch):
    _patch_chain(monkeypatch)
    piapi = AsyncMock()
    piapi.create_task.return_value = make_task_result()
    eleven = AsyncMock()
    eleven.tts_with_timestamps.return_value = (b"AUDIO", {})
    fn = await get_tool(make_deps(piapi, eleven))

    await fn(prompt="cafe selfie scene", language="he", text="שלום עולם", voice_id="v1",
             human_image_urls=["asset://hila1"], duration=5, verify_speech=False)

    inp = piapi.create_task.await_args.kwargs["input"]
    assert inp["image_urls"] == ["asset://hila1"]            # human asset forwarded
    assert inp["video_urls"] == ["https://tmpfiles.org/dl/2/carrier.mp4"]
    assert "@Image1" in inp["prompt"]                        # face tagged
    assert "@Video1" in inp["prompt"]                        # carrier tagged


async def test_content_gate_blocks_young_woman(monkeypatch):
    # LLM stubbed OK by the autouse fixture; the heuristic must still block.
    _patch_chain(monkeypatch)
    fn = await get_tool(make_deps(AsyncMock(), AsyncMock()))
    with pytest.raises(ToolError) as ei:
        await fn(prompt="a young woman waving at the camera", language="en", duration=5)
    assert "adult" in str(ei.value).lower()


async def test_hebrew_raw_prompt_rejected(monkeypatch):
    carrier, upload, translit = _patch_chain(monkeypatch)
    piapi = AsyncMock()
    eleven = AsyncMock()
    fn = await get_tool(make_deps(piapi, eleven))

    with pytest.raises(ToolError) as ei:
        await fn(prompt="אישה מדברת למצלמה", language="he", text="שלום", voice_id="v1")
    assert "transliterate_hebrew" in str(ei.value)
    eleven.tts_with_timestamps.assert_not_called()
    carrier.assert_not_called()
    piapi.create_task.assert_not_called()


async def test_hebrew_text_passed_to_tts(monkeypatch):
    _patch_chain(monkeypatch)
    piapi = AsyncMock()
    piapi.create_task.return_value = make_task_result()
    eleven = AsyncMock()
    eleven.tts_with_timestamps.return_value = (b"AUDIO", {})
    fn = await get_tool(make_deps(piapi, eleven))

    await fn(prompt="A man waving hello", language="he", text="שלום חברים", voice_id="v1",
             duration=5, verify_speech=False)
    voice_req = eleven.tts_with_timestamps.await_args.args[0]
    assert voice_req.text == "שלום חברים"
    assert voice_req.model_id == "eleven_v3"


async def test_hebrew_requires_text_and_voice(monkeypatch):
    _patch_chain(monkeypatch)
    fn = await get_tool(make_deps(AsyncMock(), AsyncMock()))
    with pytest.raises(ToolError):
        await fn(prompt="Latin prompt", language="he", voice_id="v1", verify_speech=False)


# ------------------------------------------------- Pre-approved take (audio_path)

async def test_hebrew_audio_path_skips_tts(monkeypatch, tmp_path):
    carrier, upload, _ = _patch_chain(monkeypatch)
    take = tmp_path / "approved.mp3"
    take.write_bytes(b"APPROVED_AUDIO")
    piapi = AsyncMock()
    piapi.create_task.return_value = make_task_result()
    eleven = AsyncMock()
    fn = await get_tool(make_deps(piapi, eleven))

    res = await fn(prompt="scene", language="he", text="שלום עולם",
                   audio_path=str(take), duration=5, verify_speech=False)

    eleven.tts_with_timestamps.assert_not_called()           # no fresh TTS
    assert carrier.call_args.kwargs["audio_path"] == str(take)  # the approved take is muxed
    assert res["audio_path"] == str(take)
    piapi.create_task.assert_awaited_once()


async def test_hebrew_audio_path_still_runs_source_gate(monkeypatch, tmp_path):
    _patch_chain(monkeypatch)
    take = tmp_path / "approved.mp3"
    take.write_bytes(b"APPROVED_AUDIO")
    piapi = AsyncMock()
    piapi.create_task.return_value = make_task_result()
    eleven = AsyncMock()
    eleven.transcribe.return_value = {"text": "שלום עולם"}
    fn = await get_tool(make_deps(piapi, eleven))

    res = await fn(prompt="scene", language="he", text="שלום עולם",
                   audio_path=str(take), duration=5, verify_speech=True)
    eleven.transcribe.assert_awaited_once_with(str(take), language_code="he")
    assert res["source_audio_qa"]["verdict"] == "pass"


async def test_hebrew_audio_path_missing_file_errors(monkeypatch):
    carrier, _, _ = _patch_chain(monkeypatch)
    piapi = AsyncMock()
    eleven = AsyncMock()
    fn = await get_tool(make_deps(piapi, eleven))
    with pytest.raises(ToolError) as ei:
        await fn(prompt="scene", language="he", text="שלום",
                 audio_path="/nonexistent/take.mp3", verify_speech=False)
    assert "audio_path" in str(ei.value)
    eleven.tts_with_timestamps.assert_not_called()
    carrier.assert_not_called()
    piapi.create_task.assert_not_called()


async def test_hebrew_requires_voice_or_audio_path(monkeypatch):
    _patch_chain(monkeypatch)
    fn = await get_tool(make_deps(AsyncMock(), AsyncMock()))
    with pytest.raises(ToolError) as ei:
        await fn(prompt="Latin prompt", language="he", text="שלום", verify_speech=False)
    msg = str(ei.value)
    assert "voice_id" in msg and "audio_path" in msg


# ---------------------------------------------------------------- Scribe gates

async def test_source_gate_pass(monkeypatch):
    _patch_chain(monkeypatch)
    piapi = AsyncMock()
    piapi.create_task.return_value = make_task_result()
    eleven = AsyncMock()
    eleven.tts_with_timestamps.return_value = (b"AUDIO", {})
    eleven.transcribe.return_value = {"text": "שלום עולם"}  # 100% match
    fn = await get_tool(make_deps(piapi, eleven))

    res = await fn(prompt="scene", language="he", text="שלום עולם", voice_id="v1",
                   duration=5, verify_speech=True, wait=False)
    eleven.transcribe.assert_awaited_once()  # source gate ran
    assert res["source_audio_qa"]["verdict"] == "pass"
    assert "pending" in res["generated_audio_qa"]  # no wait -> deferred


async def test_source_gate_garbled_raises(monkeypatch):
    _patch_chain(monkeypatch)
    piapi = AsyncMock()
    eleven = AsyncMock()
    eleven.tts_with_timestamps.return_value = (b"AUDIO", {})
    eleven.transcribe.return_value = {"text": ""}  # empty -> garbled -> fail
    fn = await get_tool(make_deps(piapi, eleven))

    with pytest.raises(ToolError) as ei:
        await fn(prompt="scene", language="he", text="שלום עולם", voice_id="v1",
                 duration=5, verify_speech=True)
    assert "source-mp3 gate FAILED" in str(ei.value)
    piapi.create_task.assert_not_called()  # never submitted


async def test_generated_gate_runs_on_wait(monkeypatch):
    _patch_chain(monkeypatch)
    monkeypatch.setattr("video_mcp.tools.seedance._download", AsyncMock(return_value="/tmp/gen.mp4"))
    monkeypatch.setattr("video_mcp.tools.seedance.carrier_mod.extract_audio", MagicMock(return_value="/tmp/gen.mp3"))
    piapi = AsyncMock()
    piapi.create_task.return_value = make_task_result()
    piapi.wait_for_task.return_value = make_task_result(status="completed", video="https://x/out.mp4")
    eleven = AsyncMock()
    eleven.tts_with_timestamps.return_value = (b"AUDIO", {})
    eleven.transcribe.return_value = {"text": "שלום עולם"}  # both gates pass
    fn = await get_tool(make_deps(piapi, eleven))

    res = await fn(prompt="scene", language="he", text="שלום עולם", voice_id="v1",
                   duration=5, verify_speech=True, wait=True)
    assert eleven.transcribe.await_count == 2  # source + generated
    assert res["generated_audio_qa"]["verdict"] == "pass"
    assert res["generated_audio_qa"]["gate"] == "generated-video gate"


# --------------------------------------------------------------- Non-Hebrew path

async def test_non_hebrew_submits_without_tts_or_carrier(monkeypatch):
    carrier, upload, _ = _patch_chain(monkeypatch)
    piapi = AsyncMock()
    piapi.create_task.return_value = make_task_result(status="completed")
    eleven = AsyncMock()
    fn = await get_tool(make_deps(piapi, eleven))

    res = await fn(prompt="A sunset over the ocean", language="en", duration=5)

    kwargs = piapi.create_task.await_args.kwargs
    assert kwargs["task_type"] == "seedance-2-less-restriction"
    assert kwargs["input"]["mode"] == "text_to_video"
    assert kwargs["input"]["aspect_ratio"] == "16:9"  # non-Hebrew default
    assert res["mode"] == "text_to_video"
    eleven.tts_with_timestamps.assert_not_called()
    carrier.assert_not_called()
    upload.assert_not_called()


async def test_non_hebrew_invalid_duration_toolerror():
    fn = await get_tool(make_deps(AsyncMock(), AsyncMock()))
    with pytest.raises(ToolError):
        await fn(prompt="anything", language="en", duration=7)


# ------------------------------------------- Standalone gate 2 (verify_generated_audio)

async def get_verify_tool(deps: Deps):
    mcp = FastMCP("test")
    register_seedance_tools(mcp, deps)
    tool = await mcp.get_tool("verify_generated_audio")
    return tool.fn


def _patch_gate2(monkeypatch):
    monkeypatch.setattr("video_mcp.tools.seedance._download", AsyncMock(return_value="/tmp/gen.mp4"))
    monkeypatch.setattr(
        "video_mcp.tools.seedance.carrier_mod.extract_audio", MagicMock(return_value="/tmp/gen.mp3")
    )


async def test_verify_generated_audio_by_task_id(monkeypatch):
    _patch_gate2(monkeypatch)
    piapi = AsyncMock()
    piapi.get_task.return_value = make_task_result(status="completed", video="https://x/out.mp4")
    eleven = AsyncMock()
    eleven.transcribe.return_value = {"text": "שלום עולם"}
    fn = await get_verify_tool(make_deps(piapi, eleven))

    res = await fn(text="שלום עולם", task_id="task-9")
    piapi.get_task.assert_awaited_once_with("task-9")
    assert res["verdict"] == "pass"
    assert res["gate"] == "generated-video gate"
    assert res["video_url"] == "https://x/out.mp4"


async def test_verify_generated_audio_by_video_url(monkeypatch):
    _patch_gate2(monkeypatch)
    piapi = AsyncMock()
    eleven = AsyncMock()
    eleven.transcribe.return_value = {"text": "שלום עולם"}
    fn = await get_verify_tool(make_deps(piapi, eleven))

    res = await fn(text="שלום עולם", video_url="https://x/direct.mp4")
    piapi.get_task.assert_not_called()
    assert res["verdict"] == "pass"


async def test_verify_generated_audio_garbled_raises(monkeypatch):
    _patch_gate2(monkeypatch)
    piapi = AsyncMock()
    eleven = AsyncMock()
    eleven.transcribe.return_value = {"text": ""}
    fn = await get_verify_tool(make_deps(piapi, AsyncMock(transcribe=eleven.transcribe)))

    with pytest.raises(ToolError) as ei:
        await fn(text="שלום עולם", video_url="https://x/direct.mp4")
    assert "generated-video gate FAILED" in str(ei.value)


async def test_verify_generated_audio_task_not_finished(monkeypatch):
    _patch_gate2(monkeypatch)
    piapi = AsyncMock()
    piapi.get_task.return_value = make_task_result(status="processing")
    fn = await get_verify_tool(make_deps(piapi, AsyncMock()))

    with pytest.raises(ToolError) as ei:
        await fn(text="שלום", task_id="task-9")
    assert "no video" in str(ei.value).lower()


async def test_verify_generated_audio_requires_source(monkeypatch):
    fn = await get_verify_tool(make_deps(AsyncMock(), AsyncMock()))
    with pytest.raises(ToolError) as ei:
        await fn(text="שלום")
    assert "task_id" in str(ei.value) and "video_url" in str(ei.value)
