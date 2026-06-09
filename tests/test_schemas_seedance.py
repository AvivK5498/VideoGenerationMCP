from __future__ import annotations

import pytest
from pydantic import ValidationError

from video_mcp.schemas.seedance import SeedanceVideoRequest


@pytest.mark.parametrize("dur", [5, 10, 15])
def test_allowed_durations(dur):
    req = SeedanceVideoRequest(prompt="p", duration=dur)
    assert req.duration == dur


@pytest.mark.parametrize("dur", [4, 7, 20])
def test_rejected_durations(dur):
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(prompt="p", duration=dur)


def test_prompt_too_long_fails():
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(prompt="x" * 4001)


def test_fast_1080p_fails():
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(prompt="p", task_type="seedance-2-fast", resolution="1080p")


def test_fast_720p_ok():
    req = SeedanceVideoRequest(prompt="p", task_type="seedance-2-fast", resolution="720p")
    assert req.task_type == "seedance-2-fast"


def test_mode_inference_text_to_video():
    req = SeedanceVideoRequest(prompt="p")
    assert req.mode == "text_to_video"


def test_mode_inference_first_last():
    req = SeedanceVideoRequest(prompt="p", image_urls=["http://x/1.png", "http://x/2.png"])
    assert req.mode == "first_last_frames"


def test_mode_inference_omni():
    req = SeedanceVideoRequest(
        prompt="scene with @image1 and @video1",
        image_urls=["http://x/1.png"],
        video_urls=["http://x/v.mp4"],
    )
    assert req.mode == "omni_reference"


def test_text_to_video_rejects_refs():
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(prompt="p", mode="text_to_video", image_urls=["http://x/1.png"])


def test_first_last_frames_one_or_two_images():
    SeedanceVideoRequest(prompt="p", mode="first_last_frames", image_urls=["http://x/1.png"])
    SeedanceVideoRequest(
        prompt="p", mode="first_last_frames", image_urls=["http://x/1.png", "http://x/2.png"]
    )


def test_first_last_frames_three_images_fails():
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(
            prompt="p",
            mode="first_last_frames",
            image_urls=["http://x/1.png", "http://x/2.png", "http://x/3.png"],
        )


def test_first_last_frames_rejects_audio():
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(
            prompt="p",
            mode="first_last_frames",
            image_urls=["http://x/1.png"],
            audio_urls=["http://x/a.mp3"],
        )


def test_omni_audio_requires_image_or_video():
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(
            prompt="p", mode="omni_reference", audio_urls=["http://x/a.mp3"]
        )


def test_omni_audio_with_video_ok():
    req = SeedanceVideoRequest(
        prompt="scene @video1 @audio1",
        mode="omni_reference",
        video_urls=["http://x/v.mp4"],
        audio_urls=["http://x/a.mp3"],
    )
    inp = req.to_piapi_input()
    assert inp["audio_urls"] == ["http://x/a.mp3"]
    assert inp["video_urls"] == ["http://x/v.mp4"]


def test_too_many_images_fails():
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(prompt="p", image_urls=[f"http://x/{i}.png" for i in range(13)])


def test_to_piapi_input_shape():
    req = SeedanceVideoRequest(prompt="p", duration=10, resolution="720p")
    inp = req.to_piapi_input()
    assert inp["mode"] == "text_to_video"
    assert inp["duration"] == 10
    assert inp["prompt"] == "p"
    assert "image_urls" not in inp


# --- less-restriction + private assets ---

def test_asset_ref_requires_less_restriction():
    # asset:// on a strict task type is rejected (mirrors PiAPI 422).
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(prompt="scene @image1", task_type="seedance-2",
                             mode="omni_reference", image_urls=["asset://a1"])


def test_asset_ref_ok_on_less_restriction():
    req = SeedanceVideoRequest(prompt="scene @image1", task_type="seedance-2-less-restriction",
                               mode="omni_reference", image_urls=["asset://a1"])
    assert req.to_piapi_input()["image_urls"] == ["asset://a1"]


def test_auto_upload_requires_less_restriction():
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(prompt="a scene", task_type="seedance-2", auto_upload_assets=True)


def test_auto_upload_retention_bounds():
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(prompt="a scene", task_type="seedance-2-less-restriction",
                             auto_upload_assets=True, asset_retention_hours=2)
    req = SeedanceVideoRequest(prompt="a scene", task_type="seedance-2-less-restriction",
                               auto_upload_assets=True, asset_retention_hours=8)
    inp = req.to_piapi_input()
    assert inp["auto_upload_assets"] is True and inp["asset_retention_hours"] == 8


def test_fast_less_restriction_rejects_1080p():
    with pytest.raises(ValidationError):
        SeedanceVideoRequest(prompt="a scene", task_type="seedance-2-fast-less-restriction",
                             resolution="1080p")


def test_default_task_type_is_less_restriction():
    assert SeedanceVideoRequest(prompt="a scene").task_type == "seedance-2-less-restriction"
