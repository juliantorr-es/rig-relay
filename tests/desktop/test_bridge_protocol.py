from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from rig_relay.desktop.bridge_protocol import (
    CRITICAL_KINDS,
    HIGH_KINDS,
    LOW_KINDS,
    BridgeMessage,
    BridgeMessageDirection,
    BridgeMessageKind,
    BridgeMessagePriority,
    ProtocolTracker,
    _default_priority,
)

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas"


# ── Schema validation ───────────────────────────────────────────────


def test_schema_exists():
    schema_path = SCHEMA_DIR / "rig.relay.bridge_message.v1.schema.json"
    assert schema_path.exists(), "Bridge message schema must exist"


def test_schema_is_valid_json():
    schema_path = SCHEMA_DIR / "rig.relay.bridge_message.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["$id"] == "https://json-schema.org/rig.relay.bridge_message.v1"


def test_schema_has_required_fields():
    schema_path = SCHEMA_DIR / "rig.relay.bridge_message.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    required = schema["required"]
    for field in [
        "schema_version",
        "message_id",
        "handshake_id",
        "direction",
        "kind",
        "sequence",
        "created_at",
        "payload",
    ]:
        assert field in required, f"Schema must require field: {field}"


def test_schema_constrains_schema_version():
    schema_path = SCHEMA_DIR / "rig.relay.bridge_message.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert (
        schema["properties"]["schema_version"]["const"] == "rig.relay.bridge_message.v1"
    )


def test_schema_forbids_additional_properties():
    schema_path = SCHEMA_DIR / "rig.relay.bridge_message.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    assert schema["additionalProperties"] is False


def test_schema_has_all_kinds():
    schema_path = SCHEMA_DIR / "rig.relay.bridge_message.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    kind_enum = schema["properties"]["kind"]["enum"]
    for kind in BridgeMessageKind:
        assert kind.value in kind_enum, f"Schema must include kind: {kind.value}"


def test_schema_message_id_pattern_matches_implementation():
    schema_path = SCHEMA_DIR / "rig.relay.bridge_message.v1.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    pattern = schema["properties"]["message_id"]["pattern"]
    assert pattern == "^msg_[a-f0-9]{12,}$"


# ── BridgeMessage model ─────────────────────────────────────────────


def test_valid_envelope_accepted():
    msg = BridgeMessage(
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=1,
        payload={"data": {}},
    )
    assert msg.schema_version == "rig.relay.bridge_message.v1"
    assert msg.message_id.startswith("msg_")
    assert msg.direction == BridgeMessageDirection.BACKEND_TO_FRONTEND


def test_schema_version_defaults_correctly():
    msg = BridgeMessage(
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=1,
        payload={},
    )
    assert msg.schema_version == "rig.relay.bridge_message.v1"


def test_schema_version_not_validated_by_model():
    msg = BridgeMessage(
        schema_version="rig.relay.bridge_message.v99",
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=1,
        payload={},
    )
    assert msg.schema_version == "rig.relay.bridge_message.v99"


def test_unknown_kind_rejected():
    with pytest.raises(ValidationError):
        BridgeMessage.model_validate({
            "direction": BridgeMessageDirection.BACKEND_TO_FRONTEND.value,
            "kind": "unknown_kind",
            "sequence": 1,
            "payload": {},
        })


def test_message_id_auto_generated():
    msg = BridgeMessage(
        direction=BridgeMessageDirection.FRONTEND_TO_BACKEND,
        kind=BridgeMessageKind.INTENT_REQUEST,
        sequence=1,
        payload={},
    )
    assert msg.message_id
    assert msg.message_id.startswith("msg_")


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        BridgeMessage.model_validate({
            "direction": BridgeMessageDirection.BACKEND_TO_FRONTEND.value,
            "kind": BridgeMessageKind.PROJECTION.value,
            "sequence": 1,
            "payload": {},
            "bogus_field": "should_fail",
        })


def test_payload_accepts_dict():
    msg = BridgeMessage(
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=1,
        payload={"some": "data"},
    )
    assert msg.payload == {"some": "data"}


def test_payload_defaults_to_empty_dict():
    msg = BridgeMessage(
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=1,
    )
    assert msg.payload == {}


def test_direction_enum_values():
    msg_fe = BridgeMessage(
        direction=BridgeMessageDirection.FRONTEND_TO_BACKEND,
        kind=BridgeMessageKind.INTENT_REQUEST,
        sequence=1,
        payload={},
    )
    assert msg_fe.direction == BridgeMessageDirection.FRONTEND_TO_BACKEND
    msg_be = BridgeMessage(
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=1,
        payload={},
    )
    assert msg_be.direction == BridgeMessageDirection.BACKEND_TO_FRONTEND


def test_model_is_frozen():
    msg = BridgeMessage(
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=1,
        payload={},
    )
    with pytest.raises(ValidationError):
        msg.payload = {"modified": True}


