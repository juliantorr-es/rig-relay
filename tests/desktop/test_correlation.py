from __future__ import annotations

from rig_relay.desktop.correlation import (
    DesktopCorrelation,
    hash_dict_payload,
    hash_message_payload,
    new_correlation_id,
    new_transport_session_id,
)
from rig_relay.tracing.recorder import TraceRecorder
from rig_relay.tracing.store import InMemoryTraceStore


def test_correlation_id_is_unique():
    ids = {new_correlation_id() for _ in range(100)}
    assert len(ids) == 100


def test_transport_session_id_is_unique():
    ids = {new_transport_session_id() for _ in range(100)}
    assert len(ids) == 100


def test_hash_message_payload_is_stable():
    assert hash_message_payload("hello") == hash_message_payload("hello")


def test_hash_dict_payload_is_stable():
    d1 = {"a": 1, "b": "x"}
    d2 = {"b": "x", "a": 1}
    assert hash_dict_payload(d1) == hash_dict_payload(d2)


def test_hash_dict_payload_differs_for_different_content():
    assert hash_dict_payload({"a": 1}) != hash_dict_payload({"a": 2})


def test_disabled_correlation_is_noop():
    corr = DesktopCorrelation(trace_recorder=None)
    assert not corr.is_active
    corr.emit_bridge_step("01", "test", status="ok")
    corr.emit_transport_event("desktop.transport.connecting")
    corr.emit_intent_dispatched("ralph_scan", intent_id="abc")
    corr.emit_intent_result("ralph_scan", "abc", "completed")


def test_bridge_step_emits_event():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    corr = DesktopCorrelation(trace_recorder=recorder)

    corr.emit_bridge_step("bridge:01", "assets verified", status="ok", duration_ms=5)
    events = [e for e in store.events if e["name"] == "desktop.bridge.probe"]
    assert len(events) == 1
    attrs = events[0]["attributes"]
    assert attrs["bridge.step_id"] == "bridge:01"
    assert attrs["bridge.step_label"] == "assets verified"
    assert attrs["bridge.step_status"] == "ok"
    assert attrs["correlation_id"] == corr.correlation_id


def test_bridge_step_sanitizes_unsafe_details():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    corr = DesktopCorrelation(trace_recorder=recorder)

    corr.emit_bridge_step("bridge:09", "served main.js", status="ok", details={
        "frontend_dir": "/Users/bob/project/frontend/desktop",
        "token_value": "secret-abc123",
        "raw_path": "/tmp/secrets.txt",
        "port": 9876,
        "tls_enabled": False,
    })
    events = [e for e in store.events if e["name"] == "desktop.bridge.probe"]
    assert len(events) == 1
    details = events[0]["attributes"]
    assert "frontend_dir_hash" in details, "Raw path replaced with hash"
    assert "frontend_dir_kind" in details, "Path kind should be present"
    assert "frontend_dir" not in details, "Raw frontend_dir must not leak into trace"
    assert "port" in details
    assert "tls_enabled" in details
    assert "token_value" not in details
    assert "raw_path" not in details


def test_intent_dispatched_emits_event():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    corr = DesktopCorrelation(trace_recorder=recorder)

    payload = {"profile": "quick", "paths": ["."]}
    corr.emit_intent_dispatched(
        "ralph_scan", intent_id="ii_001", payload_hash=hash_dict_payload(payload), payload_kind="ralph_scan_params"
    )
    events = [e for e in store.events if e["name"] == "desktop.intent.dispatched"]
    assert len(events) == 1
    attrs = events[0]["attributes"]
    assert attrs["intent.name"] == "ralph_scan"
    assert attrs["intent.id"] == "ii_001"
    assert attrs["intent.payload_hash"] != ""
    assert attrs["correlation_id"] == corr.correlation_id


def test_intent_result_emits_event():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    corr = DesktopCorrelation(trace_recorder=recorder)

    corr.emit_intent_result("ralph_scan", "ii_001", "completed", duration_ms=150)
    events = [e for e in store.events if e["name"] == "desktop.intent.completed"]
    assert len(events) == 1
    attrs = events[0]["attributes"]
    assert attrs["intent.result_status"] == "completed"


def test_intent_result_with_refusal():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    corr = DesktopCorrelation(trace_recorder=recorder)

    corr.emit_intent_result(
        "checkpoint.commit", "ii_099", "refused", result_refusal_code="protected_intent", duration_ms=5,
    )
    events = [e for e in store.events if e["name"] == "desktop.intent.completed"]
    assert len(events) == 1
    assert events[0]["attributes"]["intent.refusal_code"] == "protected_intent"


def test_transport_events():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    corr = DesktopCorrelation(trace_recorder=recorder)

    ts_id = new_transport_session_id()
    corr.emit_transport_event("desktop.transport.connecting", transport_session_id=ts_id)
    corr.emit_transport_event("desktop.transport.open", transport_session_id=ts_id, attributes={"token_present": True})
    connecting = [e for e in store.events if e["name"] == "desktop.transport.connecting"]
    assert len(connecting) == 1
    assert connecting[0]["attributes"]["transport.session_id"] == ts_id


def test_multiple_intents_share_correlation():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    corr = DesktopCorrelation(trace_recorder=recorder)

    corr.emit_intent_dispatched("ralph_scan", "ii_001", "", "ralph_scan_params")
    corr.emit_intent_result("ralph_scan", "ii_001", "completed")
    corr.emit_intent_dispatched("refresh_projection", "ii_002", "", "refresh_params")
    corr.emit_intent_result("refresh_projection", "ii_002", "completed")

    dispatched = [e for e in store.events if e["name"] == "desktop.intent.dispatched"]
    completed = [e for e in store.events if e["name"] == "desktop.intent.completed"]
    assert len(dispatched) == 2
    assert len(completed) == 2
    for e in dispatched + completed:
        assert e["attributes"]["correlation_id"] == corr.correlation_id


def test_correlation_id_in_span():
    store = InMemoryTraceStore()
    recorder = TraceRecorder(store)
    corr = DesktopCorrelation(trace_recorder=recorder)

    span = corr.emit_span("desktop.lifecycle", attributes={"mode": "fixture"})
    assert span is not None

    span_start = [e for e in store.events if e["event_kind"] == "span.start"]
    assert len(span_start) == 1
    assert span_start[0]["attributes"]["correlation_id"] == corr.correlation_id

    corr.end_span(span, status="ok", attributes={"result": "healthy"})
    span_end = [e for e in store.events if e["event_kind"] == "span.end"]
    assert len(span_end) == 1
    assert span_end[0]["attributes"]["correlation_id"] == corr.correlation_id
