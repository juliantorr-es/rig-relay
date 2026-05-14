"""Progress events for tool execution lifecycle.

Provides typed, validated event models with controlled vocabularies
for phases, statuses, and levels. Adapted from Rig's ProgressEvent pattern.

Replaces ad-hoc kind strings in session event recording.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

ALLOWED_PROGRESS_PHASES: set[str] = {
    "turn.started",
    "turn.completed",
    "turn.failed",
    "turn.cancelled",
    "user_message.accepted",
    "assistant_message.started",
    "assistant_message.delta",
    "assistant_message.completed",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "tool.refused",
    "status.info",
    "status.blocked",
    "error",
}

ALLOWED_PROGRESS_STATUSES: set[str] = {
    "running",
    "completed",
    "failed",
    "cancelled",
    "refused",
    "blocked",
}

ALLOWED_PROGRESS_LEVELS: set[str] = {"info", "warning", "error"}


@dataclass(frozen=True, slots=True)
class TurnProgressEvent:
    event_id: str
    sequence: int
    phase: str
    status: str
    level: str = "info"
    message: str | None = None
    tool_name: str | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
    duration_ms: float | None = None
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def __post_init__(self) -> None:
        assert self.phase in ALLOWED_PROGRESS_PHASES, f"Invalid phase: {self.phase}"
        assert self.status in ALLOWED_PROGRESS_STATUSES, (
            f"Invalid status: {self.status}"
        )
        assert self.level in ALLOWED_PROGRESS_LEVELS, f"Invalid level: {self.level}"

    @property
    def is_terminal(self) -> bool:
        return self.phase in {"turn.completed", "turn.failed", "turn.cancelled"}


class ProgressEventFactory:
    _counter: int = 0

    @classmethod
    def reset(cls) -> None:
        cls._counter = 0

    @classmethod
    def _next_id(cls) -> str:
        cls._counter += 1
        return f"evt-{cls._counter}"

    @classmethod
    def user_message(cls, text: str) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="user_message.accepted",
            status="completed",
            message=text,
        )

    @classmethod
    def assistant_started(cls) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="assistant_message.started",
            status="running",
        )

    @classmethod
    def assistant_completed(cls, text: str) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="assistant_message.completed",
            status="completed",
            message=text,
        )

    @classmethod
    def tool_started(cls, tool_name: str) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="tool.started",
            status="running",
            tool_name=tool_name,
        )

    @classmethod
    def tool_completed(cls, tool_name: str) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="tool.completed",
            status="completed",
            tool_name=tool_name,
        )

    @classmethod
    def tool_failed(cls, tool_name: str, error_kind: str) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="tool.failed",
            status="failed",
            level="error",
            tool_name=tool_name,
            error_kind=error_kind,
        )

    @classmethod
    def tool_refused(cls, tool_name: str, reason: str) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="tool.refused",
            status="refused",
            level="warning",
            tool_name=tool_name,
            refusal_reason=reason,
        )

    @classmethod
    def turn_completed(cls) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="turn.completed",
            status="completed",
        )

    @classmethod
    def turn_failed(cls, error_kind: str) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="turn.failed",
            status="failed",
            level="error",
            error_kind=error_kind,
        )

    @classmethod
    def turn_cancelled(cls) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="turn.cancelled",
            status="cancelled",
            level="warning",
        )

    @classmethod
    def status_blocked(cls) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="status.blocked",
            status="blocked",
            level="warning",
        )

    @classmethod
    def error(cls, error_kind: str) -> TurnProgressEvent:
        return TurnProgressEvent(
            event_id=cls._next_id(),
            sequence=cls._counter,
            phase="error",
            status="failed",
            level="error",
            error_kind=error_kind,
        )


__all__ = [
    "ALLOWED_PROGRESS_LEVELS",
    "ALLOWED_PROGRESS_PHASES",
    "ALLOWED_PROGRESS_STATUSES",
    "ProgressEventFactory",
    "TurnProgressEvent",
]
