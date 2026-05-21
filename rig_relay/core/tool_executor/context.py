"""ToolExecutionContext — explicit context for the tool execution boundary.

Carries all state ToolExecutor, CouncilGate, and ToolRuntimeAdapterBuilder
need to function without reaching into AgentLoop private internals.

Design: immutable after construction. Callers set fields at build time from
AgentLoop's current state snapshot for each turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=False)
class ToolExecutionContext:
    """Explicit context for tool execution — no reach-through to AgentLoop.

    Injected into ToolExecutor, CouncilGate, and ToolRuntimeAdapterBuilder
    at construction time. Fields that change per-turn (e.g. turn_id) are
    updated via update_turn() before each tool batch.
    """

    # Per-session state (stable)
    session_id: str = ""
    workspace_root: Path | None = None
    config: Any | None = None
    tool_manager: Any | None = None
    trace_runtime: Any | None = None
    rewind_manager: Any | None = None

    # Callback ports (stable)
    approval_callback: Any | None = None
    result_sink: Any | None = None
    handle_tool_response: Callable[..., None] | None = None
    add_message: Callable[[Any], None] | None = None
    emit_telemetry: Callable[..., None] | None = None
    capture_model_observation: Callable[..., None] | None = None

    # Per-turn state (updated per batch)
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
        """Update per-turn fields before a tool batch."""
        if turn_id:
            self.turn_id = turn_id
        if user_message_id:
            self.user_message_id = user_message_id
        self.bypass_permissions = bypass_permissions
        if current_turn is not None:
            self.current_turn = current_turn
