"""Conversation turn runtime — explicit one-turn phase state machine.

ConversationTurnRuntime owns the phase structure and turn-level metadata
for a single agent turn. AgentLoop instantiates it and drives phase
transitions. The turn runtime is intentionally lightweight — it does not
execute LLM calls or tool invocations; it tracks phase and outcome.

Future: desktop HITL can observe phase transitions. Ralph can consume
turn outcomes. Analytics can emit turn-phase events.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    pass


class TurnPhase(StrEnum):
    """Ordered phases for a single agent turn."""

    CREATED = "created"
    CONTEXT_BUILDING = "context_building"
    CONTEXT_READY = "context_ready"
    MODEL_CALLING = "model_calling"
    ASSISTANT_PARSED = "assistant_parsed"
    TOOL_CALLS_RUNNING = "tool_calls_running"
    TOOL_CALLS_COMPLETED = "tool_calls_completed"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"


class TurnOutcome(StrEnum):
    """Coarse outcome of a turn."""

    SUCCESS = "success"
    USER_CANCELLED = "user_cancelled"
    MIDDLEWARE_STOP = "middleware_stop"
    TOOL_FAILURE = "tool_failure"
    LLM_ERROR = "llm_error"
    UNKNOWN = "unknown"


class ConversationTurnRuntime(BaseModel):
    """One-turn orchestration state.

    Owns phase, outcome, and turn-level metadata. AgentLoop
    instantiates this at the start of each turn and advances
    phase as the turn progresses. LLM/tool calls are delegated
    back to AgentLoop methods — this class is a state tracker,
    not an executor.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    # ── Identity ──────────────────────────────────────────────────
    turn_id: str = Field(default_factory=lambda: uuid4().hex[:12])
    session_id: str = ""

    # ── Phase ─────────────────────────────────────────────────────
    phase: TurnPhase = TurnPhase.CREATED
    phase_history: list[tuple[str, str]] = Field(
        default_factory=list
    )  # [(phase, iso_timestamp), ...]

    # ── User message ──────────────────────────────────────────────
    user_message_id: str | None = None
    user_message_text: str = ""
    context_envelope_id: str | None = None
    context_section_count: int = 0

    # ── Assistant response ────────────────────────────────────────
    assistant_message_id: str | None = None
    assistant_content_length: int = 0
    reasoning_content_length: int = 0

    # ── Tool execution ────────────────────────────────────────────
    tool_call_count: int = 0
    tool_success_count: int = 0
    tool_failure_count: int = 0
    tool_skip_count: int = 0
    tool_total_duration_ms: float = 0.0

    # ── Outcome ───────────────────────────────────────────────────
    outcome: TurnOutcome = TurnOutcome.UNKNOWN
    outcome_reason: str = ""
    outcome_at: str | None = None

    # ── Timestamps ────────────────────────────────────────────────
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    # ── Transitions ───────────────────────────────────────────────

    def advance(self, next_phase: TurnPhase) -> None:
        """Record a phase transition."""
        now = datetime.now(UTC).isoformat()
        self.phase_history.append((self.phase.value, now))
        self.phase = next_phase

    def mark_outcome(self, outcome: TurnOutcome, reason: str = "") -> None:
        """Set final outcome and timestamp."""
        self.outcome = outcome
        self.outcome_reason = reason
        self.outcome_at = datetime.now(UTC).isoformat()

    # ── Snapshots ─────────────────────────────────────────────────

    def to_debug_dict(self) -> dict[str, Any]:
        """Return a JSON-safe debug snapshot."""
        return {
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "phase": self.phase.value,
            "phase_count": len(self.phase_history),
            "user_message_id": self.user_message_id,
            "context_sections": self.context_section_count,
            "assistant_content_len": self.assistant_content_length,
            "tools": {
                "total": self.tool_call_count,
                "succeeded": self.tool_success_count,
                "failed": self.tool_failure_count,
                "skipped": self.tool_skip_count,
                "duration_ms": self.tool_total_duration_ms,
            },
            "outcome": self.outcome.value,
            "outcome_reason": self.outcome_reason[:200] if self.outcome_reason else "",
            "created_at": self.created_at,
            "outcome_at": self.outcome_at,
        }

    def summary_line(self) -> str:
        """One-line summary for logging."""
        return (
            f"turn={self.turn_id} phase={self.phase.value} "
            f"tools={self.tool_success_count}/{self.tool_call_count} "
            f"outcome={self.outcome.value}"
        )
