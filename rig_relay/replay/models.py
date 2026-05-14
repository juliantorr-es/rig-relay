"""Replay models for session-centric deterministic reconstruction.

Adapted from Rig's replay.py architectural pattern (ReplayEvent → ReplayFrame
→ ReplayResult with integrity findings), but adapted for Rig Relay's
session-centric domain.

Rig Relay replay reconstructs tool invocation sequences from observability JSONL
rather than Rig's workspace state machine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any


class ReplayEventKind(StrEnum):
    RECEIPT = auto()
    TOOL_INVOCATION = auto()
    GOVERNANCE_DECISION = auto()
    SESSION_EVENT = auto()
    PROJECTION_UPDATE = auto()
    DIRTY_SNAPSHOT = auto()
    UNKNOWN = auto()


class ReplayIntegritySeverity(StrEnum):
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CRITICAL = auto()


class ReplayConflictType(StrEnum):
    MISSING_EVENT = auto()
    SEQUENCE_GAP = auto()
    DUPLICATE_SEQUENCE = auto()
    OUT_OF_ORDER = auto()
    STALE_RECEIPT = auto()
    ORPHANED_EVENT = auto()
    NON_DETERMINISTIC_ORDERING = auto()


class ReplayState(StrEnum):
    PENDING = auto()
    PROCESSING = auto()
    COMPLETE = auto()
    FAILED = auto()
    PARTIAL = auto()


# ── Data models ─────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    """A single replayable event from session observability.

    Immutable, ordered by sequence index. Carries the original event
    name, session context, and a content-light payload summary.
    """

    event_id: str
    sequence: int
    event_kind: ReplayEventKind
    event_name: str
    session_id: str
    created_at: str
    tool_name: str | None = None
    status: str | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
    duration_ms: float | None = None
    payload_hash: str | None = None

    def __lt__(self, other: ReplayEvent) -> bool:
        return (self.sequence, self.created_at, self.event_id) < (
            other.sequence, other.created_at, other.event_id
        )


@dataclass(frozen=True, slots=True)
class ReplayIntegrityFinding:
    finding_id: str
    severity: ReplayIntegritySeverity
    message: str
    conflict_type: ReplayConflictType | None = None
    event_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ReplayFrame:
    """A group of replay events forming a logical step.

    Frames are ordered by sequence. Each frame has a hash chain for
    determinism verification.
    """

    frame_index: int
    events: list[ReplayEvent] = field(default_factory=list)
    frame_hash: str | None = None
    previous_frame_hash: str | None = None
    is_terminal: bool = False

    @property
    def first_sequence(self) -> int | None:
        if not self.events:
            return None
        return min(e.sequence for e in self.events)

    @property
    def last_sequence(self) -> int | None:
        if not self.events:
            return None
        return max(e.sequence for e in self.events)


@dataclass
class ReplayCursor:
    """Navigation state for replay frames.

    Enables time-travel within a replay result.
    """

    current_frame_index: int = 0
    total_frames: int = 0
    can_go_back: bool = False
    can_go_forward: bool = False
    current_frame_hash: str | None = None


@dataclass
class ReplayResult:
    """Complete output of a replay session.

    Contains the frame chain, integrity findings, navigation cursor,
    and a content-light summary.
    """

    replay_id: str
    session_id: str
    state: ReplayState = ReplayState.PENDING
    frames: list[ReplayFrame] = field(default_factory=list)
    findings: list[ReplayIntegrityFinding] = field(default_factory=list)
    cursor: ReplayCursor = field(default_factory=ReplayCursor)
    total_events: int = 0
    summary: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self._update_cursor()

    def _update_cursor(self) -> None:
        self.cursor.total_frames = len(self.frames)
        self.cursor.can_go_back = self.cursor.current_frame_index > 0
        self.cursor.can_go_forward = (
            self.cursor.current_frame_index < len(self.frames) - 1
        )
        if self.frames:
            current = self.frames[self.cursor.current_frame_index]
            self.cursor.current_frame_hash = current.frame_hash

    @property
    def current_frame(self) -> ReplayFrame | None:
        if not self.frames:
            return None
        if self.cursor.current_frame_index >= len(self.frames):
            return None
        return self.frames[self.cursor.current_frame_index]

    @property
    def all_passed(self) -> bool:
        return not any(
            f.severity in {ReplayIntegritySeverity.ERROR, ReplayIntegritySeverity.CRITICAL}
            for f in self.findings
        )


__all__ = [
    "ReplayConflictType",
    "ReplayCursor",
    "ReplayEvent",
    "ReplayEventKind",
    "ReplayFrame",
    "ReplayIntegrityFinding",
    "ReplayIntegritySeverity",
    "ReplayResult",
    "ReplayState",
]