def test_sequence_must_be_non_negative():
    msg = BridgeMessage(
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=0,
        payload={},
    )
    assert msg.sequence == 0
    with pytest.raises(ValidationError):
        BridgeMessage(
            direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
            kind=BridgeMessageKind.PROJECTION,
            sequence=-1,
            payload={},
        )


# ── Priority assignment ─────────────────────────────────────────────


def test_error_is_critical():
    assert "error" in CRITICAL_KINDS


def test_intent_request_is_high():
    assert "intent_request" in HIGH_KINDS


def test_intent_ack_is_high():
    assert "intent_ack" in HIGH_KINDS


def test_intent_result_is_high():
    assert "intent_result" in HIGH_KINDS


def test_lifecycle_event_is_low():
    assert "lifecycle_event" in LOW_KINDS


def test_notification_is_low():
    assert "notification" in LOW_KINDS


def test_heartbeat_is_low():
    assert "heartbeat" in LOW_KINDS


def test_default_priority_error():
    p = _default_priority(BridgeMessageKind.ERROR)
    assert p == BridgeMessagePriority.CRITICAL


def test_default_priority_intent_request():
    p = _default_priority(BridgeMessageKind.INTENT_REQUEST)
    assert p == BridgeMessagePriority.HIGH


def test_default_priority_intent_ack():
    p = _default_priority(BridgeMessageKind.INTENT_ACK)
    assert p == BridgeMessagePriority.HIGH


def test_default_priority_intent_result():
    p = _default_priority(BridgeMessageKind.INTENT_RESULT)
    assert p == BridgeMessagePriority.HIGH


def test_default_priority_lifecycle():
    p = _default_priority(BridgeMessageKind.LIFECYCLE_EVENT)
    assert p == BridgeMessagePriority.LOW


def test_default_priority_projection():
    p = _default_priority(BridgeMessageKind.PROJECTION)
    assert p == BridgeMessagePriority.NORMAL


def test_default_priority_flow_control():
    p = _default_priority(BridgeMessageKind.FLOW_CONTROL)
    assert p == BridgeMessagePriority.NORMAL


def test_default_priority_accepts_string():
    p = _default_priority("error")
    assert p == BridgeMessagePriority.CRITICAL
    p = _default_priority("projection")
    assert p == BridgeMessagePriority.NORMAL


# ── ProtocolTracker ─────────────────────────────────────────────────


def test_tracker_outbound_seq_increments():
    tracker = ProtocolTracker("corr_test")
    assert tracker.next_outbound_seq() == 1
    assert tracker.next_outbound_seq() == 2
    assert tracker.next_outbound_seq() == 3


def test_tracker_outbound_seq_starts_at_zero_then_one():
    tracker = ProtocolTracker("corr_test")
    assert tracker.next_outbound_seq() == 1


def test_tracker_inbound_seq_tracks_newer():
    tracker = ProtocolTracker("corr_test")
    assert tracker.check_inbound_seq(1)
    assert not tracker.check_inbound_seq(1)  # stale
    assert tracker.check_inbound_seq(5)
    assert not tracker.check_inbound_seq(3)  # stale


def test_tracker_inbound_seq_initially_rejects_zero():
    tracker = ProtocolTracker("corr_test")
    assert tracker.check_inbound_seq(0)
    assert not tracker.check_inbound_seq(0)  # stale after seeing 0


def test_tracker_detects_duplicate_message_id():
    tracker = ProtocolTracker("corr_test")
    assert not tracker.is_duplicate_message("msg_aaa")
    assert tracker.is_duplicate_message("msg_aaa")
    assert tracker._duplicate_count == 1


def test_tracker_duplicate_message_id_increments_count():
    tracker = ProtocolTracker("corr_test")
    tracker.is_duplicate_message("msg_bbb")
    assert tracker.is_duplicate_message("msg_bbb")
    assert tracker._duplicate_count == 1
    tracker.is_duplicate_message("msg_ccc")
    tracker.is_duplicate_message("msg_ccc")
    assert tracker._duplicate_count == 2


def test_tracker_detects_duplicate_idempotency_key():
    tracker = ProtocolTracker("corr_test")
    assert not tracker.is_duplicate_idempotency("idem_xyz")
    assert tracker.is_duplicate_idempotency("idem_xyz")


def test_tracker_idempotency_empty_key_skipped():
    tracker = ProtocolTracker("corr_test")
    assert not tracker.is_duplicate_idempotency("")
    assert not tracker.is_duplicate_idempotency("")


def test_tracker_projection_sequence_stale():
    tracker = ProtocolTracker("corr_test")
    assert tracker.check_projection_sequence(10)
    assert not tracker.check_projection_sequence(5)  # stale
    assert tracker._stale_projection_count == 1
    assert tracker.check_projection_sequence(15)
    assert tracker._stale_projection_count == 1


def test_tracker_projection_sequence_accepts_equal():
    tracker = ProtocolTracker("corr_test")
    assert tracker.check_projection_sequence(10)
    assert not tracker.check_projection_sequence(10)  # equal is stale
    assert tracker._stale_projection_count == 1


