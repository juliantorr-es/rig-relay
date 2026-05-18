from __future__ import annotations

from pathlib import Path

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend" / "desktop" / "js"
PROTOCOL_DIR = FRONTEND_DIR / "protocol"


def _read_protocol(name: str) -> str:
    return (PROTOCOL_DIR / name).read_text(encoding="utf-8")


# ── Module existence ───────────────────────────────────────────────


def test_envelope_js_exists():
    assert PROTOCOL_DIR.joinpath("envelope.js").exists()


def test_client_js_exists():
    assert PROTOCOL_DIR.joinpath("client.js").exists()


def test_flow_control_js_exists():
    assert PROTOCOL_DIR.joinpath("flowControl.js").exists()


# ── Envelope module ────────────────────────────────────────────────


def test_envelope_exports_build_function():
    source = _read_protocol("envelope.js")
    assert (
        "function buildEnvelope" in source or "export function buildEnvelope" in source
    )


def test_envelope_exports_parse_function():
    source = _read_protocol("envelope.js")
    assert (
        "function parseEnvelope" in source or "export function parseEnvelope" in source
    )


def test_envelope_exports_is_envelope():
    source = _read_protocol("envelope.js")
    assert "function isEnvelope" in source or "export function isEnvelope" in source


def test_envelope_exports_kind_matchers():
    source = _read_protocol("envelope.js")
    assert "isIntentAck" in source
    assert "isProjection" in source
    assert "isHeartbeat" in source


def test_envelope_exports_is_intent_result():
    source = _read_protocol("envelope.js")
    assert "isIntentResult" in source


def test_envelope_exports_is_flow_control():
    source = _read_protocol("envelope.js")
    assert "isFlowControl" in source


def test_envelope_exports_is_protocol_error():
    source = _read_protocol("envelope.js")
    assert "isProtocolError" in source


def test_envelope_includes_all_required_fields():
    source = _read_protocol("envelope.js")
    required = [
        "schema_version",
        "message_id",
        "handshake_id",
        "kind",
        "sequence",
        "created_at",
        "payload",
    ]
    for field in required:
        assert field in source, f"Envelope must include field: {field}"


def test_envelope_has_schema_version_constant():
    source = _read_protocol("envelope.js")
    assert "rig.relay.bridge_message.v1" in source


def test_envelope_exports_schema_version():
    source = _read_protocol("envelope.js")
    assert "export { SCHEMA_VERSION" in source


def test_envelope_exports_direction():
    source = _read_protocol("envelope.js")
    assert "export { SCHEMA_VERSION, DIRECTION, KIND" in source


def test_envelope_has_direction_enum():
    source = _read_protocol("envelope.js")
    assert "FRONTEND_TO_BACKEND" in source
    assert "BACKEND_TO_FRONTEND" in source


def test_envelope_has_kind_enum():
    source = _read_protocol("envelope.js")
    for kind in [
        "PROJECTION",
        "INTENT_REQUEST",
        "INTENT_ACK",
        "INTENT_RESULT",
        "LIFECYCLE_EVENT",
        "NOTIFICATION",
        "ERROR",
        "HEARTBEAT",
        "FLOW_CONTROL",
    ]:
        assert kind in source, f"Envelope KIND must contain: {kind}"


def test_envelope_build_includes_redaction_status():
    source = _read_protocol("envelope.js")
    assert "redaction_status" in source
    assert "content_light" in source


def test_envelope_build_includes_safe_summary():
    source = _read_protocol("envelope.js")
    assert "safe_summary" in source


def test_envelope_build_includes_priority():
    source = _read_protocol("envelope.js")
    assert "priority" in source


def test_envelope_parse_maps_snake_to_camel():
    source = _read_protocol("envelope.js")
    assert "messageId" in source
    assert "handshakeId" in source
    assert "createdAt" in source


def test_envelope_new_message_id_uses_msg_prefix():
    source = _read_protocol("envelope.js")
    assert "msg_" in source


def test_envelope_object_freeze():
    source = _read_protocol("envelope.js")
    assert "Object.freeze" in source


# ── Client module ──────────────────────────────────────────────────


def test_client_exports_create_function():
    source = _read_protocol("client.js")
    assert (
        "function createProtocolClient" in source
        or "export function createProtocolClient" in source
    )


