from __future__ import annotations

import pytest

from rig_relay.desktop.bridge_state_machine import (
    DesktopBridgeEvent,
    DesktopBridgeState,
    DesktopBridgeStateMachine,
    InvalidBridgeTransitionError,
    TerminalBridgeStateError,
)


def test_valid_transition_chain() -> None:
    seen: list[tuple[str, str, str, str | None]] = []

    def on_transition(from_state, to_state, event, reason, **_kwargs):
        seen.append((from_state.value, to_state.value, event.value, reason))

    sm = DesktopBridgeStateMachine(on_transition=on_transition)
    sm.transition(DesktopBridgeEvent.RESOLVING_FRONTEND)
    sm.transition(DesktopBridgeEvent.ASSETS_VERIFIED)
    sm.transition(DesktopBridgeEvent.CONFIG_BUILT)
    sm.transition(DesktopBridgeEvent.SERVER_CREATED)
    sm.transition(DesktopBridgeEvent.SERVER_BOUND)
    sm.transition(DesktopBridgeEvent.SELF_PROBED)
    sm.transition(DesktopBridgeEvent.WEBVIEW_CREATED)
    sm.transition(DesktopBridgeEvent.WEBVIEW_STARTED)
    sm.transition(DesktopBridgeEvent.FRONTEND_CONFIG_LOADED)
    sm.transition(DesktopBridgeEvent.WEBSOCKET_CONNECTED)
    sm.transition(DesktopBridgeEvent.AUTHENTICATED)
    sm.transition(DesktopBridgeEvent.PROJECTION_SENT)
    sm.transition(DesktopBridgeEvent.PROJECTION_RENDERED)

    assert sm.current_state is DesktopBridgeState.LISTENING
    assert sm.transition_count == 13
    assert seen[0][0] == "uninitialized"
    assert seen[-1][1] == "listening"


def test_invalid_transition_refused() -> None:
    sm = DesktopBridgeStateMachine()
    with pytest.raises(InvalidBridgeTransitionError):
        sm.transition_to(DesktopBridgeState.LISTENING, DesktopBridgeEvent.SERVER_BOUND)


def test_terminal_failure_immutability() -> None:
    sm = DesktopBridgeStateMachine()
    sm.fail(DesktopBridgeEvent.FAILED, "probe failed")
    with pytest.raises(TerminalBridgeStateError):
        sm.transition(DesktopBridgeEvent.AUTHENTICATED)
    with pytest.raises(TerminalBridgeStateError):
        sm.transition(DesktopBridgeEvent.PROJECTION_RENDERED)


def test_duplicate_event_idempotent() -> None:
    sm = DesktopBridgeStateMachine()
    sm.transition(DesktopBridgeEvent.RESOLVING_FRONTEND)
    first = sm.export_projection()
    sm.transition(DesktopBridgeEvent.RESOLVING_FRONTEND)
    second = sm.export_projection()
    assert first == second


def test_export_projection_is_json_safe() -> None:
    sm = DesktopBridgeStateMachine()
    sm.transition(DesktopBridgeEvent.RESOLVING_FRONTEND)
    sm.fail(DesktopBridgeEvent.FAILED, "no frontend")
    projection = sm.export_projection()
    assert projection["state"] == "error"
    assert projection["previous_state"] == "token_generating"
    assert projection["last_event"] == "failed"
    assert projection["failed_step"] == "FAILED"
    assert projection["transition_count"] == 2
    assert isinstance(projection["transition_count"], int)


def test_trace_hook_receives_transition_payload() -> None:
    seen: list[dict[str, object]] = []

    def on_transition(**payload):
        seen.append(payload)

    sm = DesktopBridgeStateMachine(on_transition=on_transition)
    sm.transition(DesktopBridgeEvent.RESOLVING_FRONTEND, reason="startup")
    assert seen
    payload = seen[0]
    assert payload["from_state"] == DesktopBridgeState.UNINITIALIZED
    assert payload["to_state"] == DesktopBridgeState.TOKEN_GENERATING
    assert payload["event"] == DesktopBridgeEvent.RESOLVING_FRONTEND
    assert payload["reason"] == "startup"
