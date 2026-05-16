from __future__ import annotations

import json

import pytest

from rig_relay.core.tools.builtins.validate_state_machine import (
    InvalidValidateProfileTransitionError,
    TerminalValidateProfileStateError,
    ValidateProfileEvent,
    ValidateProfileState,
    ValidateProfileStateMachine,
)


def test_valid_transition_chain() -> None:
    machine = ValidateProfileStateMachine()
    machine.transition(ValidateProfileEvent.PROFILE_REQUESTED, reason="start")
    assert machine.current_state == ValidateProfileState.PLANNING
    machine.transition(ValidateProfileEvent.CHECKS_SELECTED, reason="selected")
    assert machine.current_state == ValidateProfileState.SELECTING_CHECKS
    machine.transition(ValidateProfileEvent.CHECK_STARTED, reason="run")
    assert machine.current_state == ValidateProfileState.RUNNING_CHECKS
    machine.transition(ValidateProfileEvent.CHECK_PASSED, reason="ok")
    assert machine.current_state == ValidateProfileState.RUNNING_CHECKS
    machine.transition(
        ValidateProfileEvent.PROFILE_COMPLETED,
        reason="done",
        attributes={"status": "passed"},
    )
    assert machine.current_state == ValidateProfileState.PASSED


def test_invalid_transition_refused() -> None:
    machine = ValidateProfileStateMachine()
    with pytest.raises(InvalidValidateProfileTransitionError):
        machine.transition(ValidateProfileEvent.CHECK_STARTED, reason="bad")


def test_terminal_immutability() -> None:
    machine = ValidateProfileStateMachine()
    machine.transition(ValidateProfileEvent.PROFILE_REQUESTED, reason="start")
    machine.transition(ValidateProfileEvent.CHECKS_SELECTED, reason="selected")
    machine.transition(ValidateProfileEvent.CHECK_STARTED, reason="run")
    machine.transition(
        ValidateProfileEvent.PROFILE_COMPLETED,
        reason="done",
        attributes={"status": "failed"},
    )
    assert machine.current_state == ValidateProfileState.FAILED
    with pytest.raises(TerminalValidateProfileStateError):
        machine.transition(ValidateProfileEvent.CHECK_PASSED, reason="late")


def test_timeout_degraded_path() -> None:
    machine = ValidateProfileStateMachine()
    machine.transition(ValidateProfileEvent.PROFILE_REQUESTED, reason="start")
    machine.transition(ValidateProfileEvent.CHECKS_SELECTED, reason="selected")
    machine.transition(ValidateProfileEvent.TIMEOUT, reason="slow")
    assert machine.current_state == ValidateProfileState.DEGRADED


def test_refused_path() -> None:
    machine = ValidateProfileStateMachine()
    machine.transition(ValidateProfileEvent.PROFILE_REQUESTED, reason="start")
    machine.transition(ValidateProfileEvent.PROFILE_REFUSED, reason="policy")
    assert machine.current_state == ValidateProfileState.REFUSED


def test_json_projection() -> None:
    machine = ValidateProfileStateMachine(trace_id="trace-1")
    machine.transition(ValidateProfileEvent.PROFILE_REQUESTED, reason="start")
    projection = machine.export_projection()
    json.dumps(projection)
    assert projection["state"] == "planning"
    assert projection["previous_state"] == "idle"
    assert projection["last_event"] == "profile_requested"
    assert projection["transition_count"] == 1


def test_transition_hook_receives_payload() -> None:
    seen: list[dict[str, object]] = []

    def record(**payload: object) -> None:
        seen.append(payload)

    machine = ValidateProfileStateMachine(on_transition=record, trace_id="trace-2")
    machine.transition(ValidateProfileEvent.PROFILE_REQUESTED, reason="start")

    assert seen
    payload = seen[0]
    assert payload["from_state"] == ValidateProfileState.IDLE
    assert payload["to_state"] == ValidateProfileState.PLANNING
    assert payload["event"] == ValidateProfileEvent.PROFILE_REQUESTED
    assert payload["reason"] == "start"
