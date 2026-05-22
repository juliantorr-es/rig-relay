"""Conversation runtime models — request, result, status, phase events.

ConversationRuntime is the turn state machine that owns phase order,
loop policy, and failure classification. AgentLoop delegates turn
execution to it via callbacks.

Architecture boundary: must NOT import desktop, ralph, scripts,
duckdb, or analytics.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.core.types import BaseEvent

if TYPE_CHECKING:
    pass


class ConversationRuntimeStatus(StrEnum):
    """Overall status of a conversation runtime execution."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ConversationRuntimePhaseEvent(BaseModel):
    """Emitted when the runtime advances a phase.

    Lightweight — does not carry the full turn state.
    Consumers: desktop projection, analytics, Ralph.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_id: str
    session_id: str
    phase: str
    previous_phase: str | None = None
    phase_index: int = 0


class PhaseTraceAttributes(BaseModel):
    """JSON-safe trace attributes recorded at each phase transition.

    These are intentionally sparse — no raw message content, no tool
    outputs, no model internals. The schema is the contract between
    ConversationRuntime and downstream trace consumers.

    Nullable fields use None when data is not yet available.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_session_id: str
    conversation_turn_id: str | None = None
    conversation_phase: str
    conversation_previous_phase: str | None = None
    conversation_status: str | None = None
    conversation_reason: str | None = None
    conversation_tool_call_count: int | None = None
    conversation_duration_ms: float | None = None
    trace_id: str | None = None


class PhaseTraceHook(Protocol):
    """Callback interface for phase tracing consumers.

    Implementations receive structured trace attributes at each
    phase transition and at result completion. Errors in callbacks
    must not propagate to the caller — ConversationRuntime catches
    and logs them.
    """

    def on_phase_event(self, attrs: PhaseTraceAttributes) -> None:
        """Called at each phase transition with trace attributes."""
        ...

    def on_result(self, attrs: PhaseTraceAttributes) -> None:
        """Called after _finish() with final outcome attributes."""
        ...


