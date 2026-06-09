"""Tests for recording asset IDs on an Obsidian influencer page."""

from __future__ import annotations

import os
import tempfile

import pytest

from video_mcp.utils.obsidian import record_asset


def _page(body: str = "# Hila\n\nSome notes.\n") -> str:
    fd, p = tempfile.mkstemp(suffix=".md")
    with open(fd, "w", encoding="utf-8") as fh:
        fh.write(body)
    return p


def test_creates_section_and_entry():
    p = _page()
    line = record_asset(p, name="hila-identity", asset_id="asset-1", asset_type="Image", expires_at="2026-06-16")
    text = open(p, encoding="utf-8").read()
    assert "## Private Assets (PiAPI)" in text
    assert "asset://asset-1" in text
    assert line in text


def test_replaces_same_name_idempotent():
    p = _page()
    record_asset(p, name="hila-identity", asset_id="asset-1", asset_type="Image")
    record_asset(p, name="hila-identity", asset_id="asset-2", asset_type="Image")  # re-record
    text = open(p, encoding="utf-8").read()
    assert "asset://asset-2" in text
    assert "asset://asset-1" not in text          # old line replaced
    assert text.count("- hila-identity | ") == 1  # exactly one entry for the name


def test_appends_distinct_names():
    p = _page()
    record_asset(p, name="hila-identity", asset_id="asset-1", asset_type="Image")
    record_asset(p, name="hila-body", asset_id="asset-2", asset_type="Image")
    text = open(p, encoding="utf-8").read()
    assert "asset://asset-1" in text and "asset://asset-2" in text


def test_missing_page_raises():
    with pytest.raises(FileNotFoundError):
        record_asset("/no/such/page.md", name="x", asset_id="a", asset_type="Image")