def test_client_sends_intent_request():
    source = _read_protocol("client.js")
    assert "sendIntentRequest" in source


def test_client_sends_heartbeat():
    source = _read_protocol("client.js")
    assert "sendHeartbeat" in source


def test_client_sends_lifecycle_event():
    source = _read_protocol("client.js")
    assert "sendLifecycleEvent" in source


def test_client_sends_projection_rendered_ack():
    source = _read_protocol("client.js")
    assert "sendProjectionRenderedAck" in source


def test_client_handles_messages():
    source = _read_protocol("client.js")
    assert "function handleMessage" in source or "handleMessage" in source


def test_client_has_sequence_tracking():
    source = _read_protocol("client.js")
    assert "_outboundSeq" in source
    assert "_inboundSeq" in source


def test_client_has_dedup():
    source = _read_protocol("client.js")
    assert "_isDuplicateMessageId" in source or "duplicate" in source
    assert "_seenMessageIds" in source


def test_client_staleness_check():
    source = _read_protocol("client.js")
    assert "_checkStaleProjection" in source
    assert "_lastProjectionSeq" in source


def test_client_exports_stats():
    source = _read_protocol("client.js")
    assert "function getStats" in source or "getStats" in source


def test_client_exports_destroy():
    source = _read_protocol("client.js")
    assert "function destroy" in source or "destroy" in source


def test_client_exports_set_handshake_id():
    source = _read_protocol("client.js")
    assert "setHandshakeId" in source


def test_client_exports_set_ws_client():
    source = _read_protocol("client.js")
    assert "setWsClient" in source


def test_client_has_idempotency_tracking():
    source = _read_protocol("client.js")
    assert "_seenIdempotencyKeys" in source


def test_client_has_message_count_by_kind():
    source = _read_protocol("client.js")
    assert "_messageCountByKind" in source


def test_client_has_dropped_count():
    source = _read_protocol("client.js")
    assert "_droppedCount" in source


def test_client_has_coalesced_count():
    source = _read_protocol("client.js")
    assert "_coalescedCount" in source


def test_client_has_max_queue_depth():
    source = _read_protocol("client.js")
    assert "_maxQueueDepth" in source


def test_client_has_protocol_error_count():
    source = _read_protocol("client.js")
    assert "_protocolErrorCount" in source


def test_client_stats_returns_all_counters():
    source = _read_protocol("client.js")
    for field in [
        "outboundSeq",
        "inboundSeq",
        "lastProjectionSeq",
        "duplicateCount",
        "staleProjectionCount",
        "protocolErrorCount",
        "droppedCount",
        "coalescedCount",
        "maxQueueDepth",
        "messageCountByKind",
    ]:
        assert field in source, f"Stats must include: {field}"


def test_client_imports_from_envelope():
    source = _read_protocol("client.js")
    assert "from './envelope.js'" in source


def test_client_imports_telemetry():
    source = _read_protocol("client.js")
    assert "from '../telemetry/frontendTrace.js'" in source


def test_client_send_envelope_uses_sequence():
    source = _read_protocol("client.js")
    assert "_nextSeq" in source


def test_client_dispatch_all_kinds():
    source = _read_protocol("client.js")
    assert "KIND.PROJECTION" in source
    assert "KIND.INTENT_ACK" in source
    assert "KIND.INTENT_RESULT" in source
    assert "KIND.HEARTBEAT" in source
    assert "KIND.FLOW_CONTROL" in source
    assert "KIND.ERROR" in source


def test_client_destroy_nulls_ws_client():
    source = _read_protocol("client.js")
    assert "wsClient = null" in source


def test_client_destroy_clears_seen_message_ids():
    source = _read_protocol("client.js")
    assert "_seenMessageIds = Object.create(null)" in source


def test_client_destroy_clears_idempotency_keys():
    source = _read_protocol("client.js")
    assert "_seenIdempotencyKeys = Object.create(null)" in source


# ── Flow control module ────────────────────────────────────────────


def test_flow_control_exports_create():
    source = _read_protocol("flowControl.js")
    assert (
        "function createFlowController" in source
        or "export function createFlowController" in source
    )


def test_flow_control_has_max_queue():
    source = _read_protocol("flowControl.js")
    assert "MAX_QUEUE_SIZE" in source or "128" in source


def test_flow_control_max_queue_is_128():
    source = _read_protocol("flowControl.js")
    assert "MAX_QUEUE_SIZE = 128" in source


