"""ToolExecutionContext — explicit context for the tool execution boundary.

Carries all state ToolExecutor, CouncilGate, and ToolRuntimeAdapterBuilder
need to function without reaching into AgentLoop private internals.

Design: session-scoped fields (session_id, workspace_root, config,
tool_manager, trace_runtime, rewind_manager, callback ports) are set
at construction and are stable for the life of the context. Per-turn
fields (turn_id, user_message_id, bypass_permissions, current_turn)
are updated via update_turn() before each tool batch.

Note: a future slice should split this into a frozen ToolExecutionContext
(session fields) and an immutable ToolExecutionTurnContext (per-batch fields)
to eliminate the update_turn mutation. The current mutable design is a
pragmatic compromise to avoid refactoring every call site in one pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from pathlib import Path


class ToolManagerPort(Protocol):
    """Structural interface for tool lookup — the only methods ToolExecutor needs."""

    def get(self, name: str) -> Any: ...
    @property
    def available_tools(self) -> dict[str, Any]: ...


class TraceRuntimePort(Protocol):
    """Structural interface for trace span management."""

    def tool_span(self, *, tool_name: str, call_id: str, arguments: str) -> Any: ...


class ResultSinkPort(Protocol):
    """Structural interface for recording tool results."""

    def record(self, result: Any) -> None: ...


class RewindManagerPort(Protocol):
    """Structural interface for pre-mutation file snapshots."""

    def add_snapshot(self, snapshot: Any) -> None: ...


class GovernanceTelemetryPort(Protocol):
    """Structural interface for council gate telemetry emission.
    Matches the keyword-only signature of TelemetryClient.emit_governance_gate_decision.
    """

    def emit_governance_gate_decision(
        self,
        *,
        gate: str,
        decision: str,
        reason: str = "",
        tool_name: str = "",
        mutation_intent: bool = False,
        policy_version: str = "v1",
        severity: str = "info",
        trace_id: str = "",
        span_id: str = "",
        receipt_id: str = "",
        session_id: str | None = None,
        turn_id: str = "",
        operator_action_required: bool = False,
        renewal: bool = False,
    ) -> None: ...


@dataclass(frozen=False)
class ToolExecutionContext:
    """Explicit context for tool execution — no reach-through to AgentLoop.

    Injected into ToolExecutor, CouncilGate, and ToolRuntimeAdapterBuilder
    at construction time. Session fields are stable. Per-turn fields are
    updated via update_turn() before each tool batch.

    A future slice should split session/turn into separate immutable contexts.
    """

    # ── Per-session state (stable across turns) ────────────────
    session_id: str = ""
    workspace_root: Path | None = None
    config: Any | None = None
    tool_manager: Any | None = None
    trace_runtime: Any | None = None
    rewind_manager: Any | None = None

    # ── Callback ports (stable across turns) ──────────────────
    approval_callback: Any | None = None
    result_sink: Any | None = None
    handle_tool_response: Callable[..., None] | None = None
    add_message: Callable[[Any], None] | None = None
    telemetry_client: GovernanceTelemetryPort | None = None

    # ── Per-turn state (updated via update_turn before each batch) ──
    turn_id: str = ""
    user_message_id: str = ""
    bypass_permissions: bool = False
    current_turn: Any = None

    stats: Any = None

    def update_turn(
        self,
        *,
        turn_id: str = "",
        user_message_id: str = "",
        bypass_permissions: bool = False,
        current_turn: Any = None,
    ) -> None:
        """Update per-turn fields before a tool batch.

        Called from AgentLoop._execute_pending_tool_batch() before
        delegating tool execution to ToolExecutor.execute_batch().
        """
        if turn_id:
            self.turn_id = turn_id
        if user_message_id:
            self.user_message_id = user_message_id
        self.bypass_permissions = bypass_permissions
        if current_turn is not None:
            self.current_turn = current_turn
