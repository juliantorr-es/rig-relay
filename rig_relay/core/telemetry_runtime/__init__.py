"""TelemetryRuntime — session and tool call telemetry emission.

Phase 6 extraction target. Delegates telemetry emission to
TelemetryEvidenceService (Step 2 refactor). Thin wrapper around
the service; retained for AgentLoop delegation surface.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from rig_relay.core.agent_loop import AgentLoop
    from rig_relay.core.telemetry_evidence_service import TelemetryEvidenceService


class TelemetryRuntime:
    """Thin wrapper delegating telemetry to TelemetryEvidenceService."""

    __slots__ = ("_loop", "_evidence")

    def __init__(self, loop: AgentLoop, *, evidence: Any = None) -> None:
        self._loop = loop
        self._evidence: TelemetryEvidenceService | None = evidence

    def emit_new_session(self) -> None:
        if self._evidence is not None:
            self._evidence.emit_new_session()

    def emit_ready(self, init_duration_ms: int) -> None:
        if self._evidence is not None:
            self._evidence.emit_ready(init_duration_ms)

    def emit_session_closed(self) -> None:
        if self._evidence is not None:
            self._evidence.emit_session_closed()

    def emit_context_observation(
        self,
        tool_call: Any,
        status: str,
        args_dict: dict[str, Any],
        blocked_by_policy: bool = False,
    ) -> None:
        if self._evidence is not None:
            self._evidence.emit_context_observation(
                tool_call, status, args_dict, blocked_by_policy
            )
