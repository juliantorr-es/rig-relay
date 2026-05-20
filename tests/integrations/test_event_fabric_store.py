from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.events.store import EventStore, EventStoreError

pytestmark = [pytest.mark.contract, pytest.mark.integration]


@pytest.fixture
def store(tmp_path: Path) -> EventStore:
    return EventStore(path=tmp_path / "events.jsonl")


@pytest.fixture
def store_nested(tmp_path: Path) -> EventStore:
    return EventStore(path=tmp_path / "nested" / "subdir" / "events.jsonl")


def test_append_writes_one_canonical_json_line(store: EventStore):
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "bridge",
        "correlation_id": "corr_001",
        "payload_hash": "a" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {"runtime_state": "idle"},
    }
    store.append(event)
    assert store.exists()
    with open(store._path) as f:
        lines = f.readlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_id"] == "evt_001"


def test_read_returns_list_of_parsed_dicts(store: EventStore):
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "bridge",
        "correlation_id": "corr_001",
        "payload_hash": "a" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {"runtime_state": "idle"},
    }
    store.append(event)
    results = store.read()
    assert len(results) == 1
    assert results[0]["event_id"] == "evt_001"
    assert results[0]["event_type"] == "bridge.status.updated"


def test_duplicate_event_id_appends_both(store: EventStore):
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "bridge",
        "correlation_id": "corr_001",
        "payload_hash": "a" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {"runtime_state": "idle"},
    }
    store.append(event)
    store.append(event)
    results = store.read()
    assert len(results) == 2
    assert results[0]["event_id"] == "evt_001"
    assert results[1]["event_id"] == "evt_001"


def test_missing_event_id_raises_event_store_error(store: EventStore):
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_type": "bridge.status.updated",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "bridge",
        "correlation_id": "corr_001",
        "payload_hash": "a" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {},
    }
    with pytest.raises(EventStoreError, match="event_id required"):
        store.append(event)


def test_forbidden_field_in_payload_rejected(store: EventStore):
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_001",
        "event_type": "bridge.status.updated",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "bridge",
        "correlation_id": "corr_001",
        "payload_hash": "a" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {"token_prefix": "ghp_abc123"},
    }
    with pytest.raises(EventStoreError, match="raw_content_field_detected"):
        store.append(event)


def test_forbidden_field_nested_in_payload_rejected(store: EventStore):
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_002",
        "event_type": "tool.invocation.completed",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "runtime",
        "correlation_id": "corr_002",
        "payload_hash": "b" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {"nested": {"access_token": "secret"}},
    }
    with pytest.raises(EventStoreError, match="raw_content_field_detected"):
        store.append(event)


def test_store_creates_parent_directories(store_nested: EventStore):
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_001",
        "event_type": "test.event",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "test",
        "correlation_id": "corr_001",
        "payload_hash": "a" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {},
    }
    assert not store_nested._path.parent.exists()
    store_nested.append(event)
    assert store_nested.exists()
    assert store_nested._path.parent.exists()


def test_exists_returns_false_before_append(store: EventStore):
    assert not store.exists()
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_001",
        "event_type": "test.event",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "test",
        "correlation_id": "corr_001",
        "payload_hash": "a" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "payload": {},
    }
    store.append(event)
    assert store.exists()


def test_read_returns_empty_for_nonexistent_store(tmp_path: Path):
    store = EventStore(path=tmp_path / "nonexistent.jsonl")
    assert store.read() == []


def test_multiple_appends_produce_multiple_lines(store: EventStore):
    for i in range(3):
        event = {
            "schema_version": "rig.event.envelope.v1",
            "event_id": f"evt_{i:03d}",
            "event_type": "test.event",
            "occurred_at": "2025-01-01T00:00:00+00:00",
            "producer": "test",
            "correlation_id": f"corr_{i:03d}",
            "payload_hash": "a" * 64,
            "sensitivity_class": "internal_operational",
            "redaction_status": "passed",
            "content_light": True,
            "payload": {"index": i},
        }
        store.append(event)
    results = store.read()
    assert len(results) == 3
    assert results[0]["event_id"] == "evt_000"
    assert results[1]["event_id"] == "evt_001"
    assert results[2]["event_id"] == "evt_002"
