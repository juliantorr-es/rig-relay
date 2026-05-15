"""Agent runtime state — explicit, serializable-ish snapshot of mutable session/turn state.

AgentRuntimeState gathers the scattered mutable state that AgentLoop carries
across turns and sessions. It does not replace AgentLoop attributes — it provides
a structured, debug-friendly, boundary-explicit view of runtime state for:

- Durable execution resumption
- Desktop HITL approval binding
- Analytics/observation consumers
- Debug introspection
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    pass


class ReadinessState(StrEnum):
    """Coarse readiness state for AgentLoop initialization."""

    UNKNOWN = "unknown"
    INITIALIZING = "initializing"
    PARTIAL_READY = "partial_ready"
    READY = "ready"
    FAILED = "failed"


class AgentRuntimeState(BaseModel):
    """Mutable runtime/session state snapshot.

    Intentionally excludes:
    - Callbacks (approval, user input) — not serializable
    - Thread handles — ephemeral
    - Backend references — not serializable
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    # ── Session identity ──────────────────────────────────────────
    session_id: str = ""
    parent_session_id: str | None = None
    agent_profile_name: str = ""
    workspace_root: str = ""

    # ── Turn state ────────────────────────────────────────────────
    current_turn_id: str | None = None
    current_context_receipt_id: str | None = None
    is_user_prompt_call: bool = False

    # ── Initialization ────────────────────────────────────────────
    readiness: ReadinessState = ReadinessState.UNKNOWN
    init_duration_ms: int | None = None
    init_error: str | None = None
    deferred_init: bool = False

    # ── Limits ────────────────────────────────────────────────────
    max_turns: int | None = None
    max_price: float | None = None

    # ── Policy ────────────────────────────────────────────────────
    session_rules_count: int = 0
    bypass_tool_permissions: bool = False
    enable_local_observability: bool = False
    enable_streaming: bool = False

    # ── Stats snapshot ────────────────────────────────────────────
    steps: int = 0
    context_tokens: int = 0
    tool_calls_succeeded: int = 0
    tool_calls_failed: int = 0
    tool_calls_agreed: int = 0
    tool_calls_rejected: int = 0
    last_turn_duration: float | None = None
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None

    # ── Model ─────────────────────────────────────────────────────
    active_model: str = ""
    active_provider: str = ""

    # ── Ambient context ───────────────────────────────────────────
    context_packet_available: bool = False
    git_dirty_files_count: int = 0

    # ── Timestamps ────────────────────────────────────────────────
    snapshot_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    # ── Helpers ───────────────────────────────────────────────────

    def to_debug_dict(self) -> dict[str, Any]:
        """Return a JSON-safe debug snapshot.

        Excludes anything that could contain secrets or be
        non-deterministically large.
        """
        return {
            "session_id": self.session_id,
            "agent": self.agent_profile_name,
            "readiness": self.readiness.value,
            "turn_id": self.current_turn_id,
            "steps": self.steps,
            "context_tokens": self.context_tokens,
            "tools": {
                "succeeded": self.tool_calls_succeeded,
                "failed": self.tool_calls_failed,
                "agreed": self.tool_calls_agreed,
                "rejected": self.tool_calls_rejected,
            },
            "model": self.active_model,
            "provider": self.active_provider,
            "streaming": self.enable_streaming,
            "observability": self.enable_local_observability,
            "init_duration_ms": self.init_duration_ms,
            "snapshot_at": self.snapshot_at,
        }

    def readiness_summary(self) -> str:
        """Human-readable readiness summary."""
        if self.init_error:
            return f"failed: {self.init_error[:120]}"
        if self.readiness == ReadinessState.READY:
            base = "ready"
            if self.init_duration_ms is not None:
                base += f" ({self.init_duration_ms}ms)"
            return base
        if self.readiness == ReadinessState.INITIALIZING:
            return "initializing (deferred init in progress)"
        if self.readiness == ReadinessState.PARTIAL_READY:
            return "partial_ready (some subsystems unavailable)"
        return self.readiness.value

    def current_session_summary(self) -> dict[str, Any]:
        """Compact session summary for projection/panel consumers."""
        return {
            "session_id": self.session_id,
            "agent": self.agent_profile_name,
            "readiness": self.readiness_summary(),
            "turn": self.current_turn_id,
            "steps": self.steps,
            "model": self.active_model,
            "context_tokens": self.context_tokens,
            "tools_succeeded": self.tool_calls_succeeded,
            "tools_failed": self.tool_calls_failed,
            "snapshot_at": self.snapshot_at,
        }
