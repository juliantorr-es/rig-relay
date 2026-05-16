from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any


class RuntimeSupervisorState(StrEnum):
    IDLE = auto()
    LEASED = auto()
    SPAWNING = auto()
    RUNNING = auto()
    DRAINING = auto()
    COMPLETED = auto()
    FAILED = auto()
    TIMED_OUT = auto()
    KILLED = auto()
    CANCELLED = auto()


class RuntimeSupervisorEvent(StrEnum):
    LEASE_ACQUIRED = auto()
    SPAWN_STARTED = auto()
    SPAWN_SUCCEEDED = auto()
    STDOUT_CHUNK = auto()
    STDERR_CHUNK = auto()
    PROCESS_EXITED = auto()
    DRAIN_COMPLETED = auto()
    TIMEOUT = auto()
    KILL_SENT = auto()
    CANCELLED = auto()
    FAILURE = auto()


@dataclass(frozen=True, slots=True)
class RuntimeSupervisorTransition:
    from_state: RuntimeSupervisorState
    to_state: RuntimeSupervisorState
    event: RuntimeSupervisorEvent
    reason: str | None
    attributes: dict[str, Any]
    timestamp: str


class InvalidRuntimeSupervisorTransition(Exception):
    pass


_TRANSITIONS: dict[
    RuntimeSupervisorState, dict[RuntimeSupervisorEvent, RuntimeSupervisorState]
] = {
    RuntimeSupervisorState.IDLE: {
        RuntimeSupervisorEvent.LEASE_ACQUIRED: RuntimeSupervisorState.LEASED
    },
    RuntimeSupervisorState.LEASED: {
        RuntimeSupervisorEvent.SPAWN_STARTED: RuntimeSupervisorState.SPAWNING,
        RuntimeSupervisorEvent.FAILURE: RuntimeSupervisorState.FAILED,
        RuntimeSupervisorEvent.CANCELLED: RuntimeSupervisorState.CANCELLED,
    },
    RuntimeSupervisorState.SPAWNING: {
        RuntimeSupervisorEvent.SPAWN_SUCCEEDED: RuntimeSupervisorState.RUNNING,
        RuntimeSupervisorEvent.FAILURE: RuntimeSupervisorState.FAILED,
        RuntimeSupervisorEvent.CANCELLED: RuntimeSupervisorState.CANCELLED,
    },
    RuntimeSupervisorState.RUNNING: {
        RuntimeSupervisorEvent.STDOUT_CHUNK: RuntimeSupervisorState.RUNNING,
        RuntimeSupervisorEvent.STDERR_CHUNK: RuntimeSupervisorState.RUNNING,
        RuntimeSupervisorEvent.TIMEOUT: RuntimeSupervisorState.TIMED_OUT,
        RuntimeSupervisorEvent.KILL_SENT: RuntimeSupervisorState.KILLED,
        RuntimeSupervisorEvent.CANCELLED: RuntimeSupervisorState.CANCELLED,
        RuntimeSupervisorEvent.FAILURE: RuntimeSupervisorState.FAILED,
    },
    RuntimeSupervisorState.DRAINING: {
        RuntimeSupervisorEvent.DRAIN_COMPLETED: RuntimeSupervisorState.COMPLETED,
        RuntimeSupervisorEvent.FAILURE: RuntimeSupervisorState.FAILED,
        RuntimeSupervisorEvent.TIMEOUT: RuntimeSupervisorState.TIMED_OUT,
    },
    RuntimeSupervisorState.COMPLETED: {},
    RuntimeSupervisorState.FAILED: {},
    RuntimeSupervisorState.TIMED_OUT: {},
    RuntimeSupervisorState.KILLED: {},
    RuntimeSupervisorState.CANCELLED: {},
}


