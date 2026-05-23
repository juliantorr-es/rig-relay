"""Event-driven RuntimeSupervisor supervision state machine.

Converts the implicit while-True polling loop in RuntimeSupervisor.execute
into explicit validated state transitions. Handles subprocess lifecycle
(IDLE -> SPAWNING -> RUNNING/HEARTBEATING/STALL_DETECTED/RECOVERING ->
TERMINATING -> KILLED/COMPLETED/FAILED) with heartbeat timeout, stall
detection, and recovery transitions driven by explicit events.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any

# ── States ────────────────────────────────────────────────────────────


class SupervisorState(StrEnum):
    IDLE = auto()
    SPAWNING = auto()
    RUNNING = auto()
    HEARTBEATING = auto()
    STALL_DETECTED = auto()
    RECOVERING = auto()
    TERMINATING = auto()
    KILLED = auto()
    COMPLETED = auto()
    FAILED = auto()


# ── Events ────────────────────────────────────────────────────────────


class SupervisorEvent(StrEnum):
    SPAWN_STARTED = auto()
    SPAWN_SUCCEEDED = auto()
    SPAWN_FAILED = auto()
    PROCESS_EXITED = auto()
    OUTPUT_CHUNK = auto()
    HEARTBEAT_TIMER = auto()
    STALL_TIMER = auto()
    STALL_RECOVERED = auto()
    HARD_STALL = auto()
    TIMEOUT = auto()
    BUDGET_EXCEEDED = auto()
    KILL_SENT = auto()
    CANCELLED = auto()
    ERROR = auto()


# ── Transition helpers ────────────────────────────────────────────────

_TERMINAL_STATES: frozenset[SupervisorState] = frozenset({
    SupervisorState.KILLED,
    SupervisorState.COMPLETED,
    SupervisorState.FAILED,
})

_PROCESS_ALIVE_STATES: frozenset[SupervisorState] = frozenset({
    SupervisorState.RUNNING,
    SupervisorState.HEARTBEATING,
    SupervisorState.STALL_DETECTED,
    SupervisorState.RECOVERING,
})

_TRANSITIONS: dict[SupervisorState, dict[SupervisorEvent, SupervisorState]] = {
    SupervisorState.IDLE: {SupervisorEvent.SPAWN_STARTED: SupervisorState.SPAWNING},
    SupervisorState.SPAWNING: {
        SupervisorEvent.SPAWN_SUCCEEDED: SupervisorState.RUNNING,
        SupervisorEvent.SPAWN_FAILED: SupervisorState.FAILED,
        SupervisorEvent.ERROR: SupervisorState.FAILED,
    },
    SupervisorState.RUNNING: {
        SupervisorEvent.HEARTBEAT_TIMER: SupervisorState.HEARTBEATING,
        SupervisorEvent.STALL_TIMER: SupervisorState.STALL_DETECTED,
        SupervisorEvent.TIMEOUT: SupervisorState.TERMINATING,
        SupervisorEvent.BUDGET_EXCEEDED: SupervisorState.TERMINATING,
        SupervisorEvent.CANCELLED: SupervisorState.TERMINATING,
    },
    SupervisorState.HEARTBEATING: {
        SupervisorEvent.HEARTBEAT_TIMER: SupervisorState.HEARTBEATING,
        SupervisorEvent.OUTPUT_CHUNK: SupervisorState.RUNNING,
        SupervisorEvent.STALL_TIMER: SupervisorState.STALL_DETECTED,
        SupervisorEvent.TIMEOUT: SupervisorState.TERMINATING,
        SupervisorEvent.BUDGET_EXCEEDED: SupervisorState.TERMINATING,
        SupervisorEvent.CANCELLED: SupervisorState.TERMINATING,
    },
    SupervisorState.STALL_DETECTED: {
        SupervisorEvent.HEARTBEAT_TIMER: SupervisorState.STALL_DETECTED,
        SupervisorEvent.OUTPUT_CHUNK: SupervisorState.RECOVERING,
        SupervisorEvent.HARD_STALL: SupervisorState.TERMINATING,
        SupervisorEvent.TIMEOUT: SupervisorState.TERMINATING,
        SupervisorEvent.BUDGET_EXCEEDED: SupervisorState.TERMINATING,
        SupervisorEvent.CANCELLED: SupervisorState.TERMINATING,
    },
    SupervisorState.RECOVERING: {
        SupervisorEvent.HEARTBEAT_TIMER: SupervisorState.HEARTBEATING,
        SupervisorEvent.STALL_TIMER: SupervisorState.STALL_DETECTED,
        SupervisorEvent.TIMEOUT: SupervisorState.TERMINATING,
        SupervisorEvent.BUDGET_EXCEEDED: SupervisorState.TERMINATING,
        SupervisorEvent.CANCELLED: SupervisorState.TERMINATING,
    },
    SupervisorState.TERMINATING: {SupervisorEvent.KILL_SENT: SupervisorState.KILLED},
    SupervisorState.KILLED: {},
    SupervisorState.COMPLETED: {},
    SupervisorState.FAILED: {},
}


# ── Dataclass ─────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class SupervisorTransition:
    from_state: SupervisorState
    to_state: SupervisorState
    event: SupervisorEvent
    reason: str | None
    attributes: dict[str, Any]
    timestamp: str


# ── Exception ─────────────────────────────────────────────────────────


class InvalidSupervisorTransition(Exception):
    pass


# ── State Machine ─────────────────────────────────────────────────────


class RuntimeSupervisorStateMachine:
    def __init__(self, *, on_transition: Callable[..., Any] | None = None) -> None:
        self._state = SupervisorState.IDLE
        self._previous_state: SupervisorState | None = None
        self._last_event: SupervisorEvent | None = None
        self._transition_count = 0
        self._exit_code: int | None = None
        self._timed_out = False
        self._killed = False
        self._stdout_bytes = 0
        self._stderr_bytes = 0
        self._on_transition = on_transition

    @property
    def current_state(self) -> SupervisorState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in _TERMINAL_STATES

    def transition(
        self,
        event: SupervisorEvent,
        *,
        reason: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> SupervisorTransition:
        attrs = dict(attributes or {})
        if event == SupervisorEvent.TIMEOUT:
            self._timed_out = True
        if event == SupervisorEvent.KILL_SENT:
            self._killed = True
        if "exit_code" in attrs and attrs["exit_code"] is not None:
            self._exit_code = int(attrs["exit_code"])
        if "stdout_bytes" in attrs:
            self._stdout_bytes = int(attrs["stdout_bytes"])
        if "stderr_bytes" in attrs:
            self._stderr_bytes = int(attrs["stderr_bytes"])

        target = self._resolve_target(event, attrs)

        if self.is_terminal and target != self._state:
            raise InvalidSupervisorTransition(
                f"{self._state.value} is terminal; refusing {event.value}"
            )
        previous = self._state
        self._previous_state = previous
        self._state = target
        self._last_event = event
        self._transition_count += 1
        transition = SupervisorTransition(
            from_state=previous,
            to_state=target,
            event=event,
            reason=reason,
            attributes=attrs,
            timestamp=datetime.now(UTC).isoformat(),
        )
        if self._on_transition is not None:
            self._on_transition(
                from_state=transition.from_state,
                to_state=transition.to_state,
                event=transition.event,
                reason=transition.reason,
                attributes=transition.attributes,
                timestamp=transition.timestamp,
            )
        return transition

    def next_wait_seconds(
        self, deadline_ts: float, heartbeat_s: float, stall_check_s: float
    ) -> float:
        """Return the max wall-clock seconds to wait before checking conditions.

        The caller should pass this to asyncio.wait_for(proc.wait(), timeout=...).
        On TimeoutError the caller re-evaluates conditions (deadline, stall,
        heartbeat) and feeds the appropriate event.
        """
        now = datetime.now(UTC).timestamp()
        remaining = deadline_ts - now
        if remaining <= 0:
            return 0.0
        if self._state == SupervisorState.TERMINATING:
            return min(5.0, remaining)
        check = remaining
        if heartbeat_s > 0:
            check = min(check, heartbeat_s)
        if stall_check_s > 0 and self._state in {
            SupervisorState.RUNNING,
            SupervisorState.HEARTBEATING,
            SupervisorState.STALL_DETECTED,
            SupervisorState.RECOVERING,
        }:
            check = min(check, stall_check_s)
        return max(0.01, check)

    def export_projection(self) -> dict[str, Any]:
        return {
            "current_state": self._state.value,
            "previous_state": self._previous_state.value
            if self._previous_state
            else None,
            "last_event": self._last_event.value if self._last_event else None,
            "transition_count": self._transition_count,
            "exit_code": self._exit_code,
            "timed_out": self._timed_out,
            "killed": self._killed,
            "stdout_bytes": self._stdout_bytes,
            "stderr_bytes": self._stderr_bytes,
        }

    def _resolve_target(
        self, event: SupervisorEvent, attributes: dict[str, Any]
    ) -> SupervisorState:
        if event == SupervisorEvent.PROCESS_EXITED:
            if self._state in _TERMINAL_STATES:
                raise InvalidSupervisorTransition(
                    f"{self._state.value} is terminal; refusing PROCESS_EXITED"
                )
            if self._state not in _PROCESS_ALIVE_STATES:
                raise InvalidSupervisorTransition(
                    f"PROCESS_EXITED invalid from {self._state.value}"
                )
            exit_code = attributes.get("exit_code")
            if exit_code is not None and exit_code != 0:
                return SupervisorState.FAILED
            return SupervisorState.COMPLETED

        allowed = _TRANSITIONS.get(self._state, {})
        if target := allowed.get(event):
            return target

        raise InvalidSupervisorTransition(
            f"Invalid transition from {self._state.value} via {event.value}"
        )


# ── Backward-compatible aliases ───────────────────────────────────────

RuntimeSupervisorState = SupervisorState
RuntimeSupervisorEvent = SupervisorEvent
RuntimeSupervisorTransition = SupervisorTransition
InvalidRuntimeSupervisorTransition = InvalidSupervisorTransition


__all__ = [
    "InvalidRuntimeSupervisorTransition",
    "InvalidSupervisorTransition",
    "RuntimeSupervisorEvent",
    "RuntimeSupervisorState",
    "RuntimeSupervisorStateMachine",
    "RuntimeSupervisorTransition",
    "SupervisorEvent",
    "SupervisorState",
    "SupervisorTransition",
]
