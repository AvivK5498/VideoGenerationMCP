"""Shared schema types and PiAPI envelope parsing.

PiAPI uses a single task envelope for every model. Two response shapes appear:
- create-task: {"code": 200, "data": {...}, "message": "success"}
- get-task:    {"timestamp": ..., "data": {...}}   (no top-level code/message)

`TaskResult.from_piapi` accepts either and normalizes them.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ServiceMode = Literal["public", "private"]

# PiAPI documents these canonical statuses; example JSON uses lowercase.
# Compare case-insensitively. Terminal = completed | failed.
TERMINAL_STATUSES = {"completed", "failed"}


class WebhookConfig(BaseModel):
    endpoint: str
    secret: str = ""


class TaskResult(BaseModel):
    """Normalized view of a PiAPI task (create or get)."""

    task_id: str
    status: str = ""
    model: str = ""
    task_type: str = ""
    output: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    raw: dict[str, Any] = Field(default_factory=dict, repr=False)

    @property
    def normalized_status(self) -> str:
        return (self.status or "").lower()

    @property
    def is_terminal(self) -> bool:
        return self.normalized_status in TERMINAL_STATUSES

    @property
    def is_failed(self) -> bool:
        return self.normalized_status == "failed"

    @property
    def video_url(self) -> str | None:
        """Result video URL for Kling/Seedance outputs, if present."""
        if not self.output:
            return None
        v = self.output.get("video")
        return v or None

    @property
    def error_message(self) -> str | None:
        if not self.error:
            return None
        msg = self.error.get("message") or self.error.get("raw_message")
        # error.code == 0 means "no error" in PiAPI's envelope.
        if self.error.get("code") in (0, "0", None) and not msg:
            return None
        return msg or None

    @classmethod
    def from_piapi(cls, body: dict[str, Any]) -> "TaskResult":
        """Parse either PiAPI envelope shape into a TaskResult.

        Does NOT raise on provider error fields — callers inspect status/error.
        Raises ValueError only if `data.task_id` is absent (malformed body).
        """
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict) or "task_id" not in data:
            raise ValueError(f"PiAPI response missing data.task_id: {body!r}")
        return cls(
            task_id=str(data["task_id"]),
            status=str(data.get("status", "")),
            model=str(data.get("model", "")),
            task_type=str(data.get("task_type", "")),
            output=data.get("output") if isinstance(data.get("output"), dict) else None,
            error=data.get("error") if isinstance(data.get("error"), dict) else None,
            raw=data,
        )