class RuntimeSupervisorStateMachine:
    def __init__(self, *, on_transition: Callable[..., Any] | None = None) -> None:
        self._state = RuntimeSupervisorState.IDLE
        self._previous_state: RuntimeSupervisorState | None = None
        self._last_event: RuntimeSupervisorEvent | None = None
        self._transition_count = 0
        self._exit_code: int | None = None
        self._timed_out = False
        self._killed = False
        self._stdout_bytes = 0
        self._stderr_bytes = 0
        self._on_transition = on_transition

    @property
    def current_state(self) -> RuntimeSupervisorState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in {
            RuntimeSupervisorState.COMPLETED,
            RuntimeSupervisorState.FAILED,
            RuntimeSupervisorState.TIMED_OUT,
            RuntimeSupervisorState.KILLED,
            RuntimeSupervisorState.CANCELLED,
        }

    def transition(
        self,
        event: RuntimeSupervisorEvent,
        *,
        reason: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> RuntimeSupervisorTransition:
        attrs = dict(attributes or {})
        if event in {
            RuntimeSupervisorEvent.STDOUT_CHUNK,
            RuntimeSupervisorEvent.STDERR_CHUNK,
        }:
            self._stdout_bytes = int(attrs.get("stdout_bytes", self._stdout_bytes))
            self._stderr_bytes = int(attrs.get("stderr_bytes", self._stderr_bytes))
        if event == RuntimeSupervisorEvent.TIMEOUT:
            self._timed_out = bool(attrs.get("timed_out", True))
        if event == RuntimeSupervisorEvent.KILL_SENT:
            self._killed = True
        if "exit_code" in attrs and attrs["exit_code"] is not None:
            self._exit_code = int(attrs["exit_code"])
        target = self._resolve_target(event, attrs)
        if self.is_terminal and target != self._state:
            raise InvalidRuntimeSupervisorTransition(f"{self._state} is terminal")
        if self._state == target and self._last_event == event:
            return self._build_transition(
                self._state, target, event, reason, attrs, emit=False
            )
        previous = self._state
        self._previous_state = previous
        self._state = target
        self._last_event = event
        self._transition_count += 1
        transition = self._build_transition(previous, target, event, reason, attrs)
        self._emit(transition)
        return transition

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
        self, event: RuntimeSupervisorEvent, attributes: dict[str, Any]
    ) -> RuntimeSupervisorState:
        target: RuntimeSupervisorState | None = None
        match event:
            case RuntimeSupervisorEvent.PROCESS_EXITED:
                if self._state != RuntimeSupervisorState.RUNNING:
                    raise InvalidRuntimeSupervisorTransition(
                        f"Invalid transition from {self._state} via {event}"
                    )
                target = RuntimeSupervisorState.DRAINING
            case RuntimeSupervisorEvent.DRAIN_COMPLETED:
                if self._state != RuntimeSupervisorState.DRAINING:
                    raise InvalidRuntimeSupervisorTransition(
                        f"Invalid transition from {self._state} via {event}"
                    )
                if attributes.get("exit_code") == 0 or self._exit_code == 0:
                    target = RuntimeSupervisorState.COMPLETED
                else:
                    target = RuntimeSupervisorState.FAILED
            case RuntimeSupervisorEvent.TIMEOUT:
                target = RuntimeSupervisorState.TIMED_OUT
            case RuntimeSupervisorEvent.KILL_SENT:
                target = RuntimeSupervisorState.KILLED
            case RuntimeSupervisorEvent.CANCELLED:
                target = RuntimeSupervisorState.CANCELLED
            case RuntimeSupervisorEvent.FAILURE:
                target = RuntimeSupervisorState.FAILED
            case _:
                allowed = _TRANSITIONS.get(self._state, {})
                if target := allowed.get(event):
                    pass
        if target is None:
            raise InvalidRuntimeSupervisorTransition(
                f"Invalid transition from {self._state} via {event}"
            )
        return target

    def _build_transition(
        self,
        from_state: RuntimeSupervisorState,
        to_state: RuntimeSupervisorState,
        event: RuntimeSupervisorEvent,
        reason: str | None,
        attributes: dict[str, Any],
        *,
        emit: bool = True,
    ) -> RuntimeSupervisorTransition:
        transition = RuntimeSupervisorTransition(
            from_state=from_state,
            to_state=to_state,
            event=event,
            reason=reason,
            attributes=attributes,
            timestamp=datetime.now(UTC).isoformat(),
        )
        if emit:
            self._emit(transition)
        return transition

    def _emit(self, transition: RuntimeSupervisorTransition) -> None:
        if self._on_transition is not None:
            self._on_transition(
                from_state=transition.from_state,
                to_state=transition.to_state,
                event=transition.event,
                reason=transition.reason,
                attributes=transition.attributes,
                timestamp=transition.timestamp,
            )


__all__ = [
    "InvalidRuntimeSupervisorTransition",
    "RuntimeSupervisorEvent",
    "RuntimeSupervisorState",
    "RuntimeSupervisorStateMachine",
    "RuntimeSupervisorTransition",
]
