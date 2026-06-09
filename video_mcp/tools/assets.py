"""FastMCP tools for the PiAPI Private Asset Library.

Upload a persona/product/scene reference once, get a stable `asset://<id>` that
persists for days and is reusable across tasks (no re-fetch). Asset references are
accepted only on the -less-restriction Seedance task types.
"""

from __future__ import annotations

from typing import Any

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from video_mcp.errors import VideoMCPError
from video_mcp.logging_config import get_logger
from video_mcp.tools import Deps
from video_mcp.utils import uploader
from video_mcp.utils.obsidian import record_asset

logger = get_logger(__name__)


def register_asset_tools(mcp: FastMCP, deps: Deps) -> dict:
    @mcp.tool
    async def upload_asset(
        image: str,
        name: str | None = None,
        asset_type: str = "Image",
        wait_active: bool = True,
        influencer_page: str | None = None,
    ) -> dict[str, Any]:
        """Register a private asset from a local path or public URL; return its asset://id.

        Local paths are first uploaded to a temporary public host for ingestion (the
        asset persists on PiAPI ~days afterward, independent of that URL). If
        `influencer_page` (path to an Obsidian .md) is given, the asset id is recorded
        there under a managed section for reuse.
        """
        try:
            if image.startswith(("http://", "https://")):
                src = image
            else:
                src = await uploader.upload_file(image, upload_url=deps.settings.tmpfiles_upload_url)
            created = await deps.piapi.create_asset(url=src, asset_type=asset_type, name=name)
            asset_id = created["asset_id"]
            status = created.get("status")
            if wait_active:
                active = await deps.piapi.wait_for_asset(asset_id)
                status = active.get("status")
                created = {**created, **active}
        except VideoMCPError as exc:
            raise ToolError(str(exc)) from exc

        out = {
            "asset_id": asset_id,
            "asset_ref": f"asset://{asset_id}",
            "status": status,
            "expires_at": created.get("expires_at"),
            "name": created.get("name") or name,
            "asset_type": asset_type,
        }
        if influencer_page:
            try:
                out["recorded"] = record_asset(
                    influencer_page, name=out["name"] or asset_id, asset_id=asset_id,
                    asset_type=asset_type, expires_at=out.get("expires_at") or "",
                )
            except OSError as exc:
                raise ToolError(f"could not record asset on {influencer_page}: {exc}") from exc
        logger.info("upload_asset -> %s (%s)", asset_id, status)
        return out

    @mcp.tool
    async def list_assets(status: str | None = None, page: int = 1, size: int = 20) -> dict[str, Any]:
        """List private assets (optionally filter by status: active,processing,failed)."""
        try:
            return await deps.piapi.list_assets(status=status, page=page, size=size)
        except VideoMCPError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool
    async def get_asset(asset_id: str) -> dict[str, Any]:
        """Get a single asset's current state (refreshes its TTL)."""
        try:
            return await deps.piapi.get_asset(asset_id)
        except VideoMCPError as exc:
            raise ToolError(str(exc)) from exc

    @mcp.tool
    async def delete_asset(asset_id: str) -> dict[str, Any]:
        """Delete a private asset."""
        try:
            await deps.piapi.delete_asset(asset_id)
        except VideoMCPError as exc:
            raise ToolError(str(exc)) from exc
        return {"deleted": asset_id}

    return {"upload_asset": upload_asset, "list_assets": list_assets,
            "get_asset": get_asset, "delete_asset": delete_asset}
