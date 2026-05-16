from __future__ import annotations

import pytest

from rig_relay.runtime.supervisor_state_machine import (
    InvalidRuntimeSupervisorTransition,
    RuntimeSupervisorEvent,
    RuntimeSupervisorState,
    RuntimeSupervisorStateMachine,
)


def test_valid_lifecycle_chain() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(RuntimeSupervisorEvent.LEASE_ACQUIRED)
    assert machine.current_state == RuntimeSupervisorState.LEASED
    machine.transition(RuntimeSupervisorEvent.SPAWN_STARTED)
    assert machine.current_state == RuntimeSupervisorState.SPAWNING
    machine.transition(RuntimeSupervisorEvent.SPAWN_SUCCEEDED)
    assert machine.current_state == RuntimeSupervisorState.RUNNING
    machine.transition(RuntimeSupervisorEvent.STDOUT_CHUNK, attributes={"stdout_bytes": 3})
    assert machine.current_state == RuntimeSupervisorState.RUNNING
    machine.transition(RuntimeSupervisorEvent.PROCESS_EXITED, attributes={"exit_code": 0})
    assert machine.current_state == RuntimeSupervisorState.DRAINING
    machine.transition(RuntimeSupervisorEvent.DRAIN_COMPLETED, attributes={"exit_code": 0})
    assert machine.current_state == RuntimeSupervisorState.COMPLETED


def test_idle_to_running_refused() -> None:
    machine = RuntimeSupervisorStateMachine()
    with pytest.raises(InvalidRuntimeSupervisorTransition):
        machine.transition(RuntimeSupervisorEvent.PROCESS_EXITED)


def test_terminal_immutability() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(RuntimeSupervisorEvent.LEASE_ACQUIRED)
    machine.transition(RuntimeSupervisorEvent.SPAWN_STARTED)
    machine.transition(RuntimeSupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(RuntimeSupervisorEvent.PROCESS_EXITED)
    assert machine.current_state == RuntimeSupervisorState.DRAINING
    machine.transition(RuntimeSupervisorEvent.DRAIN_COMPLETED, attributes={"exit_code": 0})
    assert machine.current_state == RuntimeSupervisorState.COMPLETED
    with pytest.raises(InvalidRuntimeSupervisorTransition):
        machine.transition(RuntimeSupervisorEvent.STDOUT_CHUNK)


def test_timeout_projection() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(RuntimeSupervisorEvent.LEASE_ACQUIRED)
    machine.transition(RuntimeSupervisorEvent.SPAWN_STARTED)
    machine.transition(RuntimeSupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(RuntimeSupervisorEvent.TIMEOUT, attributes={"timed_out": True})
    assert machine.current_state == RuntimeSupervisorState.TIMED_OUT
    projection = machine.export_projection()
    assert projection["current_state"] == "timed_out"
    assert projection["timed_out"] is True


def test_json_projection_is_safe() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(RuntimeSupervisorEvent.LEASE_ACQUIRED)
    projection = machine.export_projection()
    assert projection["current_state"] == "leased"
    assert projection["previous_state"] == "idle"
    assert projection["last_event"] == "lease_acquired"
    assert "stdout" not in projection
    assert "stderr" not in projection
