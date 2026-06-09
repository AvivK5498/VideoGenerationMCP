"""Tests for video_mcp.qa transcript bands: 100% pass / 85-99% warning / <85% fail."""

from __future__ import annotations

from video_mcp.qa import compare_transcripts


def test_exact_match_passes():
    v = compare_transcripts("שלום עולם קנו עכשיו", "שלום עולם קנו עכשיו")
    assert v.verdict == "pass"
    assert v.overlap == 1.0
    assert v.is_garbled is False


def test_minor_drift_warns():
    # 6 expected tokens, 5 present -> 0.83? tune to land in 85-99 band: 7 tokens, 6 hit = 0.857
    expected = "shalom olam knu achshav et hamutzar shelanu"   # 7 tokens
    actual = "shalom olam knu achshav et hamutzar acheret"      # last token differs -> 6/7
    v = compare_transcripts(expected, actual, expect_hebrew=False)
    assert v.verdict == "warning"
    assert 0.85 <= v.overlap < 1.0


def test_heavy_drift_fails():
    v = compare_transcripts("shalom olam knu achshav", "totally different words here", expect_hebrew=False)
    assert v.verdict == "fail"
    assert v.is_garbled is True


def test_empty_transcript_fails():
    v = compare_transcripts("שלום עולם", "")
    assert v.verdict == "fail"
    assert "empty" in v.notes


def test_wrong_language_fails():
    # Hebrew expected but transcript is all Latin -> wrong language.
    v = compare_transcripts("שלום עולם", "hello world", expect_hebrew=True)
    assert v.verdict == "fail"
    assert "wrong language" in v.notes


def test_niqqud_and_punctuation_ignored():
    v = compare_transcripts("שָׁלוֹם, עוֹלָם!", "שלום עולם")
    assert v.verdict == "pass"