def test_flow_control_never_drops_error():
    source = _read_protocol("flowControl.js")
    assert "NEVER_DROP" in source
    assert "KIND.ERROR" in source


def test_flow_control_never_drops_intent_result():
    source = _read_protocol("flowControl.js")
    assert "NEVER_DROP" in source
    assert "KIND.INTENT_RESULT" in source


def test_flow_control_coalesces_lifecycle():
    source = _read_protocol("flowControl.js")
    assert "COALESCE_KINDS" in source
    assert "KIND.LIFECYCLE_EVENT" in source or "LIFECYCLE_EVENT" in source


def test_flow_control_coalesces_heartbeat():
    source = _read_protocol("flowControl.js")
    assert "COALESCE_KINDS" in source
    assert "KIND.HEARTBEAT" in source or "HEARTBEAT" in source


def test_flow_control_has_priority_order():
    source = _read_protocol("flowControl.js")
    assert "PRIORITY_ORDER" in source


def test_flow_control_priority_order_values():
    source = _read_protocol("flowControl.js")
    assert "critical" in source
    assert "high" in source
    assert "normal" in source
    assert "low" in source


def test_flow_control_enqueue_method():
    source = _read_protocol("flowControl.js")
    assert "function enqueue" in source or "enqueue" in source


def test_flow_control_flush_method():
    source = _read_protocol("flowControl.js")
    assert "function flush" in source or "flush" in source


def test_flow_control_get_stats_method():
    source = _read_protocol("flowControl.js")
    assert "function getStats" in source or "getStats" in source


def test_flow_control_set_send_fn_method():
    source = _read_protocol("flowControl.js")
    assert "function setSendFn" in source or "setSendFn" in source


def test_flow_control_has_dropped_count():
    source = _read_protocol("flowControl.js")
    assert "_droppedCount" in source


def test_flow_control_has_coalesced_count():
    source = _read_protocol("flowControl.js")
    assert "_coalescedCount" in source


def test_flow_control_has_max_queue_depth():
    source = _read_protocol("flowControl.js")
    assert "_maxQueueDepth" in source


def test_flow_control_stats_returns_all_fields():
    source = _read_protocol("flowControl.js")
    for field in ["queueDepth", "maxQueueDepth", "droppedCount", "coalescedCount"]:
        assert field in source, f"Flow control stats must include: {field}"


def test_flow_control_imports_from_envelope():
    source = _read_protocol("flowControl.js")
    assert "from './envelope.js'" in source


def test_flow_control_imports_telemetry():
    source = _read_protocol("flowControl.js")
    assert "from '../telemetry/frontendTrace.js'" in source


def test_flow_control_object_freeze():
    source = _read_protocol("flowControl.js")
    assert "Object.freeze" in source


# ── No secrets ─────────────────────────────────────────────────────


def test_envelope_js_no_secrets():
    source = _read_protocol("envelope.js")
    for secret in ["sk-", "api_key", "password", "auth_token"]:
        assert secret not in source, f"envelope.js must not contain {secret}"
    assert source.count("secret") <= 2, (
        "envelope.js must not contain secret outside safety comment"
    )


def test_client_js_no_secrets():
    source = _read_protocol("client.js")
    for secret in ["sk-", "api_key", "password", "auth_token"]:
        assert secret not in source, f"client.js must not contain {secret}"


def test_flow_control_js_no_secrets():
    source = _read_protocol("flowControl.js")
    for secret in ["sk-", "api_key", "password", "auth_token"]:
        assert secret not in source, f"flowControl.js must not contain {secret}"
    assert source.count("secret") <= 1, (
        "flowControl.js must not contain secret outside safety comment"
    )


# ── String-search edge cases ───────────────────────────────────────


def test_envelope_comment_blocks_reflect_source():
    source = _read_protocol("envelope.js")
    assert "Rig Relay" in source
    assert "Bridge Protocol Envelope" in source


def test_client_comment_blocks_reflect_source():
    source = _read_protocol("client.js")
    assert "Rig Relay" in source
    assert "Bridge Protocol Client" in source


def test_flow_control_comment_blocks_reflect_source():
    source = _read_protocol("flowControl.js")
    assert "Rig Relay" in source
    assert "Bridge Protocol Flow Control" in source
