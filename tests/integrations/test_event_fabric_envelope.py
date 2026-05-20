from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.events.envelope import (
    EventEnvelope,
    EventRedactionStatus,
    EventSensitivityClass,
    canonical_payload_hash,
    new_event_id,
)

pytestmark = [pytest.mark.contract, pytest.mark.integration]


def test_envelope_as_dict_has_all_required_fields():
    env = EventEnvelope()
    env.event_type = "bridge.status.updated"
    env.source = "rig_relay.desktop"
    env.producer = "bridge"
    env.payload = {"runtime_state": "idle"}
    env.finalize()

    d = env.as_dict()

    required = {
        "schema_version",
        "event_id",
        "event_type",
        "occurred_at",
        "producer",
        "correlation_id",
        "payload_hash",
        "sensitivity_class",
        "redaction_status",
        "content_light",
    }
    for key in required:
        assert key in d, f"missing required field: {key}"
    assert d["schema_version"] == "rig.event.envelope.v1"
    assert d["content_light"] is True


def test_canonical_payload_hash_is_deterministic():
    payload = {"key": "value", "nested": {"a": 1, "b": 2}}
    h1 = canonical_payload_hash(payload)
    h2 = canonical_payload_hash(payload)
    assert h1 == h2
    assert len(h1) == 64


def test_payload_hash_changes_when_payload_changes():
    h1 = canonical_payload_hash({"a": 1})
    h2 = canonical_payload_hash({"a": 2})
    assert h1 != h2


def test_event_id_is_unique_across_creations():
    ids = {new_event_id() for _ in range(100)}
    assert len(ids) == 100
    for eid in ids:
        assert eid.startswith("evt_")


def test_strenum_values_serialize_as_json_safe_strings():
    assert json.dumps(EventSensitivityClass.PUBLIC) == '"public"'
    assert (
        json.dumps(EventSensitivityClass.INTERNAL_OPERATIONAL)
        == '"internal_operational"'
    )
    assert json.dumps(EventSensitivityClass.NEVER_EMIT) == '"never_emit"'
    assert json.dumps(EventRedactionStatus.PASSED) == '"passed"'
    assert json.dumps(EventRedactionStatus.QUARANTINED) == '"quarantined"'
    assert json.dumps(EventRedactionStatus.NEEDS_REVIEW) == '"needs_review"'


def test_envelope_validates_against_schema():
    import jsonschema

    repo_root = Path(__file__).resolve().parent.parent.parent
    schema_path = repo_root / "docs/schemas/rig.event.envelope.v1.schema.json"
    schema = json.loads(schema_path.read_text())

    env = EventEnvelope()
    env.event_type = "bridge.status.updated"
    env.source = "rig_relay.desktop"
    env.producer = "bridge"
    env.payload = {"runtime_state": "idle"}
    env.finalize()

    jsonschema.validate(instance=env.as_dict(), schema=schema)


def test_envelope_with_forbidden_payload_fields_still_produces_dict():
    payload = {"access_token": "secret-stuff", "runtime_state": "idle"}
    env = EventEnvelope()
    env.event_type = "bridge.status.updated"
    env.source = "rig_relay.desktop"
    env.producer = "bridge"
    env.payload = payload
    env.finalize()

    d = env.as_dict()
    assert d["payload"]["access_token"] == "secret-stuff"
    assert d["payload_hash"] == canonical_payload_hash(payload)


def test_canonical_payload_hash_is_canonical_for_key_order():
    h1 = canonical_payload_hash({"b": 2, "a": 1})
    h2 = canonical_payload_hash({"a": 1, "b": 2})
    assert h1 == h2


def test_finalize_updates_payload_hash_in_place():
    env = EventEnvelope()
    env.event_type = "test.event"
    env.payload = {"x": "y"}

    assert env.payload_hash == ""
    env.finalize()
    assert env.payload_hash == canonical_payload_hash({"x": "y"})
