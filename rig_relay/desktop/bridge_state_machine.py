"""Desktop bridge lifecycle state machine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any


class DesktopBridgeState(StrEnum):
    UNINITIALIZED = auto()
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


_TRANSITIONS: dict[DesktopBridgeState, dict[DesktopBridgeEvent, DesktopBridgeState]] = {
    DesktopBridgeState.UNINITIALIZED: {
        DesktopBridgeEvent.RESOLVING_FRONTEND: DesktopBridgeState.RESOLVING_FRONTEND,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.RESOLVING_FRONTEND: {
        DesktopBridgeEvent.ASSETS_VERIFIED: DesktopBridgeState.ASSETS_VERIFIED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.ASSETS_VERIFIED: {
        DesktopBridgeEvent.CONFIG_BUILT: DesktopBridgeState.CONFIG_BUILT,
        DesktopBridgeEvent.RESOLVING_FRONTEND: DesktopBridgeState.ASSETS_VERIFIED,
        DesktopBridgeEvent.ASSETS_VERIFIED: DesktopBridgeState.ASSETS_VERIFIED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.CONFIG_BUILT: {
        DesktopBridgeEvent.SERVER_CREATED: DesktopBridgeState.SERVER_CREATED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.SERVER_CREATED: {
        DesktopBridgeEvent.SERVER_BOUND: DesktopBridgeState.SERVER_BOUND,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.SERVER_BOUND: {
        DesktopBridgeEvent.SELF_PROBED: DesktopBridgeState.SELF_PROBED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.SELF_PROBED: {
        DesktopBridgeEvent.WEBVIEW_CREATED: DesktopBridgeState.WEBVIEW_CREATED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.WEBVIEW_CREATED: {
        DesktopBridgeEvent.WEBVIEW_STARTED: DesktopBridgeState.WEBVIEW_STARTED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.WEBVIEW_STARTED: {
        DesktopBridgeEvent.WEBSOCKET_CONNECTED: DesktopBridgeState.WEBSOCKET_CONNECTED,
        DesktopBridgeEvent.FRONTEND_CONFIG_LOADED: DesktopBridgeState.FRONTEND_CONFIG_LOADED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.FRONTEND_CONFIG_LOADED: {
        DesktopBridgeEvent.WEBSOCKET_CONNECTED: DesktopBridgeState.WEBSOCKET_CONNECTED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.WEBSOCKET_CONNECTED: {
        DesktopBridgeEvent.AUTHENTICATED: DesktopBridgeState.AUTHENTICATED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.AUTHENTICATED: {
        DesktopBridgeEvent.PROJECTION_SENT: DesktopBridgeState.PROJECTION_SENT,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.PROJECTION_SENT: {
        DesktopBridgeEvent.PROJECTION_RENDERED: DesktopBridgeState.PROJECTION_RENDERED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
    },
    DesktopBridgeState.PROJECTION_RENDERED: {
        DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
        DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
    },
    DesktopBridgeState.FAILED: {},
    DesktopBridgeState.CLOSED: {},
}

_EVENT_TO_STATE: dict[DesktopBridgeEvent, DesktopBridgeState] = {
    DesktopBridgeEvent.RESOLVING_FRONTEND: DesktopBridgeState.RESOLVING_FRONTEND,
    DesktopBridgeEvent.ASSETS_VERIFIED: DesktopBridgeState.ASSETS_VERIFIED,
    DesktopBridgeEvent.CONFIG_BUILT: DesktopBridgeState.CONFIG_BUILT,
    DesktopBridgeEvent.SERVER_CREATED: DesktopBridgeState.SERVER_CREATED,
    DesktopBridgeEvent.SERVER_BOUND: DesktopBridgeState.SERVER_BOUND,
    DesktopBridgeEvent.SELF_PROBED: DesktopBridgeState.SELF_PROBED,
    DesktopBridgeEvent.WEBVIEW_CREATED: DesktopBridgeState.WEBVIEW_CREATED,
    DesktopBridgeEvent.WEBVIEW_STARTED: DesktopBridgeState.WEBVIEW_STARTED,
    DesktopBridgeEvent.FRONTEND_CONFIG_LOADED: DesktopBridgeState.FRONTEND_CONFIG_LOADED,
    DesktopBridgeEvent.WEBSOCKET_CONNECTED: DesktopBridgeState.WEBSOCKET_CONNECTED,
    DesktopBridgeEvent.AUTHENTICATED: DesktopBridgeState.AUTHENTICATED,
    DesktopBridgeEvent.PROJECTION_SENT: DesktopBridgeState.PROJECTION_SENT,
    DesktopBridgeEvent.PROJECTION_RENDERED: DesktopBridgeState.PROJECTION_RENDERED,
    DesktopBridgeEvent.FAILED: DesktopBridgeState.FAILED,
    DesktopBridgeEvent.CLOSED: DesktopBridgeState.CLOSED,
}


class DesktopBridgeStateMachine:
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
    def current_state(self) -> DesktopBridgeState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in {DesktopBridgeState.FAILED, DesktopBridgeState.CLOSED}

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
        if self.is_terminal and state not in {
            DesktopBridgeState.FAILED,
            DesktopBridgeState.CLOSED,
        }:
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
        return transition

    def fail(
        self,
        event: DesktopBridgeEvent,
        reason: str,
        attributes: dict[str, Any] | None = None,
    ) -> DesktopBridgeTransition:
        self._failed_step = str((attributes or {}).get("step_id") or event.name)
        return self.transition_to(
            DesktopBridgeState.FAILED, event, reason=reason, attributes=attributes
        )

    def close(self, event: str = "closed") -> DesktopBridgeTransition:
        bridge_event = DesktopBridgeEvent.CLOSED
        if self._state == DesktopBridgeState.CLOSED:
            return self._build_transition(
                self._state, self._state, bridge_event, event, {}, record=False
            )
        return self.transition_to(
            DesktopBridgeState.CLOSED, bridge_event, reason=event, attributes=None
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


__all__ = [
    "DesktopBridgeEvent",
    "DesktopBridgeState",
    "DesktopBridgeStateMachine",
    "DesktopBridgeTransition",
    "InvalidBridgeTransitionError",
    "TerminalBridgeStateError",
]
