"""Integration tests for the correlation spine — real artifact path."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from rig_relay.core.agent_loop import _new_causation_id, _new_correlation_id
from rig_relay.core.telemetry.local import (
    _degradation_marker_written,
    get_observability_log_path,
    is_telemetry_enabled,
    log_local_event,
    set_telemetry_enabled,
    write_degradation_marker,
)
from rig_relay.core.telemetry.receipts import build_session_receipts
from rig_relay.core.tool_runtime_models import ToolRuntimeResult, ToolRuntimeStatus
from rig_relay.core.tools._agent_outcome import derive_agent_outcome


class _FakeToolClass:
    mutation_class = None


def _make_result(
    tool_call_id: str,
    correlation_id: str,
    causation_id: str,
    turn_id: str = "turn-uuid-1",
    session_id: str = "session-1",
) -> ToolRuntimeResult:
    return ToolRuntimeResult.completed(
        tool_name="test_tool",
        tool_call_id=tool_call_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        turn_id=turn_id,
        session_id=session_id,
    )


def test_sibling_tools_preserve_identity_through_outcome_and_jsonl():
    """Two sibling tools in one batch must share correlation_id/causation_id,
    differ by tool_call_id, and produce joinable outcomes and JSONL evidence.
    """
    turn_id = "turn-uuid-integration-1"
    session_id = "session-integration-1"
    corr_id = _new_correlation_id()
    cause_id = _new_causation_id()

    tc1 = "tc-sibling-a"
    tc2 = "tc-sibling-b"

    r1 = _make_result(tc1, corr_id, cause_id, turn_id, session_id)
    r2 = _make_result(tc2, corr_id, cause_id, turn_id, session_id)

    assert r1.correlation_id == corr_id
    assert r1.causation_id == cause_id
    assert r1.tool_call_id == tc1
    assert r1.turn_id == turn_id
    assert r2.correlation_id == corr_id
    assert r2.causation_id == cause_id
    assert r2.tool_call_id == tc2
    assert r2.turn_id == turn_id

    o1 = derive_agent_outcome(r1, _FakeToolClass)
    o2 = derive_agent_outcome(r2, _FakeToolClass)
    assert o1.correlation_id == corr_id
    assert o1.causation_id == cause_id
    assert o1.tool_call_id == tc1
    assert o1.session_id == session_id
    assert o1.turn_id == turn_id
    assert o2.correlation_id == corr_id
    assert o2.tool_call_id == tc2

    log_local_event(
        session_id,
        "rig.relay.tool.call_completed",
        {
            "tool_name": "test_tool",
            "tool_call_id": tc1,
            "message_id": "msg-1",
            "turn_id": turn_id,
        },
        correlation_id=corr_id,
        causation_id=cause_id,
        receipt_candidate=True,
    )
    log_local_event(
        session_id,
        "rig.relay.tool.call_completed",
        {
            "tool_name": "test_tool",
            "tool_call_id": tc2,
            "message_id": "msg-1",
            "turn_id": turn_id,
        },
        correlation_id=corr_id,
        causation_id=cause_id,
        receipt_candidate=True,
    )

    log_path = get_observability_log_path(session_id)
    assert log_path.exists(), f"Missing {log_path}"
    lines = log_path.read_text().strip().split("\n")
    assert len(lines) >= 2, f"Expected >= 2 events, got {len(lines)}"

    events = [json.loads(line) for line in lines]
    tc1_events = [e for e in events if e.get("payload", {}).get("tool_call_id") == tc1]
    tc2_events = [e for e in events if e.get("payload", {}).get("tool_call_id") == tc2]
    assert len(tc1_events) == 1
    assert len(tc2_events) == 1

    e1 = tc1_events[0]
    e2 = tc2_events[0]

    assert e1["session_id"] == session_id
    assert e2["session_id"] == session_id
    assert e1["correlation_id"] == corr_id
    assert e2["correlation_id"] == corr_id
    assert e1["causation_id"] == cause_id
    assert e2["causation_id"] == cause_id

    p1 = e1["payload"]
    p2 = e2["payload"]
    assert p1["turn_id"] == turn_id
    assert p2["turn_id"] == turn_id
    assert p1["tool_call_id"] == tc1
    assert p2["tool_call_id"] == tc2

    assert e1.get("receipt_candidate") is True


def test_two_batches_distinct_correlation_in_same_turn():
    """Two batches in the same turn must receive different correlation_id values
    and produce distinct evidence records.
    """
    turn_id = "turn-uuid-two-batches"
    session_id = "session-two-batches"

    batch1_corr = _new_correlation_id()
    batch1_cause = _new_causation_id()
    batch2_corr = _new_correlation_id()
    batch2_cause = _new_causation_id()

    assert batch1_corr != batch2_corr
    assert batch1_cause != batch2_cause

    r1 = _make_result("tc-b1", batch1_corr, batch1_cause, turn_id, session_id)
    r2 = _make_result("tc-b2", batch2_corr, batch2_cause, turn_id, session_id)

    o1 = derive_agent_outcome(r1, _FakeToolClass)
    o2 = derive_agent_outcome(r2, _FakeToolClass)

    assert o1.turn_id == turn_id
    assert o2.turn_id == turn_id
    assert o1.correlation_id == batch1_corr
    assert o2.correlation_id == batch2_corr
    assert o1.correlation_id != o2.correlation_id


def test_agent_tool_outcome_is_independently_joinable():
    """AgentToolOutcome carries all four join key components."""
    corr_id = _new_correlation_id()
    cause_id = _new_causation_id()

    r = _make_result("tc-join", corr_id, cause_id, "turn-uuid-xyz", "session-xyz")
    o = derive_agent_outcome(r, _FakeToolClass)

    assert o.session_id == "session-xyz"
    assert o.turn_id == "turn-uuid-xyz"
    assert o.correlation_id == corr_id
    assert o.tool_call_id == "tc-join"

    assert o.causation_id == cause_id


def test_legacy_result_without_new_fields_is_safe():
    """ToolRuntimeResult constructed without session_id/turn_id (legacy)
    should not crash derive_agent_outcome.
    """
    r = ToolRuntimeResult(
        status=ToolRuntimeStatus.COMPLETED,
        tool_name="legacy_tool",
        tool_call_id="tc-legacy",
    )
    o = derive_agent_outcome(r, _FakeToolClass)
    assert o.session_id is None
    assert o.turn_id is None
    assert o.correlation_id is None
    assert o.causation_id is None


def test_receipt_chain_resolves_correlation_identity():
    """Write receipt-candidate events with correlation identity, build receipts,
    and prove the receipt references an event that carries the same correlation context.
    """
    session_id = "receipt-correlation-test"
    turn_id = "turn-uuid-receipt-test"
    corr_id = _new_correlation_id()
    cause_id = _new_causation_id()
    tool_call_id = "tc-receipt-1"

    # Write a correlated tool_call_completed event (receipt_candidate=True)
    log_local_event(
        session_id,
        "rig.relay.tool.call_completed",
        {
            "tool_name": "test_tool",
            "tool_call_id": tool_call_id,
            "turn_id": turn_id,
            "message_id": "msg-1",
            "status": "success",
            "receipt_candidate": True,
        },
        correlation_id=corr_id,
        causation_id=cause_id,
        receipt_candidate=True,
    )

    # Write an artifact_written event that references the same tool.
    artifact_sha = (
        "sha256:aaaa0000aaaa0000aaaa0000aaaa0000aaaa0000aaaa0000aaaa0000aaaa0000"
    )
    log_local_event(
        session_id,
        "rig.relay.artifact.tool_output_written",
        {
            "tool_name": "test_tool",
            "tool_call_id": tool_call_id,
            "turn_id": turn_id,
            "message_id": "msg-1",
            "evidence_relative_path": f"artifacts/{tool_call_id}.json",
            "evidence_sha256": artifact_sha,
        },
        correlation_id=corr_id,
        causation_id=cause_id,
    )

    # Build receipts from the written events
    log_path = get_observability_log_path(session_id)
    receipts = build_session_receipts(log_path.parent, session_id)

    # At minimum one receipt should have been generated (from artifact_written)
    assert len(receipts) >= 1, f"Expected >= 1 receipt, got {len(receipts)}"

    # Read all events from the log
    events = [
        json.loads(line)
        for line in log_path.read_text().strip().split("\n")
        if line.strip()
    ]

    # For each receipt, find the event by event_index and verify correlation
    for receipt in receipts:
        idx = receipt.event_index
        assert idx < len(events), (
            f"Receipt event_index {idx} out of range ({len(events)} events)"
        )
        event = events[idx]

        # The receipt references an event — that event should carry correlation identity
        evt_corr = event.get("correlation_id", "")
        evt_cause = event.get("causation_id", "")
        evt_payload = event.get("payload", {})
        evt_tool = evt_payload.get("tool_call_id", "")
        evt_turn = evt_payload.get("turn_id", "")

        assert evt_corr == corr_id, (
            f"Receipt {receipt.sequence} references event {idx} "
            f"with correlation_id={evt_corr!r}, expected {corr_id}"
        )
        assert evt_cause == cause_id
        assert evt_tool == tool_call_id
        assert evt_turn == turn_id
        assert event.get("session_id") == session_id

    # Also verify we can find the tool_call_completed event and it shares identity
    tc_events = [
        e for e in events if e.get("payload", {}).get("tool_call_id") == tool_call_id
    ]
    assert len(tc_events) >= 2  # at least tool_call_completed and artifact_written

    # All events for this tool should share correlation_id
    for e in tc_events:
        assert e.get("correlation_id") == corr_id
        assert e.get("causation_id") == cause_id
        assert e.get("session_id") == session_id


def test_observability_schema_validates_correlated_event():
    """Validates a correlated observability event against the canonical schema."""
    session_id = "schema-validation-test"
    corr_id = _new_correlation_id()
    cause_id = _new_causation_id()

    # Write a correlated event
    log_local_event(
        session_id,
        "rig.relay.tool.call_completed",
        {"tool_name": "test", "tool_call_id": "tc-1", "turn_id": "turn-uuid-1"},
        correlation_id=corr_id,
        causation_id=cause_id,
        receipt_candidate=True,
    )

    log_path = get_observability_log_path(session_id)
    events = [
        json.loads(line)
        for line in log_path.read_text().strip().split("\n")
        if line.strip()
    ]
    event = events[0]

    # Validate against schema
    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.observability.v1.schema.json"
    )
    with open(schema_path) as f:
        schema = json.load(f)
    jsonschema.validate(event, schema)


def test_observability_schema_allows_legacy_events():
    """Validates a legacy observability event (no correlation fields) against the schema."""
    from datetime import UTC, datetime
    from uuid import uuid4

    schema_path = (
        Path(__file__).resolve().parent.parent.parent
        / "docs"
        / "schemas"
        / "rig.relay.observability.v1.schema.json"
    )
    with open(schema_path) as f:
        schema = json.load(f)

    # Legacy event — no correlation_id or causation_id
    legacy_event = {
        "schema_version": "rig.relay.observability.v1",
        "event_id": str(uuid4()),
        "session_id": "legacy-session",
        "sequence": 0,
        "created_at": datetime.now(UTC).isoformat(),
        "event_name": "rig.relay.tool.call_completed",
        "payload": {"tool_name": "test"},
        "producer": {"name": "rig-relay", "version": "0.1.0"},
    }
    jsonschema.validate(legacy_event, schema)


def test_degradation_marker_schema_validates():
    """Validates the degradation marker against its schema."""
    was_enabled = is_telemetry_enabled()
    try:
        set_telemetry_enabled(False)
        session_id = "degradation-schema-test"

        _degradation_marker_written.clear()
        marker_path = write_degradation_marker(session_id)
        assert marker_path is not None
        with open(marker_path) as f:
            marker = json.load(f)

        schema_path = (
            Path(__file__).resolve().parent.parent.parent
            / "docs"
            / "schemas"
            / "rig.relay.telemetry_degradation.v1.schema.json"
        )
        with open(schema_path) as f:
            schema = json.load(f)
        jsonschema.validate(marker, schema)
    finally:
        set_telemetry_enabled(was_enabled)
        _degradation_marker_written.clear()
