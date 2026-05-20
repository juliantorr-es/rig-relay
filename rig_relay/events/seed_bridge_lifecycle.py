from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rig_relay.events.envelope import (
    EventEnvelope,
    EventRedactionStatus,
    EventSensitivityClass,
    new_event_id,
)

_SEED_PATH = (
    Path(__file__).resolve().parents[2]
    / ".build"
    / "rig-relay"
    / "events"
    / "seeded_bridge_lifecycle.v1.jsonl"
)


def _build_event(
    event_type: str,
    sequence: int,
    occurred_at: str,
    correlation_id: str,
    causation_id: str,
    producer: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    env = EventEnvelope()
    env.event_id = new_event_id()
    env.event_type = event_type
    env.source = "rig_relay.desktop.websocket_server"
    env.occurred_at = occurred_at
    env.producer = producer
    env.correlation_id = correlation_id
    env.causation_id = causation_id
    env.sequence = sequence
    env.subject = "handshake_seeded_001"
    env.payload_schema = "rig.bridge.lifecycle.v1"
    env.sensitivity_class = EventSensitivityClass.INTERNAL_OPERATIONAL
    env.redaction_status = EventRedactionStatus.PASSED
    env.content_light = True
    env.payload = payload
    env.finalize()
    return env.as_dict()


def build_seed_events(*, seed_output_path: Path | None = None) -> dict[str, Any]:
    correlation_id = "corr_seeded_mission_001"

    timeline = [
        (
            "bridge.connection.begin",
            1,
            "2026-05-20T10:00:00Z",
            0,
            "bridge",
            {"handshake_id": "seeded_001", "state": "connecting"},
        ),
        (
            "bridge.auth.succeeded",
            2,
            "2026-05-20T10:00:01Z",
            1,
            "bridge",
            {"handshake_id": "seeded_001", "auth_method": "token"},
        ),
        (
            "bridge.backend_loop.started",
            3,
            "2026-05-20T10:00:02Z",
            2,
            "bridge",
            {"handshake_id": "seeded_001", "loop_type": "idle_projection"},
        ),
        (
            "bridge.status.updated",
            4,
            "2026-05-20T10:00:10Z",
            3,
            "bridge",
            {"runtime_state": "ready", "idle_sequence": 0},
        ),
        (
            "bridge.first_status.sent",
            5,
            "2026-05-20T10:00:10Z",
            4,
            "bridge",
            {"handshake_id": "seeded_001"},
        ),
        (
            "projection.content.requested",
            6,
            "2026-05-20T10:00:11Z",
            5,
            "projection",
            {"requested_by": "frontend_001"},
        ),
        (
            "projection.content.sent",
            7,
            "2026-05-20T10:00:12Z",
            6,
            "projection",
            {"digest": "sha256:0000aaaa", "sequence": 1},
        ),
        (
            "bridge.status.updated",
            8,
            "2026-05-20T10:00:20Z",
            0,
            "bridge",
            {"runtime_state": "idle", "idle_sequence": 1},
        ),
        (
            "bridge.heartbeat.sent",
            9,
            "2026-05-20T10:00:30Z",
            0,
            "bridge",
            {"handshake_id": "seeded_001"},
        ),
        (
            "bridge.status.updated",
            10,
            "2026-05-20T10:00:30Z",
            0,
            "bridge",
            {"runtime_state": "idle", "idle_sequence": 2},
        ),
        (
            "projection.unchanged_for_interval",
            11,
            "2026-05-20T10:00:40Z",
            0,
            "projection",
            {"intervals_unchanged": 1, "current_cadence_ms": 10000},
        ),
        (
            "bridge.heartbeat.sent",
            12,
            "2026-05-20T10:00:45Z",
            0,
            "bridge",
            {"handshake_id": "seeded_001"},
        ),
        (
            "resource_projection.snapshot.generated",
            13,
            "2026-05-20T10:00:50Z",
            0,
            "resource",
            {"bridge_health": "idle", "pressure": "none"},
        ),
        (
            "bridge.disconnect",
            14,
            "2026-05-20T10:01:00Z",
            0,
            "bridge",
            {"reason": "transport_closed", "close_code": 1006},
        ),
        (
            "bridge.backend_loop.stopped",
            15,
            "2026-05-20T10:01:01Z",
            14,
            "bridge",
            {"reason": "connection_closed"},
        ),
        (
            "bridge.reconnect.attempt",
            16,
            "2026-05-20T10:01:05Z",
            15,
            "bridge",
            {"attempt": 1, "backoff_ms": 1000},
        ),
        (
            "bridge.connection.begin",
            17,
            "2026-05-20T10:01:06Z",
            16,
            "bridge",
            {"handshake_id": "seeded_001", "state": "reconnecting"},
        ),
        (
            "bridge.auth.succeeded",
            18,
            "2026-05-20T10:01:07Z",
            17,
            "bridge",
            {"handshake_id": "seeded_001"},
        ),
        (
            "bridge.backend_loop.started",
            19,
            "2026-05-20T10:01:08Z",
            18,
            "bridge",
            {"handshake_id": "seeded_001"},
        ),
        (
            "bridge.status.updated",
            20,
            "2026-05-20T10:01:10Z",
            19,
            "bridge",
            {"runtime_state": "ready", "idle_sequence": 0},
        ),
        (
            "projection.content.sent",
            21,
            "2026-05-20T10:01:11Z",
            20,
            "projection",
            {"digest": "sha256:1111bbbb", "sequence": 2},
        ),
        (
            "resource_projection.snapshot.generated",
            22,
            "2026-05-20T10:01:15Z",
            0,
            "resource",
            {"bridge_health": "ready", "pressure": "none"},
        ),
        (
            "event_fabric.consumer_error.detected",
            23,
            "2026-05-20T10:02:00Z",
            0,
            "resource",
            {"consumer": "dispatcher", "error_count": 1},
        ),
        (
            "resource.consumer_pressure.updated",
            24,
            "2026-05-20T10:02:01Z",
            23,
            "resource",
            {"consumer_errors": 1, "severity": "elevated"},
        ),
        (
            "bridge.projection_loop.error",
            25,
            "2026-05-20T10:02:30Z",
            0,
            "bridge",
            {"error": "projection_timeout", "duration_ms": 15000},
        ),
    ]

    event_ids: list[str] = []
    events: list[dict[str, Any]] = []
    for event_type, seq, ts, parent_idx, producer_label, payload in timeline:
        causation_id = ""
        if (
            isinstance(parent_idx, int)
            and parent_idx > 0
            and parent_idx <= len(event_ids)
        ):
            causation_id = event_ids[parent_idx - 1]
        event = _build_event(
            event_type=event_type,
            sequence=seq,
            occurred_at=ts,
            correlation_id=correlation_id,
            causation_id=causation_id,
            producer=producer_label,
            payload=payload,
        )
        events.append(event)
        event_ids.append(event["event_id"])

    output_path = seed_output_path or _SEED_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        for event in events:
            f.write(json.dumps(event, sort_keys=True) + "\n")

    return {
        "seed_event_log_path": str(output_path),
        "event_count": len(events),
        "event_types": sorted({e["event_type"] for e in events}),
        "correlation_id": correlation_id,
        "causation_links": sum(1 for e in events if e.get("causation_id")),
    }


__all__ = ["build_seed_events"]