class ConversationRuntimeRequest(BaseModel):
    """Input to ConversationRuntime.execute_turn().

    Only data and port references — no business logic.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    session_id: str
    user_message_text: str
    user_message_id: str
    max_turns: int | None = None
    max_price: float | None = None
    enable_streaming: bool = False
    context_envelope_id: str | None = None


class ConversationRuntimeResult(BaseModel):
    """Output from ConversationRuntime.execute_turn().

    JSON-safe summary of what happened in the turn.
    """

    model_config = ConfigDict(extra="forbid", frozen=False)

    session_id: str
    turn_id: str = ""
    status: ConversationRuntimeStatus = ConversationRuntimeStatus.NOT_STARTED
    final_outcome: str = ""
    outcome_reason: str = ""

    # Phase tracking
    phases_entered: list[str] = Field(default_factory=list)
    total_turns: int = 0

    # Tool summary
    tool_calls_attempted: int = 0
    tool_calls_succeeded: int = 0
    tool_calls_failed: int = 0
    tool_calls_skipped: int = 0
    tool_total_duration_ms: float = 0.0

    # Context
    context_section_count: int = 0
    context_envelope_id: str | None = None

    # LLM
    llm_calls: int = 0
    assistant_content_length: int = 0

    # Timing
    duration_ms: float | None = None

    # Errors
    error_message: str | None = None
    last_phase: str | None = None


class ConversationRuntimeCallbacks(Protocol):
    """Port interface for ConversationRuntime → AgentLoop adapter.

    Each callback provides access to AgentLoop capabilities.
    The callbacks are intentionally coarse — they group related operations
    to avoid a proliferation of tiny callbacks.
    """

    # ── Turn lifecycle ──────────────────────────────────────────

    def setup_turn(self, request: ConversationRuntimeRequest) -> None:
        """Create turn state, append user message, set IDs."""
        ...

    def persist_turn_state(self) -> None:
        """Save messages and state at turn end."""
        ...

    def get_turn_id(self) -> str:
        """Return current turn ID."""
        ...

    def get_turn(self) -> Any:
        """Return current turn state object."""
        ...

    def mark_turn_outcome(self, outcome: Any, reason: str) -> None:
        """Set final turn outcome."""
        ...

    def emit_phase_event(self, event: ConversationRuntimePhaseEvent) -> None:
        """Record a phase transition."""
        ...

    # ── Middleware ───────────────────────────────────────────────

    async def middleware_before_turn(
        self, ctx: dict[str, str]
    ) -> tuple[Any, list[BaseEvent]]:
        """Run middleware pipeline. Returns (result, events_to_yield)."""
        ...

    def reset_hooks(self) -> None:
        """Reset hook retry count."""
        ...

    # ── Context ──────────────────────────────────────────────────

    async def build_context_envelope(
        self, request: ConversationRuntimeRequest
    ) -> Any | None:
        """Build context envelope. Returns receipt or None."""
        ...

    def set_context_envelope(self, receipt: Any) -> None:
        """Store context envelope receipt."""
        ...

    # ── LLM ──────────────────────────────────────────────────────

    def stream_llm_turn(self) -> AsyncGenerator[BaseEvent, None]:
        """Yield LLM response events (AssistantEvent, ReasoningEvent, ToolCallEvent)."""
        ...

    def is_user_cancellation_event(self, event: BaseEvent) -> bool:
        """Check if an event indicates user cancellation."""
        ...

    # ── Hooks ────────────────────────────────────────────────────

    def stream_hooks_post_turn(self) -> AsyncGenerator[BaseEvent, None]:
        """Yield post-turn hook events. HookUserMessage → retry signal."""
        ...

    def is_hook_user_message(self, event: BaseEvent) -> bool:
        """Check if event is a HookUserMessage (triggers retry)."""
        ...

    def inject_hook_message(self, hook_message: Any) -> None:
        """Inject a hook user message into the conversation for retry."""
        ...

    # ── Loop control ─────────────────────────────────────────────

    def last_message_has_no_tool_calls(self) -> bool:
        """[Deprecated] Check if last message indicates loop should break.

        Superseded by get_turn_batch_result(). Kept for compatibility
        during migration. Prefer TurnBatchResult.
        """
        ...

    def get_turn_batch_result(self) -> TurnBatchResult:
        """Return typed pending-tool state after model turn completes.

        Replaces last_message_has_no_tool_calls() with an explicit
        typed result that ConversationRuntime can use for decision dispatch.
        """
        ...

    # ── Tool execution ─────────────────────────────────────────

    def execute_tool_batch(self) -> AsyncGenerator[BaseEvent, None]:
        """Execute pending tool calls. Yields tool events."""
        ...

    # ── Budget ──────────────────────────────────────────────────

    def check_max_turns(self) -> int | None:
        """Return max_turns limit or None."""
        ...

    # ── Event emission ─────────────────────────────────────────

    def yield_user_message_event(self) -> AsyncGenerator[BaseEvent, None]:
        """Yield UserMessageEvent for the current user message."""
        ...


# ── Decision model (Phase 2A) ────────────────────────────────────────


class ConversationLoopDecisionKind(StrEnum):
    """Kinds of loop-continuation decisions."""

    continue_turn = "continue_turn"
    stop_completed = "stop_completed"
    stop_middleware = "stop_middleware"
    stop_cancelled = "stop_cancelled"
    run_tools = "run_tools"
    retry_hooks = "retry_hooks"
    fail_error = "fail_error"
    fail_budget_exceeded = "fail_budget_exceeded"


class ConversationLoopDecision(BaseModel):
    """Result of a loop-continuation decision.

    Returned by ConversationRuntime.decide_*() methods.
    AgentLoop reads the decision and executes the corresponding action.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ConversationLoopDecisionKind
    reason: str = ""
    should_break: bool = False
    should_run_tools: bool = False
    should_retry_hooks: bool = False
    attributes: dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def continue_turn(reason: str = "") -> ConversationLoopDecision:
        return ConversationLoopDecision(
            kind=ConversationLoopDecisionKind.continue_turn, reason=reason
        )

    @staticmethod
    def stop_completed(reason: str = "") -> ConversationLoopDecision:
        return ConversationLoopDecision(
            kind=ConversationLoopDecisionKind.stop_completed,
            reason=reason,
            should_break=True,
        )

    @staticmethod
    def stop_middleware(reason: str = "") -> ConversationLoopDecision:
        return ConversationLoopDecision(
            kind=ConversationLoopDecisionKind.stop_middleware,
            reason=reason,
            should_break=True,
        )

    @staticmethod
    def stop_cancelled(reason: str = "") -> ConversationLoopDecision:
        return ConversationLoopDecision(
            kind=ConversationLoopDecisionKind.stop_cancelled,
            reason=reason,
            should_break=True,
        )

    @staticmethod
    def run_tools(reason: str = "") -> ConversationLoopDecision:
        return ConversationLoopDecision(
            kind=ConversationLoopDecisionKind.run_tools,
            reason=reason,
            should_run_tools=True,
        )

    @staticmethod
    def retry_hooks(reason: str = "") -> ConversationLoopDecision:
        return ConversationLoopDecision(
            kind=ConversationLoopDecisionKind.retry_hooks,
            reason=reason,
            should_retry_hooks=True,
        )

    @staticmethod
    def fail_error(
        reason: str = "", attributes: dict[str, Any] | None = None
    ) -> ConversationLoopDecision:
        return ConversationLoopDecision(
            kind=ConversationLoopDecisionKind.fail_error,
            reason=reason,
            should_break=True,
            attributes=attributes or {},
        )

    @staticmethod
    def fail_budget_exceeded(reason: str = "") -> ConversationLoopDecision:
        return ConversationLoopDecision(
            kind=ConversationLoopDecisionKind.fail_budget_exceeded,
            reason=reason,
            should_break=True,
        )


# ── Turn result models (Phase 0: typed turn-state contract) ─────────


class TurnBatchResult(BaseModel):
    """Result of a tool execution batch within a turn.

    Replaces the implicit adapter query for pending tool state.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    pending_batch: list[object] | None = Field(default=None)
    """Resolved tool calls waiting to execute. None means no tools pending."""

    failed_calls: list[object] = Field(default_factory=list)
    """Tool calls that failed resolution."""

    assistant_is_final: bool = False
    """True when the assistant produced a message with no tool call intent."""

    @property
    def has_tool_work(self) -> bool:
        """True when there are pending tool calls to execute."""
        return self.pending_batch is not None and len(self.pending_batch) > 0
