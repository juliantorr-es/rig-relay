"""ProgressEvent model for desktop intent progress streaming.

Content-light progress events streamed over the existing WebSocket transport.
Telemetry, not authority. No second transport.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict

# Reusable event_type constants
EVENT_OPERATION_STARTED = "operation.started"
EVENT_OPERATION_PROGRESS = "operation.progress"
EVENT_OPERATION_WARNING = "operation.warning"
EVENT_OPERATION_COMPLETED = "operation.completed"
EVENT_OPERATION_FAILED = "operation.failed"
EVENT_OPERATION_REFUSED = "operation.refused"
EVENT_PROJECTION_REFRESHED = "projection.refreshed"
EVENT_VALIDATION_STEP_STARTED = "validation.step.started"
EVENT_VALIDATION_STEP_COMPLETED = "validation.step.completed"


class ProgressEvent(BaseModel):
    """Content-light progress event for WebSocket streaming.

    All fields are content-light: no raw stdout/stderr, prompts, model outputs,
    source code, diffs, secrets, or raw receipt bodies.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.progress_event.v1"
    event_id: str = ""
    operation_id: str = ""
    intent_id: str = ""
    source: str = ""
    event_type: str = ""
    phase: str = ""
    status: str = "running"
    sequence: int = 0
    created_at: str = ""
    message: str = ""
    progress_current: int | None = None
    progress_total: int | None = None
    percent: float | None = None
    result_kind: str = ""
    output_refs: list[str] = []
    receipt_candidate: dict[str, Any] | None = None
    projection_refresh_recommended: bool = False
    warnings: list[str] = []
    content_light_guarantee: bool = True


def build_progress_event(
    operation_id: str,
    event_type: str,
    phase: str,
    status: str = "running",
    *,
    source: str = "intents",
    intent_id: str = "",
    message: str = "",
    **extra: Any,
) -> ProgressEvent:
    """Build a ProgressEvent with auto-generated event_id and timestamp."""
    kwargs: dict[str, Any] = {
        "event_id": f"pe_{uuid.uuid4().hex[:12]}",
        "operation_id": operation_id,
        "intent_id": intent_id,
        "source": source,
        "event_type": event_type,
        "phase": phase,
        "status": status,
        "sequence": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "message": message,
        "content_light_guarantee": True,
    }
    kwargs.update(extra)
    return ProgressEvent(**kwargs)


def progress_event_sha256(event: ProgressEvent) -> str:
    """Compute SHA256 of a ProgressEvent's content-light fields."""
    raw = event.model_dump_json(exclude_none=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


class ProgressEventBuffer:
    """Bounded buffer for ProgressEvents.

    Keeps the most recent N events for replay on client connect.
    Events are stored content-light (model dump, no raw data).
    """

    def __init__(self, max_events: int = 50) -> None:
        self._events: list[dict[str, Any]] = []
        self._max_events = max_events

    def push(self, event: ProgressEvent) -> None:
        dumped = event.model_dump(mode="json", exclude_none=True)
        self._events.append(dumped)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events :]

    def push_dict(self, dumped: dict[str, Any]) -> None:
        """Push a pre-dumped event dict (eg from broadcast_progress_event)."""
        self._events.append(dumped)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events :]

    def recent(self, count: int = 20) -> list[dict[str, Any]]:
        return self._events[-count:]

    def clear(self) -> None:
        self._events.clear()

    def __len__(self) -> int:
        return len(self._events)
