"""A2A v1 Protocol — lifecycle, delegation, and schema tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.protocols.a2a import (
    A2ATaskLifecycleEvent,
    A2ATaskStatus,
    build_agent_card,
    build_agent_card_with_security,
    build_delegation_receipt,
    build_task_card,
    cancel_task,
    send_local_task_message,
    serve_agent_card,
    serve_agent_card_json,
    transition_task,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
S = REPO_ROOT / "docs" / "schemas"


def _load(name: str) -> dict:
    return json.loads((S / name).read_text(encoding="utf-8"))


def _v(instance, name):
    jsonschema.validate(instance, _load(name))


def _card_dict(c) -> dict:
    return {
        "schema_version": "rig.relay.a2a.task_card.v1",
        "task_id": c.task_id,
        "agent_id": c.agent_id,
        "status": c.status.value,
        "description": c.description,
        "input_hash": c.input_hash,
        "output_hash": c.output_hash,
        "trace_id": c.trace_id,
        "messages": c.messages,
        "events": [
            {
                "event_type": e.event_type.value,
                "timestamp": e.timestamp,
                "metadata_hash": e.metadata_hash,
                "schema_version": e.schema_version,
                "task_id": e.task_id,
                "trace_id": e.trace_id,
                "content_light": e.content_light,
                "generated_at": e.generated_at,
                "seq": e.seq,
            }
            for e in c.events
        ],
        "seq": c.seq,
        "created_at": c.created_at,
        "updated_at": c.updated_at,
        "content_light": True,
        "generated_at": c.generated_at,
    }


class TestA2AV1:
    def test_agent_card_validates(self):
        d = build_agent_card_with_security("a1", "Test", "desc", ["read"], ["explore"])
        _v(d, "rig.relay.a2a.agent_card.v1.schema.json")

    def test_task_card_validates(self):
        c = build_task_card("t1", "a1", "test", "tr1")
        _v(_card_dict(c), "rig.relay.a2a.task_card.v1.schema.json")

    def test_valid_transitions(self):
        c = build_task_card("t1", "a1")
        assert c.status == A2ATaskStatus.CREATED
        c = transition_task(c, A2ATaskStatus.SUBMITTED)
        c = transition_task(c, A2ATaskStatus.RUNNING)
        c = transition_task(c, A2ATaskStatus.COMPLETED)
        assert c.status == A2ATaskStatus.COMPLETED

    def test_invalid_transition_refused(self):
        c = build_task_card("t1", "a1")
        with pytest.raises(ValueError, match="Invalid A2A task transition"):
            transition_task(c, A2ATaskStatus.COMPLETED)

    def test_send_message_creates_update(self):
        c = build_task_card("t1", "a1", trace_id="tr1")
        u = send_local_task_message(c, "hello", "tr1")
        assert u.task_id == c.task_id

    def test_cancel_task(self):
        c = build_task_card("t1", "a1")
        c = transition_task(c, A2ATaskStatus.SUBMITTED)
        d = cancel_task(c)
        assert d.status == A2ATaskStatus.CANCELLED

    def test_remote_federation_refused(self):
        c = build_agent_card("a1", "Test")
        assert c.remote_federation_supported is False

    def test_trace_context_present(self):
        c = build_task_card("t1", "a1", trace_id="tr-abc-123")
        assert c.trace_id == "tr-abc-123"

    def test_delegation_receipt_validates(self):
        r = build_delegation_receipt("o", "a1", "t1", "tr1", "allowed")
        _v(r.to_dict(), "rig.relay.a2a.delegation_receipt.v1.schema.json")

    def test_delegation_refused_with_code(self):
        r = build_delegation_receipt("o", "a1", "t1", "tr1", "refused", "cap_mismatch")
        d = r.to_dict()
        assert d["verdict"] == "refused"
        assert d["refusal_code"] == "cap_mismatch"

    def test_send_local_task_message_attaches_message(self):
        c = build_task_card("t1", "a1")
        assert c.messages == []
        u = send_local_task_message(c, "hello world")
        assert u.messages == ["hello world"]
        v = send_local_task_message(u, "second msg")
        assert v.messages == ["hello world", "second msg"]

    def test_task_card_has_events(self):
        c = build_task_card("t1", "a1")
        assert isinstance(c.events, list)
        assert len(c.events) == 1
        assert c.events[0].event_type == A2ATaskStatus.CREATED

    def test_build_task_card_creates_created_event(self):
        c = build_task_card("t1", "a1", trace_id="tr0")
        assert len(c.events) == 1
        event = c.events[0]
        assert event.event_type == A2ATaskStatus.CREATED
        assert event.task_id == "t1"
        assert event.trace_id == "tr0"
        assert event.seq == 1
        assert c.seq == 1

    def test_transition_task_emits_event(self):
        c = build_task_card("t1", "a1")
        assert len(c.events) == 1
        c = transition_task(c, A2ATaskStatus.SUBMITTED)
        assert len(c.events) == 2
        assert c.events[0].event_type == A2ATaskStatus.CREATED
        assert c.events[1].event_type == A2ATaskStatus.SUBMITTED
        assert c.seq == 2

    def test_cancel_task_emits_cancel_event(self):
        c = build_task_card("t1", "a1")
        c = transition_task(c, A2ATaskStatus.SUBMITTED)
        d = cancel_task(c)
        assert d.status == A2ATaskStatus.CANCELLED
        assert len(d.events) == 3
        assert d.events[-1].event_type == A2ATaskStatus.CANCELLED

    def test_event_seq_increments(self):
        c = build_task_card("t1", "a1")
        assert c.seq == 1
        c = transition_task(c, A2ATaskStatus.SUBMITTED)
        assert c.seq == 2
        c = transition_task(c, A2ATaskStatus.RUNNING)
        assert c.seq == 3
        c = transition_task(c, A2ATaskStatus.COMPLETED)
        assert c.seq == 4
        assert [e.seq for e in c.events] == [1, 2, 3, 4]

    def test_lifecycle_event_type_is_enum(self):
        event = A2ATaskLifecycleEvent(
            event_type=A2ATaskStatus.CREATED, task_id="t1", trace_id="tr0"
        )
        assert event.event_type == A2ATaskStatus.CREATED
        assert isinstance(event.event_type, A2ATaskStatus)

    def test_delegation_receipt_verdict_literal(self):
        r = build_delegation_receipt("o", "a1", "t1", "tr1", "completed")
        assert r.verdict == "completed"
        d = r.to_dict()
        assert d["verdict"] == "completed"

    @pytest.mark.asyncio
    async def test_serve_agent_card(self):
        card = await serve_agent_card("test-agent", "trace-42")
        assert card.agent_id == "test-agent"
        assert card.name == "test-agent"
        assert card.local_only is True

    @pytest.mark.asyncio
    async def test_serve_agent_card_json(self):
        result = await serve_agent_card_json("test-agent", "trace-42")
        agent = result["agent_card"]
        assert agent["agent_id"] == "test-agent"
        assert agent["agent_name"] == "test-agent"
        assert agent["trace_id"] == "trace-42"
        assert agent["local_only"] is True

    def test_transition_preserves_messages(self):
        c = build_task_card("t1", "a1")
        c = send_local_task_message(c, "msg1")
        c = transition_task(c, A2ATaskStatus.SUBMITTED)
        assert c.messages == ["msg1"]
        c = send_local_task_message(c, "msg2")
        assert c.messages == ["msg1", "msg2"]

    def test_cancel_of_terminal_is_noop(self):
        c = build_task_card("t1", "a1")
        c = transition_task(c, A2ATaskStatus.SUBMITTED)
        c = transition_task(c, A2ATaskStatus.RUNNING)
        c = transition_task(c, A2ATaskStatus.COMPLETED)
        d = cancel_task(c)
        assert d is c
        assert d.status == A2ATaskStatus.COMPLETED

    def test_failed_cannot_be_revived(self):
        c = build_task_card("t1", "a1")
        c = transition_task(c, A2ATaskStatus.SUBMITTED)
        c = transition_task(c, A2ATaskStatus.RUNNING)
        c = transition_task(c, A2ATaskStatus.FAILED)
        with pytest.raises(ValueError, match="Invalid A2A task transition"):
            transition_task(c, A2ATaskStatus.RUNNING)
