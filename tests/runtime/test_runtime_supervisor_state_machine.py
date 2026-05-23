from __future__ import annotations

import pytest

# Backward-compatible aliases
from rig_relay.runtime.supervisor_state_machine import (
    InvalidSupervisorTransition,
    RuntimeSupervisorEvent,
    RuntimeSupervisorState,
    RuntimeSupervisorStateMachine,
    SupervisorEvent,
    SupervisorState,
)


def test_valid_lifecycle_chain() -> None:
    machine = RuntimeSupervisorStateMachine()
    assert machine.current_state == SupervisorState.IDLE
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    assert machine.current_state == SupervisorState.SPAWNING
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    assert machine.current_state == SupervisorState.RUNNING
    # HEARTBEAT_TIMER: RUNNING -> HEARTBEATING
    machine.transition(SupervisorEvent.HEARTBEAT_TIMER)
    assert machine.current_state == SupervisorState.HEARTBEATING
    # OUTPUT_CHUNK: HEARTBEATING -> RUNNING (recovery)
    machine.transition(SupervisorEvent.OUTPUT_CHUNK)
    assert machine.current_state == SupervisorState.RUNNING
    # PROCESS_EXITED with exit_code=0: -> COMPLETED
    machine.transition(SupervisorEvent.PROCESS_EXITED, attributes={"exit_code": 0})
    assert machine.current_state == SupervisorState.COMPLETED
    assert machine.is_terminal


def test_process_exited_nonzero_goes_to_failed() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.PROCESS_EXITED, attributes={"exit_code": 42})
    assert machine.current_state == SupervisorState.FAILED
    assert machine.is_terminal


def test_idle_refuses_process_exited() -> None:
    machine = RuntimeSupervisorStateMachine()
    with pytest.raises(InvalidSupervisorTransition):
        machine.transition(SupervisorEvent.PROCESS_EXITED)


def test_idle_refuses_heartbeat_timer() -> None:
    machine = RuntimeSupervisorStateMachine()
    with pytest.raises(InvalidSupervisorTransition):
        machine.transition(SupervisorEvent.HEARTBEAT_TIMER)


def test_spawning_to_failed_on_spawn_failed() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_FAILED)
    assert machine.current_state == SupervisorState.FAILED


def test_terminal_immutability() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.PROCESS_EXITED, attributes={"exit_code": 0})
    assert machine.current_state == SupervisorState.COMPLETED
    with pytest.raises(InvalidSupervisorTransition):
        machine.transition(SupervisorEvent.OUTPUT_CHUNK)


def test_timeout_transition() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.TIMEOUT)
    assert machine.current_state == SupervisorState.TERMINATING
    machine.transition(SupervisorEvent.KILL_SENT)
    assert machine.current_state == SupervisorState.KILLED


def test_cancelled_transition() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.CANCELLED)
    assert machine.current_state == SupervisorState.TERMINATING


def test_stall_timer_transition() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.STALL_TIMER)
    assert machine.current_state == SupervisorState.STALL_DETECTED


def test_stall_recovery_transition() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.HEARTBEAT_TIMER)
    assert machine.current_state == SupervisorState.HEARTBEATING
    machine.transition(SupervisorEvent.OUTPUT_CHUNK)
    assert machine.current_state == SupervisorState.RUNNING


def test_stall_detected_to_recovering() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.STALL_TIMER)
    assert machine.current_state == SupervisorState.STALL_DETECTED
    machine.transition(SupervisorEvent.OUTPUT_CHUNK)
    assert machine.current_state == SupervisorState.RECOVERING


def test_hard_stall_to_terminating() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.STALL_TIMER)
    assert machine.current_state == SupervisorState.STALL_DETECTED
    machine.transition(SupervisorEvent.HARD_STALL)
    assert machine.current_state == SupervisorState.TERMINATING


def test_budget_exceeded_to_terminating() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.BUDGET_EXCEEDED)
    assert machine.current_state == SupervisorState.TERMINATING


def test_running_self_loop_output_chunk() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    # OUTPUT_CHUNK from RUNNING is a self-loop (not in transition table)
    with pytest.raises(InvalidSupervisorTransition):
        machine.transition(SupervisorEvent.OUTPUT_CHUNK)


def test_timeout_projection() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.TIMEOUT, attributes={"timed_out": True})
    assert machine.current_state == SupervisorState.TERMINATING
    projection = machine.export_projection()
    assert projection["current_state"] == "terminating"
    assert projection["timed_out"] is True


def test_json_projection_is_safe() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    projection = machine.export_projection()
    assert projection["current_state"] == "spawning"
    assert projection["previous_state"] == "idle"
    assert projection["last_event"] == "spawn_started"
    assert "stdout" not in projection
    assert "stderr" not in projection


def test_next_wait_seconds_at_deadline() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    import time as _time

    past = _time.time() - 10.0
    wait = machine.next_wait_seconds(past, 1.0, 1.0)
    assert wait == 0.0


def test_next_wait_seconds_terminating() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.TIMEOUT)
    import time as _time

    future = _time.time() + 60.0
    wait = machine.next_wait_seconds(future, 1.0, 1.0)
    assert wait == 5.0


def test_next_wait_seconds_running() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    import time as _time

    future = _time.time() + 60.0
    wait = machine.next_wait_seconds(future, heartbeat_s=1.0, stall_check_s=2.0)
    assert wait == 1.0  # min(60, 1, 2) = 1


def test_next_wait_seconds_no_heartbeat() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    import time as _time

    future = _time.time() + 60.0
    wait = machine.next_wait_seconds(future, heartbeat_s=0.0, stall_check_s=2.0)
    assert wait == 2.0  # min(60, 2) = 2


def test_backward_compat_aliases() -> None:
    assert RuntimeSupervisorState is SupervisorState
    assert RuntimeSupervisorEvent is SupervisorEvent


def test_killed_is_terminal() -> None:
    machine = RuntimeSupervisorStateMachine()
    machine.transition(SupervisorEvent.SPAWN_STARTED)
    machine.transition(SupervisorEvent.SPAWN_SUCCEEDED)
    machine.transition(SupervisorEvent.TIMEOUT)
    machine.transition(SupervisorEvent.KILL_SENT)
    assert machine.current_state == SupervisorState.KILLED
    assert machine.is_terminal
