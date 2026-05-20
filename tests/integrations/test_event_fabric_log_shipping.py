from __future__ import annotations

import json
from pathlib import Path

import pytest

from rig_relay.events.log_shipping import LogShipper

pytestmark = [pytest.mark.contract, pytest.mark.integration]


def _make_event(**overrides: object) -> dict:
    event = {
        "schema_version": "rig.event.envelope.v1",
        "event_id": "evt_ship_001",
        "event_type": "bridge.status.updated",
        "source": "rig_relay.desktop",
        "occurred_at": "2025-01-01T00:00:00+00:00",
        "producer": "bridge",
        "correlation_id": "corr_001",
        "causation_id": "",
        "command_id": "",
        "trace_id": "",
        "span_id": "",
        "sequence": 0,
        "subject": "",
        "payload_schema": "rig.bridge.lifecycle.v1",
        "payload_hash": "a" * 64,
        "sensitivity_class": "internal_operational",
        "redaction_status": "passed",
        "content_light": True,
        "resource_tags": [],
        "policy_tags": [],
        "payload": {"runtime_state": "idle", "bridge_runtime_state": "healthy"},
    }
    event.update(overrides)
    return event


@pytest.fixture
def shipper(tmp_path: Path) -> LogShipper:
    return LogShipper(ship_dir=tmp_path / "shipped")


def _read_shipped(shipper: LogShipper) -> list[dict]:
    if not shipper.current_path.exists():
        return []
    results: list[dict] = []
    with open(shipper.current_path) as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                results.append(json.loads(stripped))
    return results


def test_ship_event_writes_jsonl_with_envelope_fields_only(shipper: LogShipper):
    event = _make_event()
    shipper.ship_event(event)
    shipped = _read_shipped(shipper)
    assert len(shipped) == 1
    entry = shipped[0]
    assert entry["event_id"] == "evt_ship_001"
    assert entry["event_type"] == "bridge.status.updated"
    assert "shipped_at" in entry


def test_ship_event_does_not_include_raw_payload(shipper: LogShipper):
    event = _make_event(payload={"runtime_state": "idle", "token_prefix": "ghp_secret"})
    shipper.ship_event(event)
    shipped = _read_shipped(shipper)
    entry = shipped[0]
    assert "payload" not in entry
    for key in entry:
        assert "token" not in str(key) or key == "content_light"
    assert "runtime_state" not in json.dumps(entry)


def test_ship_metric_snapshot_writes_metric_jsonl_entry(shipper: LogShipper):
    metrics = {"bridge_backend_health": "healthy", "consumer_error_count": 3}
    shipper.ship_metric_snapshot(metrics)
    shipped = _read_shipped(shipper)
    assert len(shipped) == 1
    entry = shipped[0]
    assert entry["type"] == "metric_snapshot"
    assert entry["metrics"] == metrics
    assert "shipped_at" in entry


def test_rotate_creates_timestamped_rollover_file(shipper: LogShipper):
    event = _make_event()
    shipper.ship_event(event)
    original_path = shipper.current_path
    assert original_path.exists()
    rotated_path = shipper.rotate()
    assert rotated_path != original_path
    assert rotated_path.exists()
    assert not original_path.exists()
    assert "ship_" in rotated_path.name
    assert rotated_path.suffix == ".jsonl"


def test_rotate_does_not_lose_entries(shipper: LogShipper):
    event = _make_event()
    shipper.ship_event(event)
    rotated_path = shipper.rotate()
    with open(rotated_path) as f:
        lines = f.readlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["event_id"] == "evt_ship_001"


def test_shipped_logs_are_valid_jsonl(shipper: LogShipper):
    for i in range(3):
        shipper.ship_event(_make_event(event_id=f"evt_ship_{i:03d}"))
    shipped = _read_shipped(shipper)
    assert len(shipped) == 3
    for entry in shipped:
        assert isinstance(entry, dict)
        assert "event_id" in entry
        assert "shipped_at" in entry
