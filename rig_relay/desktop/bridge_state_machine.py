"""Desktop bridge lifecycle state machine — phase-based with strict validation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
import json as _json
from pathlib import Path as _Path
from typing import Any


class DesktopBridgeState(StrEnum):
    UNINITIALIZED = auto()
    TOKEN_GENERATING = auto()
    TOKEN_VERIFYING = auto()
    PORT_BINDING = auto()
    LISTENING = auto()
    ERROR = auto()
    SHUTDOWN = auto()


class DesktopBridgeEvent(StrEnum):
    RESOLVING_FRONTEND = auto()
    ASSETS_VERIFIED = auto()
    CONFIG_BUILT = auto()
    SERVER_CREATED = auto()
    SERVER_BOUND = auto()
    SELF_PROBED = auto()
    WEBVIEW_CREATED = auto()
    WEBVIEW_STARTED = auto()
    FRONTEND_CONFIG_LOADED = auto()
    WEBSOCKET_CONNECTED = auto()
    AUTHENTICATED = auto()
    PROJECTION_SENT = auto()
    PROJECTION_RENDERED = auto()
    FAILED = auto()
    CLOSED = auto()


@dataclass(frozen=True, slots=True)
class DesktopBridgeTransition:
    from_state: DesktopBridgeState
    to_state: DesktopBridgeState
    event: DesktopBridgeEvent
    reason: str | None
    attributes: dict[str, Any]
    timestamp: str


class InvalidBridgeTransitionError(RuntimeError):
    """Raised when a bridge transition is invalid."""


class TerminalBridgeStateError(RuntimeError):
    """Raised when a terminal bridge state rejects transitions."""


_TERMINAL_STATES = frozenset({DesktopBridgeState.ERROR, DesktopBridgeState.SHUTDOWN})

_OPERATIONAL_EVENTS = frozenset({
    DesktopBridgeEvent.SELF_PROBED,
    DesktopBridgeEvent.WEBVIEW_CREATED,
    DesktopBridgeEvent.WEBVIEW_STARTED,
    DesktopBridgeEvent.FRONTEND_CONFIG_LOADED,
    DesktopBridgeEvent.WEBSOCKET_CONNECTED,
    DesktopBridgeEvent.AUTHENTICATED,
    DesktopBridgeEvent.PROJECTION_SENT,
    DesktopBridgeEvent.PROJECTION_RENDERED,
})

_TRANSITIONS: dict[DesktopBridgeState, dict[DesktopBridgeEvent, DesktopBridgeState]] = {
    DesktopBridgeState.UNINITIALIZED: {
        DesktopBridgeEvent.RESOLVING_FRONTEND: DesktopBridgeState.TOKEN_GENERATING,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.ERROR,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.SHUTDOWN,
    },
    DesktopBridgeState.TOKEN_GENERATING: {
        DesktopBridgeEvent.ASSETS_VERIFIED: DesktopBridgeState.TOKEN_GENERATING,
        DesktopBridgeEvent.CONFIG_BUILT: DesktopBridgeState.TOKEN_VERIFYING,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.ERROR,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.SHUTDOWN,
    },
    DesktopBridgeState.TOKEN_VERIFYING: {
        DesktopBridgeEvent.SERVER_CREATED: DesktopBridgeState.PORT_BINDING,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.ERROR,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.SHUTDOWN,
    },
    DesktopBridgeState.PORT_BINDING: {
        DesktopBridgeEvent.SERVER_BOUND: DesktopBridgeState.LISTENING,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.ERROR,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.SHUTDOWN,
    },
    DesktopBridgeState.LISTENING: {
        DesktopBridgeEvent.SELF_PROBED: DesktopBridgeState.LISTENING,
        DesktopBridgeEvent.WEBVIEW_CREATED: DesktopBridgeState.LISTENING,
        DesktopBridgeEvent.WEBVIEW_STARTED: DesktopBridgeState.LISTENING,
        DesktopBridgeEvent.FRONTEND_CONFIG_LOADED: DesktopBridgeState.LISTENING,
        DesktopBridgeEvent.WEBSOCKET_CONNECTED: DesktopBridgeState.LISTENING,
        DesktopBridgeEvent.AUTHENTICATED: DesktopBridgeState.LISTENING,
        DesktopBridgeEvent.PROJECTION_SENT: DesktopBridgeState.LISTENING,
        DesktopBridgeEvent.PROJECTION_RENDERED: DesktopBridgeState.LISTENING,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.ERROR,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.SHUTDOWN,
    },
    DesktopBridgeState.ERROR: {DesktopBridgeEvent.CLOSED: DesktopBridgeState.SHUTDOWN},
    DesktopBridgeState.SHUTDOWN: {},
}

_EVENT_TO_STATE: dict[DesktopBridgeEvent, DesktopBridgeState] = {
    DesktopBridgeEvent.RESOLVING_FRONTEND: DesktopBridgeState.TOKEN_GENERATING,
    DesktopBridgeEvent.ASSETS_VERIFIED: DesktopBridgeState.TOKEN_GENERATING,
    DesktopBridgeEvent.CONFIG_BUILT: DesktopBridgeState.TOKEN_VERIFYING,
    DesktopBridgeEvent.SERVER_CREATED: DesktopBridgeState.PORT_BINDING,
    DesktopBridgeEvent.SERVER_BOUND: DesktopBridgeState.LISTENING,
    DesktopBridgeEvent.SELF_PROBED: DesktopBridgeState.LISTENING,
    DesktopBridgeEvent.WEBVIEW_CREATED: DesktopBridgeState.LISTENING,
    DesktopBridgeEvent.WEBVIEW_STARTED: DesktopBridgeState.LISTENING,
    DesktopBridgeEvent.FRONTEND_CONFIG_LOADED: DesktopBridgeState.LISTENING,
    DesktopBridgeEvent.WEBSOCKET_CONNECTED: DesktopBridgeState.LISTENING,
    DesktopBridgeEvent.AUTHENTICATED: DesktopBridgeState.LISTENING,
    DesktopBridgeEvent.PROJECTION_SENT: DesktopBridgeState.LISTENING,
    DesktopBridgeEvent.PROJECTION_RENDERED: DesktopBridgeState.LISTENING,
    DesktopBridgeEvent.FAILED: DesktopBridgeState.ERROR,
    DesktopBridgeEvent.CLOSED: DesktopBridgeState.SHUTDOWN,
}


def _state_accepts_operational(state: DesktopBridgeState) -> bool:
    return state is DesktopBridgeState.LISTENING


class DesktopBridgeStateMachine:
    _lifecycle_log_path: _Path | None = None

    def __init__(
        self,
        *,
        on_transition: Callable[..., Any] | None = None,
        trace_id: str | None = None,
    ) -> None:
        self._state = DesktopBridgeState.UNINITIALIZED
        self._previous_state: DesktopBridgeState | None = None
        self._last_event: DesktopBridgeEvent | None = None
        self._failed_step: str | None = None
        self._transition_count = 0
        self._on_transition = on_transition
        self._trace_id = trace_id

    @property
    def lifecycle_log_path(self) -> _Path | None:
        return self._lifecycle_log_path

    def set_lifecycle_log_path(self, path: _Path) -> None:
        self._lifecycle_log_path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def current_state(self) -> DesktopBridgeState:
        return self._state

    @property
    def is_listening(self) -> bool:
        return self._state is DesktopBridgeState.LISTENING

    @property
    def is_active(self) -> bool:
        return self._state is DesktopBridgeState.LISTENING

    @property
    def is_terminal(self) -> bool:
        return self._state in _TERMINAL_STATES

    @property
    def transition_count(self) -> int:
        return self._transition_count

    def transition(
        self,
        event: DesktopBridgeEvent,
        reason: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> DesktopBridgeTransition:
        if self.is_terminal and event not in {
            DesktopBridgeEvent.FAILED,
            DesktopBridgeEvent.CLOSED,
        }:
            raise TerminalBridgeStateError(f"{self._state} is terminal")
        target = _EVENT_TO_STATE.get(event)
        if target is None:
            raise InvalidBridgeTransitionError(f"Unknown event: {event}")
        return self.transition_to(target, event, reason=reason, attributes=attributes)

    def transition_to(
        self,
        state: DesktopBridgeState,
        event: DesktopBridgeEvent,
        reason: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> DesktopBridgeTransition:
        attrs = dict(attributes or {})
        if self._state == state and self._last_event == event:
            return self._build_transition(
                self._state, state, event, reason, attrs, record=False
            )
        if self.is_terminal and state not in _TERMINAL_STATES:
            raise TerminalBridgeStateError(f"{self._state} is terminal")
        allowed = _TRANSITIONS.get(self._state, {})
        if allowed.get(event) != state:
            raise InvalidBridgeTransitionError(
                f"Invalid transition from {self._state} via {event} to {state}"
            )
        previous = self._state
        self._previous_state = previous
        self._state = state
        self._last_event = event
        self._transition_count += 1
        transition = self._build_transition(previous, state, event, reason, attrs)
        self._emit(transition)
        self._write_lifecycle_event(transition)
        return transition

    def fail(
        self,
        event: DesktopBridgeEvent,
        reason: str,
        attributes: dict[str, Any] | None = None,
    ) -> DesktopBridgeTransition:
        self._failed_step = str((attributes or {}).get("step_id") or event.name)
        return self.transition_to(
            DesktopBridgeState.ERROR, event, reason=reason, attributes=attributes
        )

    def close(self, event: str = "closed") -> DesktopBridgeTransition:
        bridge_event = DesktopBridgeEvent.CLOSED
        if self._state == DesktopBridgeState.SHUTDOWN:
            return self._build_transition(
                self._state, self._state, bridge_event, event, {}, record=False
            )
        return self.transition_to(
            DesktopBridgeState.SHUTDOWN, bridge_event, reason=event, attributes=None
        )

    def export_projection(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "previous_state": self._previous_state.value
            if self._previous_state
            else None,
            "last_event": self._last_event.value if self._last_event else None,
            "failed_step": self._failed_step,
            "transition_count": self._transition_count,
            "trace_id": self._trace_id,
        }

    def _build_transition(
        self,
        from_state: DesktopBridgeState,
        to_state: DesktopBridgeState,
        event: DesktopBridgeEvent,
        reason: str | None,
        attributes: dict[str, Any],
        *,
        record: bool = True,
    ) -> DesktopBridgeTransition:
        transition = DesktopBridgeTransition(
            from_state=from_state,
            to_state=to_state,
            event=event,
            reason=reason,
            attributes=attributes,
            timestamp=datetime.now(UTC).isoformat(),
        )
        if record:
            self._transition_count += 0
        return transition

    def _emit(self, transition: DesktopBridgeTransition) -> None:
        if self._on_transition is None:
            return
        payload = {
            "from_state": transition.from_state,
            "to_state": transition.to_state,
            "event": transition.event,
            "reason": transition.reason,
            "attributes": transition.attributes,
            "timestamp": transition.timestamp,
            "trace_id": self._trace_id,
        }
        self._on_transition(**payload)

    def _write_lifecycle_event(self, transition: DesktopBridgeTransition) -> None:
        if self._lifecycle_log_path is None:
            return
        entry = {
            "schema_version": "rig.desktop.bridge_lifecycle.v1",
            "state": transition.to_state.value,
            "previous_state": transition.from_state.value,
            "event": transition.event.value,
            "timestamp": transition.timestamp,
            "transition_count": self._transition_count,
        }
        with self._lifecycle_log_path.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(entry, sort_keys=True) + "\n")
            f.flush()


__all__ = [
    "DesktopBridgeEvent",
    "DesktopBridgeState",
    "DesktopBridgeStateMachine",
    "DesktopBridgeTransition",
    "InvalidBridgeTransitionError",
    "TerminalBridgeStateError",
]
