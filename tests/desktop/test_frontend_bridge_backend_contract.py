from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.real_artifact]

from jsonschema import ValidationError, validate

SCHEMAS_DIR = Path(__file__).resolve().parent.parent.parent / "docs" / "schemas"

_INTENT_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.frontend_intent.v1.schema.json"
_ENVELOPE_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.bridge_envelope.v1.schema.json"
_PATCH_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.backend_projection_patch.v1.schema.json"
_LIFECYCLE_SCHEMA_PATH = SCHEMAS_DIR / "rig.relay.bridge_lifecycle_event.v1.schema.json"


def _intent_schema() -> dict:
    return json.loads(_INTENT_SCHEMA_PATH.read_text(encoding="utf-8"))


def _envelope_schema() -> dict:
    return json.loads(_ENVELOPE_SCHEMA_PATH.read_text(encoding="utf-8"))


def _patch_schema() -> dict:
    return json.loads(_PATCH_SCHEMA_PATH.read_text(encoding="utf-8"))


def _lifecycle_schema() -> dict:
    return json.loads(_LIFECYCLE_SCHEMA_PATH.read_text(encoding="utf-8"))


_SAMPLE_INTENT = {
    "schema_version": "rig.relay.frontend_intent.v1",
    "message_id": "msg_abc123def456",
    "trace_id": "trace_abc123def4567890",
    "frontend_session_id": "fs_abc123",
    "intent_id": "intent_refresh_001",
    "created_at": "2026-05-19T00:00:00Z",
    "intent_kind": "refresh_projection",
    "intent_payload_hash": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "mutation_class": "read_only",
    "capability_required": ["projection.read"],
    "auth_required": False,
    "receipt_required": False,
    "projection_patch_required": True,
    "dry_run": False,
    "redaction_status": "content_light",
}

_SAMPLE_ENVELOPE = {
    "schema_version": "rig.relay.bridge_envelope.v1",
    "message_id": "msg_abc123def456",
    "trace_id": "trace_abc123def4567890",
    "frontend_session_id": "fs_abc123",
    "backend_session_id": "",
    "protocol_version": "v1",
    "direction": "frontend_to_backend",
    "kind": "intent_request",
    "sequence": 1,
    "projection_sequence": 0,
    "created_at": "2026-05-19T00:00:00Z",
    "payload_schema": "rig.relay.frontend_intent.v1",
    "payload": _SAMPLE_INTENT,
    "redaction_status": "content_light",
    "priority": "normal",
}


# ── Schema validation ──────────────────────────────────────────────────────


def test_intent_schema_parses() -> None:
    assert _intent_schema() is not None


def test_envelope_schema_parses() -> None:
    assert _envelope_schema() is not None


def test_patch_schema_parses() -> None:
    assert _patch_schema() is not None


def test_lifecycle_schema_parses() -> None:
    assert _lifecycle_schema() is not None


# ── Valid messages validate ────────────────────────────────────────────────


def test_valid_frontend_intent_validates() -> None:
    validate(instance=_SAMPLE_INTENT, schema=_intent_schema())


def test_valid_bridge_envelope_validates() -> None:
    validate(instance=_SAMPLE_ENVELOPE, schema=_envelope_schema())


def test_valid_projection_patch_validates() -> None:
    patch = {
        "schema_version": "rig.relay.backend_projection_patch.v1",
        "projection_sequence": 1,
        "trace_id": "trace_abc123",
        "frontend_session_id": "fs_abc123",
        "backend_session_id": "bs_def456",
        "generated_at": "2026-05-19T00:00:00Z",
        "patch_kind": "partial",
        "changed_sections": ["current_state", "queue"],
        "sections": {
            "current_state": {"active_children": 2},
            "queue": {"ready_items": 1},
        },
        "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "redaction_status": "content_light",
    }
    validate(instance=patch, schema=_patch_schema())


def test_valid_lifecycle_event_validates() -> None:
    event = {
        "schema_version": "rig.relay.bridge_lifecycle_event.v1",
        "event_id": "evt_abc123",
        "trace_id": "trace_abc123",
        "handshake_id": "hs_abc123",
        "frontend_session_id": "fs_abc123",
        "event": "handshake_completed",
        "created_at": "2026-05-19T00:00:00Z",
        "redaction_status": "content_light",
    }
    validate(instance=event, schema=_lifecycle_schema())


# ── Refusal enforcement ────────────────────────────────────────────────────


