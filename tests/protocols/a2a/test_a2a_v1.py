"""A2A v1 Protocol — lifecycle, delegation, and schema tests."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.protocols.a2a import (
    build_agent_card,
    build_delegation_receipt,
    build_task_card,
    cancel_task,
    send_local_task_message,
    transition_task,
)
from rig_relay.protocols.a2a._models import A2ATaskStatus

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
S = REPO_ROOT / "docs" / "schemas"


def _load(name: str) -> dict:
    return json.loads((S / name).read_text(encoding="utf-8"))


def _v(instance, name):
    jsonschema.validate(instance, _load(name))


class TestA2AV1:
    def test_agent_card_validates(self):
        c = build_agent_card("a1", "Test", "desc", ["read"], ["explore"])
        _v(
            {
                "schema_version": "rig.relay.a2a.agent_card.v1",
                "agent_id": c.agent_id,
                "name": c.name,
                "description": c.description,
                "capabilities": c.capabilities,
                "supported_task_types": c.supported_task_types,
                "local_only": True,
                "remote_federation_supported": False,
                "content_light": True,
                "generated_at": c.generated_at,
            },
            "rig.relay.a2a.agent_card.v1.schema.json",
        )

    def test_task_card_validates(self):
        c = build_task_card("t1", "a1", "test", "tr1")
        _v(
            {
                "schema_version": "rig.relay.a2a.task_card.v1",
                "task_id": c.task_id,
                "agent_id": c.agent_id,
                "status": c.status.value,
                "description": c.description,
                "input_hash": "",
                "output_hash": "",
                "trace_id": c.trace_id,
                "created_at": c.created_at,
                "updated_at": c.updated_at,
                "content_light": True,
                "generated_at": c.generated_at,
            },
            "rig.relay.a2a.task_card.v1.schema.json",
        )

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
