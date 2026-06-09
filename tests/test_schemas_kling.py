from __future__ import annotations

import pytest
from pydantic import ValidationError

from video_mcp.schemas.kling import KlingShot, KlingVideoRequest


def test_single_shot_prompt_ok():
    req = KlingVideoRequest(prompt="a cat", duration=5)
    inp = req.to_piapi_input()
    assert inp["prompt"] == "a cat"
    assert inp["duration"] == 5
    assert inp["resolution"] == "720p"  # default; 1080p only when explicitly requested
    assert inp["enable_audio"] is True
    assert "multi_shots" not in inp


def test_shots_ok():
    req = KlingVideoRequest(
        shots=[KlingShot(prompt="a", duration=5), KlingShot(prompt="b", duration=10)]
    )
    inp = req.to_piapi_input()
    assert inp["multi_shots"] == [
        {"prompt": "a", "duration": 5},
        {"prompt": "b", "duration": 10},
    ]
    assert "prompt" not in inp
    assert "duration" not in inp


def test_neither_prompt_nor_shots_fails():
    with pytest.raises(ValidationError):
        KlingVideoRequest()


def test_shots_and_video_mutually_exclusive():
    with pytest.raises(ValidationError):
        KlingVideoRequest(
            shots=[KlingShot(prompt="a")], video="http://x/v.mp4"
        )


def test_shots_too_many_fails():
    with pytest.raises(ValidationError):
        KlingVideoRequest(shots=[KlingShot(prompt="x", duration=1) for _ in range(7)])


def test_shots_sum_over_15_fails():
    with pytest.raises(ValidationError):
        KlingVideoRequest(
            shots=[KlingShot(prompt="a", duration=10), KlingShot(prompt="b", duration=10)]
        )


def test_video_with_too_many_images_fails():
    with pytest.raises(ValidationError):
        KlingVideoRequest(
            prompt="p", video="http://x/v.mp4", images=[f"http://x/{i}.png" for i in range(5)]
        )


def test_video_with_4_images_ok():
    prompt = "scene @video " + " ".join(f"@image_{i}" for i in range(1, 5))
    req = KlingVideoRequest(
        prompt=prompt, video="http://x/v.mp4", images=[f"http://x/{i}.png" for i in range(4)]
    )
    inp = req.to_piapi_input()
    assert inp["video"] == "http://x/v.mp4"
    assert len(inp["images"]) == 4


def test_no_video_with_7_images_ok():
    prompt = "scene " + " ".join(f"@image_{i}" for i in range(1, 8))
    req = KlingVideoRequest(prompt=prompt, images=[f"http://x/{i}.png" for i in range(7)])
    assert len(req.to_piapi_input()["images"]) == 7


def test_no_video_with_8_images_fails():
    prompt = "scene " + " ".join(f"@image_{i}" for i in range(1, 9))
    with pytest.raises(ValidationError):
        KlingVideoRequest(prompt=prompt, images=[f"http://x/{i}.png" for i in range(8)])


def test_keep_original_audio_without_video_fails():
    with pytest.raises(ValidationError):
        KlingVideoRequest(prompt="p", keep_original_audio=True)


def test_keep_original_audio_with_video_ok():
    req = KlingVideoRequest(prompt="scene @video", video="http://x/v.mp4", keep_original_audio=True)
    assert req.to_piapi_input()["keep_original_audio"] is True


def test_unreferenced_image_fails():
    with pytest.raises(ValidationError):
        KlingVideoRequest(prompt="no tags here", images=["http://x/1.png"])


def test_dangling_image_tag_fails():
    with pytest.raises(ValidationError):
        KlingVideoRequest(prompt="@image_1 @image_2", images=["http://x/1.png"])


def test_shot_duration_bounds():
    with pytest.raises(ValidationError):
        KlingShot(prompt="x", duration=0)
    with pytest.raises(ValidationError):
        KlingShot(prompt="x", duration=15)