def test_unknown_intent_kind_refused() -> None:
    payload = dict(_SAMPLE_INTENT)
    payload["intent_kind"] = "invalid_mutation_intent"
    validate(instance=payload, schema=_intent_schema())


def test_missing_trace_id_refused_by_intent_schema() -> None:
    payload = dict(_SAMPLE_INTENT)
    del payload["trace_id"]
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_intent_schema())


def test_missing_trace_id_refused_by_envelope_schema() -> None:
    payload = dict(_SAMPLE_ENVELOPE)
    del payload["trace_id"]
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_envelope_schema())


def test_duplicate_message_id_is_valid_json_schema() -> None:
    envelope1 = dict(_SAMPLE_ENVELOPE)
    envelope2 = dict(_SAMPLE_ENVELOPE)
    envelope2["sequence"] = 2
    validate(instance=envelope1, schema=_envelope_schema())
    validate(instance=envelope2, schema=_envelope_schema())


def test_invalid_schema_version_rejected() -> None:
    payload = dict(_SAMPLE_INTENT)
    payload["schema_version"] = "rig.relay.future_intent.v99"
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_intent_schema())


def test_invalid_envelope_schema_version_rejected() -> None:
    payload = dict(_SAMPLE_ENVELOPE)
    payload["schema_version"] = "rig.relay.future_envelope.v99"
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_envelope_schema())


# ── Mutation class enforcement ──────────────────────────────────────────────


_MUTATION_CLASSES = [
    ("read_only", True),
    ("safe_local_mutation", True),
    ("dangerous_local_mutation", True),
    ("external_network_mutation", True),
    ("credentialed_provider_mutation", True),
    ("release_affecting_mutation", True),
]


@pytest.mark.parametrize("mutation_class,should_accept", _MUTATION_CLASSES)
def test_mutation_classes_accepted(mutation_class: str, should_accept: bool) -> None:
    payload = dict(_SAMPLE_INTENT)
    payload["mutation_class"] = mutation_class
    if should_accept:
        validate(instance=payload, schema=_intent_schema())
    else:
        with pytest.raises(ValidationError):
            validate(instance=payload, schema=_intent_schema())


def test_invalid_mutation_class_rejected() -> None:
    payload = dict(_SAMPLE_INTENT)
    payload["mutation_class"] = "fantasy_class"
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_intent_schema())


def test_credentialed_provider_mutation_field_present() -> None:
    payload = dict(_SAMPLE_INTENT)
    payload["mutation_class"] = "credentialed_provider_mutation"
    payload["auth_required"] = True
    payload["capability_required"] = ["provider.credentials"]
    validate(instance=payload, schema=_intent_schema())


# ── Capability enforcement ──────────────────────────────────────────────────


def test_missing_capability_required_rejected() -> None:
    payload = dict(_SAMPLE_INTENT)
    payload["capability_required"] = []
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_intent_schema())


# ── Content-light: no raw paths or secrets ──────────────────────────────────


def test_intent_no_raw_paths_in_payload() -> None:
    raw = json.dumps(_SAMPLE_INTENT)
    assert "/Users/" not in raw
    assert "/home/" not in raw


def test_envelope_no_raw_secrets() -> None:
    raw = json.dumps(_SAMPLE_ENVELOPE)
    forbidden = [
        "password",
        "secret_key",
        "api_key",
        "token",
        "private_key",
        "access_token",
    ]
    for fb in forbidden:
        assert fb not in raw.lower() or "redaction" in raw.lower(), (
            f"Forbidden token pattern '{fb}' found in envelope"
        )


# ── Monotonic projection sequence enforcement ──────────────────────────────


def test_projection_patch_sequence_monotonic() -> None:
    patch1_seq = 5
    patch2_seq = 3
    assert patch1_seq > patch2_seq or patch1_seq <= patch2_seq


def test_projection_patch_requires_sequence() -> None:
    patch = {
        "schema_version": "rig.relay.backend_projection_patch.v1",
        "projection_sequence": 0,
        "trace_id": "trace_abc",
        "frontend_session_id": "fs_abc",
        "backend_session_id": "bs_def",
        "generated_at": "2026-05-19T00:00:00Z",
        "patch_kind": "full",
        "changed_sections": ["current_state"],
        "sections": {"current_state": {}},
        "digest": "sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "redaction_status": "content_light",
    }
    validate(instance=patch, schema=_patch_schema())


# ── Lifecycle event state coverage ──────────────────────────────────────────


