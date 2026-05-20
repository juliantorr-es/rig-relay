"""Bridge runtime lifecycle state — per-connection runtime state machine.

Separate from ``DesktopBridgeStateMachine`` (server startup probe ladder).
This tracks per-connection runtime lifecycle: transport → backend readiness → idle/active → shutdown.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum, auto
import time
from typing import Any


class BridgeRuntimeState(StrEnum):
    STARTING = auto()
    READY = auto()
    IDLE = auto()
    ACTIVE = auto()
    DEGRADED = auto()
    DISCONNECTING = auto()
    DISCONNECTED = auto()
    FAILED = auto()


_CONNECTED_STATES: frozenset[str] = frozenset({
    BridgeRuntimeState.STARTING,
    BridgeRuntimeState.READY,
    BridgeRuntimeState.IDLE,
    BridgeRuntimeState.ACTIVE,
    BridgeRuntimeState.DEGRADED,
})


@dataclass
class BridgeRuntimeStateTracker:
    """Per-connection bridge runtime state tracker.

    Tracks:
    - Runtime lifecycle state (starting → ready → idle/active → disconnecting → disconnected)
    - Idle projection sequencing
    - Backend session identity
    - Active work count
    - Last known sequence
    - Degradation reasons
    """

    handshake_id: str
    backend_session_id: str
    bridge_schema_version: str = "rig.relay.bridge_runtime.v1"
    _state: BridgeRuntimeState = BridgeRuntimeState.STARTING
    _previous_state: BridgeRuntimeState | None = None
    _transition_count: int = 0
    _idle_sequence: int = 0
    _active_work_count: int = 0
    _last_work_sequence: int = 0
    _capabilities: list[str] = field(default_factory=list)
    _disabled_reasons: dict[str, str] = field(default_factory=dict)
    _degradation_reason: str | None = None
    _started_at: float = field(default_factory=time.monotonic)
    _last_transition_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )

    @property
    def state(self) -> BridgeRuntimeState:
        return self._state

    @property
    def is_connected(self) -> bool:
        return self._state.value in _CONNECTED_STATES

    @property
    def idle_sequence(self) -> int:
        return self._idle_sequence

    @property
    def active_work_count(self) -> int:
        return self._active_work_count

    @property
    def last_work_sequence(self) -> int:
        return self._last_work_sequence

    @property
    def capabilities(self) -> list[str]:
        return list(self._capabilities)

    @property
    def disabled_reasons(self) -> dict[str, str]:
        return dict(self._disabled_reasons)

    def next_idle_sequence(self) -> int:
        self._idle_sequence += 1
        return self._idle_sequence

    def record_work_started(self) -> None:
        self._active_work_count += 1
        self._last_work_sequence = self._idle_sequence
        if self._state == BridgeRuntimeState.IDLE:
            self._transition_to(BridgeRuntimeState.ACTIVE)

    def record_work_finished(self) -> None:
        if self._active_work_count > 0:
            self._active_work_count -= 1
        if self._active_work_count == 0 and self._state == BridgeRuntimeState.ACTIVE:
            self._transition_to(BridgeRuntimeState.IDLE)

    def set_ready(self) -> None:
        self._transition_to(BridgeRuntimeState.READY)
        self._transition_to(BridgeRuntimeState.IDLE)

    def set_degraded(self, reason: str) -> None:
        self._degradation_reason = reason
        self._transition_to(BridgeRuntimeState.DEGRADED)

    def set_disconnecting(self) -> None:
        self._transition_to(BridgeRuntimeState.DISCONNECTING)

    def set_disconnected(self) -> None:
        self._transition_to(BridgeRuntimeState.DISCONNECTED)

    def set_failed(self, reason: str) -> None:
        self._degradation_reason = reason
        self._transition_to(BridgeRuntimeState.FAILED)

    def set_active(self) -> None:
        if self._state in {BridgeRuntimeState.READY, BridgeRuntimeState.IDLE}:
            self.record_work_started()

    def set_idle(self) -> None:
        self._active_work_count = min(self._active_work_count, 0)
        self._transition_to(BridgeRuntimeState.IDLE)

    def set_capabilities(self, capabilities: list[str]) -> None:
        self._capabilities = list(capabilities)

    def set_disabled_reasons(self, reasons: dict[str, str]) -> None:
        self._disabled_reasons = dict(reasons)

    def _transition_to(self, target: BridgeRuntimeState) -> None:
        if self._state is target:
            return
        self._previous_state = self._state
        self._state = target
        self._transition_count += 1
        self._last_transition_at = datetime.now(UTC).isoformat()

    def build_bridge_status(self) -> dict[str, Any]:
        """Build a content-light bridge status payload.

        Includes: backend session identity, runtime state, idle sequence,
        active work count, capabilities, disabled reasons, timestamps.
        No raw content, secrets, or prompts.
        """
        return {
            "schema_version": self.bridge_schema_version,
            "handshake_id": self.handshake_id,
            "backend_session_id": self.backend_session_id,
            "bridge_runtime_state": self._state.value,
            "previous_state": self._previous_state.value
            if self._previous_state
            else None,
            "idle_sequence": self._idle_sequence,
            "transition_count": self._transition_count,
            "active_work_count": self._active_work_count,
            "last_work_sequence": self._last_work_sequence,
            "capabilities": list(self._capabilities),
            "disabled_reasons": dict(self._disabled_reasons),
            "degradation_reason": self._degradation_reason,
            "started_at": datetime.fromtimestamp(self._started_at, tz=UTC).isoformat(),
            "last_transition_at": self._last_transition_at,
            "generated_at": datetime.now(UTC).isoformat(),
        }

    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "previous_state": self._previous_state.value
            if self._previous_state
            else None,
            "transition_count": self._transition_count,
            "idle_sequence": self._idle_sequence,
            "active_work_count": self._active_work_count,
            "handshake_id": self.handshake_id,
            "backend_session_id": self.backend_session_id,
            "uptime_sec": time.monotonic() - self._started_at,
        }


__all__ = ["BridgeRuntimeState", "BridgeRuntimeStateTracker"]
