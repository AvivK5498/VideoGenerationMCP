"""Record PiAPI private-asset IDs on an influencer's Obsidian page.

Maintains a managed '## Private Assets (PiAPI)' section with one structured line
per asset: `- <name> | asset://<id> | <type> | expires <expires_at>`. Re-recording
the same name replaces its line (idempotent), so the page always holds the latest
asset:// id to paste into generate_seedance_video.
"""

from __future__ import annotations

import os

_HEADING = "## Private Assets (PiAPI)"


def _entry(name: str, asset_id: str, asset_type: str, expires_at: str) -> str:
    return f"- {name} | asset://{asset_id} | {asset_type} | expires {expires_at}"


def record_asset(page_path: str, *, name: str, asset_id: str, asset_type: str, expires_at: str = "") -> str:
    """Insert/replace the asset line for `name` under the managed heading. Returns the line."""
    if not os.path.isfile(page_path):
        raise FileNotFoundError(f"influencer page not found: {page_path}")
    line = _entry(name, asset_id, asset_type, expires_at)
    with open(page_path, encoding="utf-8") as fh:
        lines = fh.read().splitlines()

    if _HEADING not in lines:
        lines += ["", _HEADING, line]
    else:
        start = lines.index(_HEADING)
        # section runs until the next heading or EOF
        end = len(lines)
        for i in range(start + 1, len(lines)):
            if lines[i].startswith("## "):
                end = i
                break
        section = lines[start + 1:end]
        prefix = f"- {name} | "
        replaced = False
        for i, ln in enumerate(section):
            if ln.startswith(prefix):
                section[i] = line
                replaced = True
                break
        if not replaced:
            # keep entries adjacent; append after the last existing entry/blank
            insert_at = len(section)
            while insert_at > 0 and not section[insert_at - 1].strip():
                insert_at -= 1
            section.insert(insert_at, line)
        lines = lines[:start + 1] + section + lines[end:]

    with open(page_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    return line