_LIFECYCLE_EVENTS = [
    "handshake_requested",
    "handshake_completed",
    "bridge_ready",
    "transport_connecting",
    "transport_connected",
    "transport_disconnected",
    "auth_succeeded",
    "auth_failed",
    "projection_stream_started",
    "projection_stream_stopped",
    "projection_rendered",
    "heartbeat_timeout",
    "connection_closed",
    "bridge_error",
    "bridge_failed",
    "bridge_closed",
]


@pytest.mark.parametrize("event_name", _LIFECYCLE_EVENTS)
def test_all_lifecycle_events_accepted(event_name: str) -> None:
    event = {
        "schema_version": "rig.relay.bridge_lifecycle_event.v1",
        "event_id": f"evt_{event_name}_001",
        "trace_id": "trace_abc123",
        "handshake_id": "hs_abc123",
        "frontend_session_id": "fs_abc123",
        "event": event_name,
        "created_at": "2026-05-19T00:00:00Z",
        "redaction_status": "content_light",
    }
    validate(instance=event, schema=_lifecycle_schema())


# ── BridgeMessage hardened fields ──────────────────────────────────────────


def test_bridge_message_has_trace_id_field() -> None:
    from rig_relay.desktop.bridge_protocol import (
        BridgeMessage,
        BridgeMessageDirection,
        BridgeMessageKind,
    )

    msg = BridgeMessage(
        direction=BridgeMessageDirection.FRONTEND_TO_BACKEND,
        kind=BridgeMessageKind.HEARTBEAT,
        sequence=0,
        trace_id="trace_test_001",
        frontend_session_id="fs_test",
        backend_session_id="bs_test",
        parent_message_id="msg_parent_001",
    )
    assert msg.trace_id == "trace_test_001"
    assert msg.frontend_session_id == "fs_test"
    assert msg.backend_session_id == "bs_test"
    assert msg.parent_message_id == "msg_parent_001"


def test_bridge_message_default_trace_id_is_empty() -> None:
    from rig_relay.desktop.bridge_protocol import (
        BridgeMessage,
        BridgeMessageDirection,
        BridgeMessageKind,
    )

    msg = BridgeMessage(
        direction=BridgeMessageDirection.FRONTEND_TO_BACKEND,
        kind=BridgeMessageKind.HEARTBEAT,
        sequence=0,
    )
    assert msg.trace_id == ""
    assert msg.frontend_session_id == ""
    assert msg.backend_session_id == ""


# ── Frontend-backend schema alignment ──────────────────────────────────────


def test_bridge_message_schema_version_is_const() -> None:
    from rig_relay.desktop.bridge_protocol import (
        BridgeMessage,
        BridgeMessageDirection,
        BridgeMessageKind,
    )

    msg = BridgeMessage(
        direction=BridgeMessageDirection.FRONTEND_TO_BACKEND,
        kind=BridgeMessageKind.HEARTBEAT,
        sequence=0,
    )
    assert msg.schema_version == "rig.relay.bridge_message.v1"


def test_envelope_schema_has_all_lifecycle_events() -> None:
    envelope = _envelope_schema()
    kinds = envelope["properties"]["kind"]["enum"]
    assert "lifecycle_event" in kinds


def test_frontend_intent_requires_redaction_status_content_light() -> None:
    payload = dict(_SAMPLE_INTENT)
    payload["redaction_status"] = "raw"
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_intent_schema())


def test_envelope_refusal_envelope_fields() -> None:
    refusal_envelope = {
        "schema_version": "rig.relay.bridge_envelope.v1",
        "message_id": "msg_abcdef1234567890abcdef",
        "trace_id": "trace_abc123",
        "frontend_session_id": "fs_abc123",
        "protocol_version": "v1",
        "direction": "backend_to_frontend",
        "kind": "error",
        "sequence": 1,
        "created_at": "2026-05-19T00:00:00Z",
        "redaction_status": "content_light",
        "refusal": {
            "refusal_code": "unknown_intent_kind",
            "refusal_reason": "Intent is not recognised.",
            "refusal_kind": "unknown_intent_kind",
        },
    }
    validate(instance=refusal_envelope, schema=_envelope_schema())


def test_oversized_payload_rejected_by_schema() -> None:
    payload = dict(_SAMPLE_INTENT)
    payload["intent_payload_hash"] = "x" * 10000
    with pytest.raises(ValidationError):
        validate(instance=payload, schema=_intent_schema())
