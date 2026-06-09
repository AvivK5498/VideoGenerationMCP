"""Async PiAPI client for Kling/Seedance task submission and polling."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from video_mcp.config import Settings
from video_mcp.errors import PiapiError
from video_mcp.logging_config import get_logger, redact
from video_mcp.schemas.common import TaskResult

logger = get_logger(__name__)


def _parse_error(body: Any) -> str | None:
    """Extract a human-readable message from a PiAPI error envelope, if any."""
    if not isinstance(body, dict):
        return None
    msg = body.get("message")
    data = body.get("data")
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict) and err.get("message"):
            msg = err.get("message") or msg
    return msg


class PiapiClient:
    """Thin async wrapper over the PiAPI unified task endpoint."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._client = client

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self._settings.require_piapi(),
            "Content-Type": "application/json",
        }

    async def _post(self, url: str, json: dict[str, Any]) -> httpx.Response:
        if self._client is not None:
            return await self._client.post(url, json=json, headers=self._headers())
        async with httpx.AsyncClient(timeout=self._settings.http_timeout_s) as client:
            return await client.post(url, json=json, headers=self._headers())

    async def _get(self, url: str) -> httpx.Response:
        if self._client is not None:
            return await self._client.get(url, headers=self._headers())
        async with httpx.AsyncClient(timeout=self._settings.http_timeout_s) as client:
            return await client.get(url, headers=self._headers())

    async def create_task(
        self,
        *,
        model: str,
        task_type: str,
        input: dict[str, Any],
        config: dict[str, Any] | None = None,
    ) -> TaskResult:
        url = f"{self._settings.piapi_base}/task"
        body: dict[str, Any] = {"model": model, "task_type": task_type, "input": input}
        if config:
            body["config"] = config
        logger.info("piapi create_task: %s", redact(body))

        # Retry transient gateway failures (5xx / connect-read timeouts) on submit.
        attempts = 4
        for attempt in range(1, attempts + 1):
            try:
                resp = await self._post(url, body)
            except httpx.HTTPError as exc:
                if attempt == attempts:
                    raise PiapiError(f"PiAPI submit failed after {attempts} attempts: {exc}", code="network") from exc
                logger.warning("create_task transient %s (attempt %d/%d), retrying", exc, attempt, attempts)
                await asyncio.sleep(min(2 ** attempt, 15))
                continue
            if resp.status_code >= 500 and attempt < attempts:
                logger.warning("create_task HTTP %s (attempt %d/%d), retrying", resp.status_code, attempt, attempts)
                await asyncio.sleep(min(2 ** attempt, 15))
                continue
            break

        try:
            data = resp.json()
        except Exception:
            data = None

        code = data.get("code") if isinstance(data, dict) else None
        if resp.status_code >= 400 or (code is not None and code != 200):
            message = _parse_error(data) or f"PiAPI request failed (HTTP {resp.status_code})"
            raise PiapiError(message, code=code if code is not None else resp.status_code, raw=data)

        if not isinstance(data, dict):
            raise PiapiError("PiAPI returned a non-JSON body", code=resp.status_code, raw=resp.text)
        return TaskResult.from_piapi(data)

    async def get_task(self, task_id: str) -> TaskResult:
        url = f"{self._settings.piapi_base}/task/{task_id}"
        resp = await self._get(url)
        data = resp.json()
        return TaskResult.from_piapi(data)

    async def wait_for_task(
        self,
        task_id: str,
        *,
        interval: float | None = None,
        timeout: float | None = None,
    ) -> TaskResult:
        interval = interval if interval is not None else self._settings.poll_interval_s
        timeout = timeout if timeout is not None else self._settings.poll_timeout_s

        loop = asyncio.get_event_loop()
        start = loop.time()
        last: TaskResult | None = None
        while True:
            try:
                last = await self.get_task(task_id)
                if last.is_terminal:
                    return last
            except (ValueError, httpx.HTTPError) as exc:
                # Transient parse / network blip — keep polling until timeout.
                logger.debug("piapi wait_for_task transient: %s", exc)

            if loop.time() - start >= timeout:
                raise PiapiError(
                    f"Timed out waiting for task {task_id} after {timeout}s",
                    code="timeout",
                    raw=last.raw if last else None,
                )
            await asyncio.sleep(interval)

    # ------------------------------------------------------------------ Assets

    async def _post_json_retry(self, url: str, body: dict[str, Any]) -> httpx.Response:
        """POST with transient-5xx/network retry (same policy as create_task)."""
        attempts, resp = 4, None
        for attempt in range(1, attempts + 1):
            try:
                resp = await self._post(url, body)
            except httpx.HTTPError as exc:
                if attempt == attempts:
                    raise PiapiError(f"request failed after {attempts} attempts: {exc}", code="network") from exc
                await asyncio.sleep(min(2 ** attempt, 15))
                continue
            if resp.status_code >= 500 and attempt < attempts:
                await asyncio.sleep(min(2 ** attempt, 15))
                continue
            return resp
        return resp

    async def create_asset(self, *, url: str, asset_type: str | None = None, name: str | None = None) -> dict[str, Any]:
        """Register a private asset from a public URL. Returns {asset_id, status, expires_at, ...}."""
        body: dict[str, Any] = {"url": url}
        if asset_type:
            body["asset_type"] = asset_type
        if name:
            body["name"] = name
        logger.info("piapi create_asset: %s", redact(body))
        resp = await self._post_json_retry(f"{self._settings.piapi_base}/asset/upload", body)
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise PiapiError(_parse_error(data) or f"asset upload failed (HTTP {resp.status_code})",
                             code=resp.status_code, raw=data)
        return data

    async def get_asset(self, asset_id: str) -> dict[str, Any]:
        resp = await self._get(f"{self._settings.piapi_base}/asset/{asset_id}")
        data = resp.json() if resp.content else {}
        if resp.status_code >= 400:
            raise PiapiError(_parse_error(data) or f"get asset failed (HTTP {resp.status_code})",
                             code=resp.status_code, raw=data)
        return data

    async def wait_for_asset(self, asset_id: str, *, interval: float = 4.0, timeout: float = 240.0) -> dict[str, Any]:
        """Poll an asset until status Active (returns it) or Failed/timeout (raises)."""
        loop = asyncio.get_event_loop()
        start = loop.time()
        while True:
            data = await self.get_asset(asset_id)
            status = str(data.get("status", "")).lower()
            if status == "active":
                return data
            if status == "failed":
                err = (data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else None
                raise PiapiError(f"asset {asset_id} failed: {err or 'unknown'}", code="asset_failed", raw=data)
            if loop.time() - start >= timeout:
                raise PiapiError(f"asset {asset_id} not Active after {timeout}s", code="timeout", raw=data)
            await asyncio.sleep(interval)

    async def list_assets(self, *, status: str | None = None, page: int = 1, size: int = 20) -> dict[str, Any]:
        url = f"{self._settings.piapi_base}/asset/list?page={page}&size={size}"
        if status:
            url += f"&status={status}"
        resp = await self._get(url)
        if resp.status_code >= 400:
            raise PiapiError(f"list assets failed (HTTP {resp.status_code})", code=resp.status_code, raw=resp.text)
        return resp.json()

    async def delete_asset(self, asset_id: str) -> bool:
        url = f"{self._settings.piapi_base}/asset/{asset_id}"
        if self._client is not None:
            resp = await self._client.request("DELETE", url, headers=self._headers())
        else:
            async with httpx.AsyncClient(timeout=self._settings.http_timeout_s) as client:
                resp = await client.request("DELETE", url, headers=self._headers())
        if resp.status_code not in (200, 204):
            raise PiapiError(f"delete asset failed (HTTP {resp.status_code})", code=resp.status_code, raw=resp.text)
        return True
