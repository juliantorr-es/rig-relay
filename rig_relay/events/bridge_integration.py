from __future__ import annotations

from typing import Any

from rig_relay.events.envelope import (
    EventEnvelope,
    EventRedactionStatus,
    EventSensitivityClass,
    new_event_id,
)


def bridge_event_from_lifecycle(
    *,
    event_name: str,
    handshake_id: str,
    correlation_id: str,
    backend_session_id: str = "",
    bridge_runtime_state: str = "",
    idle_sequence: int = 0,
    details: dict[str, Any] | None = None,
    sequence: int = 0,
    trace_id: str = "",
    span_id: str = "",
) -> dict[str, Any]:
    env = EventEnvelope()
    env.event_id = new_event_id()
    env.event_type = event_name
    env.source = "rig_relay.desktop.websocket_server"
    env.producer = "bridge"
    env.correlation_id = correlation_id
    env.causation_id = ""
    env.trace_id = trace_id
    env.span_id = span_id
    env.sequence = sequence
    env.subject = handshake_id
    env.payload_schema = "rig.bridge.lifecycle.v1"
    env.sensitivity_class = EventSensitivityClass.INTERNAL_OPERATIONAL
    env.redaction_status = EventRedactionStatus.PASSED
    env.content_light = True

    env.payload = {
        "handshake_id": handshake_id,
        "backend_session_id": backend_session_id,
        "bridge_runtime_state": bridge_runtime_state,
        "idle_sequence": idle_sequence,
        **(details or {}),
    }
    env.finalize()
    return env.as_dict()


__all__ = ["bridge_event_from_lifecycle"]
