"""Desktop event sink — stable event stream interface for desktop HITL.

Provides protocol, no-op, and in-memory implementations.
Events are content-light: hashes, status enums, no raw payloads.

Future: JSONL sink, analytics compiler integration.
"""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from typing import Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

DESKTOP_EVENT_VERSION = "rig.desktop_event.v1"


class DesktopEventRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = DESKTOP_EVENT_VERSION
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event_name: str = ""
    occurred_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    intent_kind: str = ""
    run_id: str | None = None
    scan_id: str | None = None
    panel_sha256: str | None = None
    mission_candidate_sha256: str | None = None
    ok: bool = False
    status: str = ""
    error_code: str | None = None
    execution_enabled: bool = False
    payload_sha256: str | None = None
    event_sha256: str = ""

    def compute_sha256(self) -> str:
        payload = self.model_dump_json(
            exclude={"event_sha256", "occurred_at", "created_at"}, exclude_none=True
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@runtime_checkable
class DesktopEventSink(Protocol):
    """Protocol for desktop event sinks."""

    def emit(self, event: DesktopEventRecord) -> None: ...


class NoOpDesktopEventSink:
    """No-op sink — discards all events."""

    def emit(self, event: DesktopEventRecord) -> None:
        pass


class InMemoryDesktopEventSink:
    """In-memory sink — stores events for tests."""

    def __init__(self) -> None:
        self._events: list[DesktopEventRecord] = []

    def emit(self, event: DesktopEventRecord) -> None:
        event.event_sha256 = event.compute_sha256()
        self._events.append(event)

    @property
    def events(self) -> list[DesktopEventRecord]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()


__all__ = [
    "DESKTOP_EVENT_VERSION",
    "DesktopEventRecord",
    "DesktopEventSink",
    "InMemoryDesktopEventSink",
    "NoOpDesktopEventSink",
]