def test_tracker_records_kind():
    tracker = ProtocolTracker("corr_test")
    tracker.record_kind("projection")
    tracker.record_kind("projection")
    tracker.record_kind("intent_request")
    assert tracker._message_count_by_kind["projection"] == 2
    assert tracker._message_count_by_kind["intent_request"] == 1


def test_tracker_snapshot_has_all_fields():
    tracker = ProtocolTracker("corr_test")
    tracker.next_outbound_seq()
    tracker.check_inbound_seq(1)
    snap = tracker.snapshot()
    assert snap["handshake_id"] == "corr_test"
    assert snap["outbound_seq"] == 1
    assert snap["inbound_seq"] == 1
    assert "message_count_by_kind" in snap
    assert "duplicate_count" in snap
    assert "stale_projection_count" in snap
    assert "dropped_count" in snap
    assert "coalesced_count" in snap
    assert "max_queue_depth" in snap
    assert "protocol_error_count" in snap
    assert "heartbeat_age_sec" in snap


def test_tracker_snapshot_message_counts_are_copied():
    tracker = ProtocolTracker("corr_test")
    tracker.record_kind("projection")
    snap = tracker.snapshot()
    assert snap["message_count_by_kind"]["projection"] == 1
    # Mutating snapshot dict should not affect tracker internals
    snap["message_count_by_kind"]["projection"] = 999
    assert tracker._message_count_by_kind["projection"] == 1


def test_tracker_heartbeat_recording():
    tracker = ProtocolTracker("corr_test")
    initial = tracker.heartbeat_age_sec()
    tracker.record_heartbeat()
    assert tracker.heartbeat_age_sec() < initial + 1


def test_tracker_intent_ack_latency():
    tracker = ProtocolTracker("corr_test")
    tracker.record_ack_sent("intent_123")
    latency = tracker.record_ack_latency("intent_123")
    assert latency is not None
    assert latency >= 0


def test_tracker_intent_ack_latency_unknown_intent():
    tracker = ProtocolTracker("corr_test")
    latency = tracker.record_ack_latency("nonexistent")
    assert latency is None


def test_tracker_record_dropped():
    tracker = ProtocolTracker("corr_test")
    tracker.record_dropped()
    assert tracker._dropped_count == 1
    tracker.record_dropped(3)
    assert tracker._dropped_count == 4


def test_tracker_record_coalesced():
    tracker = ProtocolTracker("corr_test")
    tracker.record_coalesced()
    assert tracker._coalesced_count == 1
    tracker.record_coalesced(2)
    assert tracker._coalesced_count == 3


def test_tracker_record_queue_depth():
    tracker = ProtocolTracker("corr_test")
    tracker.record_queue_depth(5)
    assert tracker._max_queue_depth == 5
    tracker.record_queue_depth(3)
    assert tracker._max_queue_depth == 5
    tracker.record_queue_depth(10)
    assert tracker._max_queue_depth == 10


def test_tracker_record_protocol_error():
    tracker = ProtocolTracker("corr_test")
    assert tracker._protocol_error_count == 0
    tracker.record_protocol_error()
    assert tracker._protocol_error_count == 1
    tracker.record_protocol_error()
    assert tracker._protocol_error_count == 2


# ── Envelope no-secret check ────────────────────────────────────────


def test_envelope_no_token_in_message_id():
    msg = BridgeMessage(
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=1,
        payload={"data": {"status": "ok", "token": "sk-secret"}},
    )
    dumped = msg.model_dump()
    assert "sk-secret" not in dumped.get("message_id", "")
    assert "secret" not in dumped.get("message_id", "").lower()


def test_envelope_payload_is_not_scrubbed_by_model():
    msg = BridgeMessage(
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=1,
        payload={"token": "sk-secret"},
    )
    assert msg.payload["token"] == "sk-secret"


def test_envelope_redaction_status_is_content_light():
    msg = BridgeMessage(
        direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
        kind=BridgeMessageKind.PROJECTION,
        sequence=1,
        payload={},
    )
    assert msg.redaction_status == "content_light"


# ── All kinds are valid ─────────────────────────────────────────────


def test_all_kinds_constructable():
    for kind in BridgeMessageKind:
        msg = BridgeMessage(
            direction=BridgeMessageDirection.BACKEND_TO_FRONTEND,
            kind=kind,
            sequence=1,
            payload={},
        )
        assert msg.kind == kind


def test_bridge_message_kind_count():
    assert len(BridgeMessageKind) == 9


def test_bridge_message_priority_count():
    assert len(BridgeMessagePriority) == 4


def test_bridge_message_direction_count():
    assert len(BridgeMessageDirection) == 2


def test_no_overlap_between_priority_sets():
    all_kinds = {k.value for k in BridgeMessageKind}
    critical = set(CRITICAL_KINDS)
    high = set(HIGH_KINDS)
    low = set(LOW_KINDS)
    assert critical & high == set()
    assert critical & low == set()
    assert high & low == set()
    assigned = critical | high | low
    unassigned = all_kinds - assigned
    assert unassigned == {"projection", "flow_control"}
