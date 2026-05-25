"""Tool execution contexts — explicit, immutable boundary for tool execution.

Design: ToolSessionContext carries all session-scoped state and is
constructed once per AgentLoop session. ToolTurnContext carries
per-batch turn state and is constructed fresh before each tool batch.
Both are frozen (immutable) — no update_turn mutation.

Protocols define structural interfaces for dependency injection.
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


@dataclass(frozen=True)
class ToolSessionContext:
    """Immutable per-session context for tool execution.

    Constructed once per AgentLoop session. All fields are stable
    for the life of the session and never change.
    """

    session_id: str = ""
    workspace_root: Path | None = None
    config: Any = None
    tool_manager: Any = None
    trace_runtime: Any = None
    rewind_manager: Any = None

    approval_callback: Any = None
    result_sink: Any = None
    handle_tool_response: Callable[..., None] | None = None
    handle_failed_tool_response: Callable[..., Any] | None = None
    add_message: Callable[[Any], None] | None = None
    telemetry_client: GovernanceTelemetryPort | None = None

    stats: Any = None


@dataclass(frozen=True)
class ToolTurnContext:
    """Immutable per-turn context for a single tool execution batch.

    Constructed fresh before each tool batch. Carries only the
    per-turn fields that were previously mutated via update_turn().
    """

    turn_id: str = ""
    user_message_id: str = ""
    bypass_permissions: bool = False
    current_turn: Any = None
    correlation_id: str = ""
    causation_id: str = ""
    mission_authority: Any = None
