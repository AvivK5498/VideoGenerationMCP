"""Tests for @-tag reference validation."""

from __future__ import annotations

import pytest

from video_mcp.utils.references import extract_tags, validate_references


def test_extract_kling_tags():
    tags = extract_tags("@image_1 and @image_2 with @video", style="kling")
    assert tags["image"] == {1, 2}
    assert tags["video"] == {1}


def test_extract_kling_bare_video_not_matched_by_indexed():
    # @video1 is NOT a Kling tag (Kling uses bare @video).
    assert extract_tags("@video1", style="kling")["video"] == set()


def test_extract_seedance_tags():
    tags = extract_tags("@image1 @video1 @audio1", style="seedance")
    assert tags == {"image": {1}, "video": {1}, "audio": {1}}


def test_tags_case_insensitive():
    # @Image1 (skill convention, capitalized) must validate the same as @image1.
    assert extract_tags("@Image1 @Video1", style="seedance")["image"] == {1}
    validate_references("@Image1 @Video1", n_images=1, n_videos=1, style="seedance")


def test_kling_ok():
    validate_references("@image_1 @video", n_images=1, n_videos=1, style="kling")


def test_dangling_tag_fails():
    with pytest.raises(ValueError, match="only 1"):
        validate_references("@image1 @image2", n_images=1, style="seedance")


def test_unreferenced_fails():
    with pytest.raises(ValueError, match="never referenced"):
        validate_references("no tags", n_images=2, style="seedance")


def test_index_zero_invalid():
    with pytest.raises(ValueError):
        validate_references("@image0", n_images=1, style="seedance")


def test_flf_exempt_from_must_reference():
    # No tags but 2 images supplied — allowed because require_referenced=False.
    validate_references("a calm dolly shot", n_images=2, style="seedance", require_referenced=False)
    # ...but a dangling tag is still rejected even when exempt.
    with pytest.raises(ValueError):
        validate_references("@image3", n_images=2, style="seedance", require_referenced=False)
