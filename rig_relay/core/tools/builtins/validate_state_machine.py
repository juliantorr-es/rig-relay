"""Validate profile lifecycle state machine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum, auto
from typing import Any


class ValidateProfileState(StrEnum):
    IDLE = auto()
    PLANNING = auto()
    SELECTING_CHECKS = auto()
    RUNNING_CHECKS = auto()
    SUMMARIZING = auto()
    PASSED = auto()
    FAILED = auto()
    DEGRADED = auto()
    REFUSED = auto()


class ValidateProfileEvent(StrEnum):
    PROFILE_REQUESTED = auto()
    CHECKS_SELECTED = auto()
    CHECK_STARTED = auto()
    CHECK_PASSED = auto()
    CHECK_FAILED = auto()
    CHECK_SKIPPED = auto()
    TIMEOUT = auto()
    PROFILE_COMPLETED = auto()
    PROFILE_REFUSED = auto()


@dataclass(frozen=True, slots=True)
class ValidateProfileTransition:
    from_state: ValidateProfileState
    to_state: ValidateProfileState
    event: ValidateProfileEvent
    reason: str | None
    attributes: dict[str, Any]
    timestamp: str


class InvalidValidateProfileTransitionError(RuntimeError):
    """Raised when a validate profile transition is invalid."""


class TerminalValidateProfileStateError(RuntimeError):
    """Raised when a terminal validate profile state rejects transitions."""


_TRANSITIONS: dict[ValidateProfileState, dict[ValidateProfileEvent, ValidateProfileState]] = {
    ValidateProfileState.IDLE: {
        ValidateProfileEvent.PROFILE_REQUESTED: ValidateProfileState.PLANNING,
        ValidateProfileEvent.PROFILE_REFUSED: ValidateProfileState.REFUSED,
    },
    ValidateProfileState.PLANNING: {
        ValidateProfileEvent.CHECKS_SELECTED: ValidateProfileState.SELECTING_CHECKS,
        ValidateProfileEvent.PROFILE_REFUSED: ValidateProfileState.REFUSED,
        ValidateProfileEvent.TIMEOUT: ValidateProfileState.DEGRADED,
    },
    ValidateProfileState.SELECTING_CHECKS: {
        ValidateProfileEvent.CHECK_STARTED: ValidateProfileState.RUNNING_CHECKS,
        ValidateProfileEvent.PROFILE_REFUSED: ValidateProfileState.REFUSED,
        ValidateProfileEvent.TIMEOUT: ValidateProfileState.DEGRADED,
    },
    ValidateProfileState.RUNNING_CHECKS: {
        ValidateProfileEvent.CHECK_STARTED: ValidateProfileState.RUNNING_CHECKS,
        ValidateProfileEvent.CHECK_PASSED: ValidateProfileState.RUNNING_CHECKS,
        ValidateProfileEvent.CHECK_FAILED: ValidateProfileState.RUNNING_CHECKS,
        ValidateProfileEvent.CHECK_SKIPPED: ValidateProfileState.RUNNING_CHECKS,
        ValidateProfileEvent.PROFILE_COMPLETED: ValidateProfileState.SUMMARIZING,
        ValidateProfileEvent.TIMEOUT: ValidateProfileState.DEGRADED,
        ValidateProfileEvent.PROFILE_REFUSED: ValidateProfileState.REFUSED,
    },
    ValidateProfileState.SUMMARIZING: {
        ValidateProfileEvent.PROFILE_COMPLETED: ValidateProfileState.PASSED,
        ValidateProfileEvent.CHECK_FAILED: ValidateProfileState.FAILED,
        ValidateProfileEvent.TIMEOUT: ValidateProfileState.DEGRADED,
        ValidateProfileEvent.PROFILE_REFUSED: ValidateProfileState.REFUSED,
    },
    ValidateProfileState.PASSED: {},
    ValidateProfileState.FAILED: {},
    ValidateProfileState.DEGRADED: {},
    ValidateProfileState.REFUSED: {},
}

_EVENT_TO_STATE: dict[ValidateProfileEvent, ValidateProfileState] = {
    ValidateProfileEvent.PROFILE_REQUESTED: ValidateProfileState.PLANNING,
    ValidateProfileEvent.CHECKS_SELECTED: ValidateProfileState.SELECTING_CHECKS,
    ValidateProfileEvent.CHECK_STARTED: ValidateProfileState.RUNNING_CHECKS,
    ValidateProfileEvent.CHECK_PASSED: ValidateProfileState.RUNNING_CHECKS,
    ValidateProfileEvent.CHECK_FAILED: ValidateProfileState.RUNNING_CHECKS,
    ValidateProfileEvent.CHECK_SKIPPED: ValidateProfileState.RUNNING_CHECKS,
    ValidateProfileEvent.TIMEOUT: ValidateProfileState.DEGRADED,
    ValidateProfileEvent.PROFILE_REFUSED: ValidateProfileState.REFUSED,
}


class ValidateProfileStateMachine:
    def __init__(
        self,
        *,
        on_transition: Callable[..., Any] | None = None,
        trace_id: str | None = None,
    ) -> None:
        self._state = ValidateProfileState.IDLE
        self._previous_state: ValidateProfileState | None = None
        self._last_event: ValidateProfileEvent | None = None
        self._reason: str | None = None
        self._transition_count = 0
        self._on_transition = on_transition
        self._trace_id = trace_id

    @property
    def current_state(self) -> ValidateProfileState:
        return self._state

    @property
    def is_terminal(self) -> bool:
        return self._state in {
            ValidateProfileState.PASSED,
            ValidateProfileState.FAILED,
            ValidateProfileState.DEGRADED,
            ValidateProfileState.REFUSED,
        }

    def transition(
        self,
        event: ValidateProfileEvent,
        *,
        reason: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> ValidateProfileTransition:
        target = self._resolve_target(event, attributes or {})
        return self.transition_to(target, event, reason=reason, attributes=attributes)

    def transition_to(
        self,
        state: ValidateProfileState,
        event: ValidateProfileEvent,
        *,
        reason: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> ValidateProfileTransition:
        attrs = dict(attributes or {})
        if self._state == state and self._last_event == event:
            return self._build_transition(self._state, state, event, reason, attrs, emit=False)
        if self.is_terminal and state != self._state:
            raise TerminalValidateProfileStateError(f"{self._state} is terminal")
        if event == ValidateProfileEvent.PROFILE_COMPLETED:
            if self._state in {
                ValidateProfileState.SELECTING_CHECKS,
                ValidateProfileState.RUNNING_CHECKS,
            } and state in {
                ValidateProfileState.SUMMARIZING,
                ValidateProfileState.PASSED,
                ValidateProfileState.FAILED,
                ValidateProfileState.DEGRADED,
                ValidateProfileState.REFUSED,
            }:
                self._previous_state = self._state
                self._state = state
                self._last_event = event
                self._reason = reason
                self._transition_count += 1
                transition = self._build_transition(
                    self._previous_state,
                    state,
                    event,
                    reason,
                    attrs,
                    emit=False,
                )
                self._emit(transition)
                return transition
            if self._state == ValidateProfileState.SUMMARIZING and state in {
                ValidateProfileState.PASSED,
                ValidateProfileState.FAILED,
                ValidateProfileState.DEGRADED,
                ValidateProfileState.REFUSED,
            }:
                self._previous_state = self._state
                self._state = state
                self._last_event = event
                self._reason = reason
                self._transition_count += 1
                transition = self._build_transition(
                    self._previous_state,
                    state,
                    event,
                    reason,
                    attrs,
                    emit=False,
                )
                self._emit(transition)
                return transition
        allowed = _TRANSITIONS.get(self._state, {})
        if allowed.get(event) != state:
            raise InvalidValidateProfileTransitionError(
                f"Invalid transition from {self._state} via {event} to {state}"
            )
        previous = self._state
        self._previous_state = previous
        self._state = state
        self._last_event = event
        self._reason = reason
        self._transition_count += 1
        transition = self._build_transition(previous, state, event, reason, attrs)
        self._emit(transition)
        return transition

    def export_projection(self) -> dict[str, Any]:
        return {
            "state": self._state.value,
            "previous_state": self._previous_state.value if self._previous_state else None,
            "last_event": self._last_event.value if self._last_event else None,
            "reason": self._reason,
            "transition_count": self._transition_count,
            "trace_id": self._trace_id,
        }

    def _resolve_target(
        self, event: ValidateProfileEvent, attributes: dict[str, Any]
    ) -> ValidateProfileState:
        target: ValidateProfileState | None = None
        match event:
            case ValidateProfileEvent.PROFILE_COMPLETED:
                outcome = str(attributes.get("status") or attributes.get("outcome") or "passed")
                completion_states = {
                    "passed": ValidateProfileState.PASSED,
                    "failed": ValidateProfileState.FAILED,
                    "degraded": ValidateProfileState.DEGRADED,
                    "refused": ValidateProfileState.REFUSED,
                }
                if outcome in completion_states:
                    target = completion_states[outcome]
                else:
                    target = ValidateProfileState.SUMMARIZING
            case ValidateProfileEvent.CHECK_FAILED:
                if self._state == ValidateProfileState.SUMMARIZING:
                    target = ValidateProfileState.FAILED
                else:
                    target = ValidateProfileState.RUNNING_CHECKS
            case ValidateProfileEvent.PROFILE_REFUSED:
                target = ValidateProfileState.REFUSED
            case ValidateProfileEvent.TIMEOUT:
                target = ValidateProfileState.DEGRADED
            case _:
                target = _EVENT_TO_STATE.get(event)
        if target is None:
            raise InvalidValidateProfileTransitionError(f"Unknown event: {event}")
        return target

    def _build_transition(
        self,
        from_state: ValidateProfileState,
        to_state: ValidateProfileState,
        event: ValidateProfileEvent,
        reason: str | None,
        attributes: dict[str, Any],
        *,
        emit: bool = True,
    ) -> ValidateProfileTransition:
        transition = ValidateProfileTransition(
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

    def _emit(self, transition: ValidateProfileTransition) -> None:
        if self._on_transition is not None:
            self._on_transition(
                from_state=transition.from_state,
                to_state=transition.to_state,
                event=transition.event,
                reason=transition.reason,
                attributes=transition.attributes,
                timestamp=transition.timestamp,
                trace_id=self._trace_id,
            )
        if self._trace_id is None:
            return


__all__ = [
    "InvalidValidateProfileTransitionError",
    "TerminalValidateProfileStateError",
    "ValidateProfileEvent",
    "ValidateProfileState",
    "ValidateProfileStateMachine",
    "ValidateProfileTransition",
]
