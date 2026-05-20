from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from rig_relay.events.resource_projection_feed import ResourceProjectionFeed

pytestmark = [pytest.mark.contract, pytest.mark.integration]

SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "docs"
    / "schemas"
    / "rig.event.resource_projection_snapshot.v1.schema.json"
)


def _load_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text("utf-8"))


def _validate_snapshot(snapshot: dict) -> None:
    schema = _load_schema()
    jsonschema.Draft7Validator(schema).validate(snapshot)


def make_event(event_type: str, payload: dict | None = None) -> dict:
    return {"event_type": event_type, "payload": payload or {}}


def test_snapshot_validates_against_schema():
    feed = ResourceProjectionFeed()
    _validate_snapshot(feed.snapshot())


def test_initial_snapshot_has_unknown_health():
    feed = ResourceProjectionFeed()
    assert feed.snapshot()["bridge_backend_health"] == "unknown"


@pytest.mark.asyncio
async def test_bridge_status_updated_sets_health_from_runtime_state():
    feed = ResourceProjectionFeed()
    await feed.handle_event(
        make_event("bridge.status.updated", {"runtime_state": "idle"})
    )
    assert feed.snapshot()["bridge_backend_health"] == "idle"


@pytest.mark.asyncio
async def test_bridge_disconnect_sets_health_to_disconnected():
    feed = ResourceProjectionFeed()
    await feed.handle_event(make_event("bridge.disconnect"))
    assert feed.snapshot()["bridge_backend_health"] == "disconnected"


@pytest.mark.asyncio
async def test_sequence_of_bridge_events_produces_correct_cumulative_state():
    feed = ResourceProjectionFeed()
    await feed.handle_event(
        make_event("bridge.status.updated", {"runtime_state": "active"})
    )
    await feed.handle_event(make_event("bridge.disconnect"))
    snapshot = feed.snapshot()
    assert snapshot["bridge_backend_health"] == "disconnected"
    assert snapshot["event_count"] == 2


@pytest.mark.asyncio
async def test_projection_stale_sets_freshness_to_stale():
    feed = ResourceProjectionFeed()
    await feed.handle_event(make_event("projection.stale"))
    assert feed.snapshot()["projection_freshness"] == "stale"


@pytest.mark.asyncio
async def test_projection_fresh_sets_freshness_to_fresh():
    feed = ResourceProjectionFeed()
    await feed.handle_event(make_event("projection.fresh"))
    assert feed.snapshot()["projection_freshness"] == "fresh"


@pytest.mark.asyncio
async def test_reconnect_events_accumulate_pressure():
    feed = ResourceProjectionFeed()
    await feed.handle_event(make_event("bridge.reconnect_failed"))
    assert feed.snapshot()["reconnect_pressure"] == "moderate"
    await feed.handle_event(make_event("bridge.reconnect_failed"))
    await feed.handle_event(make_event("bridge.reconnect_failed"))
    assert feed.snapshot()["reconnect_pressure"] == "high"


def test_command_boundary_violations_start_at_zero_for_projection_updates():
    feed = ResourceProjectionFeed()
    boundary = feed.snapshot()["command_boundary_summary"]
    assert boundary["violation_count"] == 0
    assert boundary["violations"] == []
    assert boundary["gated_command_classes"] == []


@pytest.mark.asyncio
async def test_snapshot_includes_hints_when_degraded():
    feed = ResourceProjectionFeed()
    await feed.handle_event(make_event("bridge.disconnect"))
    hints = feed.snapshot()["recommended_scheduling_hints"]
    assert "trigger_backend_reconnect" in hints


@pytest.mark.asyncio
async def test_snapshot_includes_degraded_reasons_when_health_is_degraded():
    feed = ResourceProjectionFeed()
    await feed.handle_event(make_event("bridge.disconnect"))
    degraded = feed.snapshot()["degraded_reasons"]
    assert any("bridge_backend_health=disconnected" in r for r in degraded)


def test_snapshot_is_deterministic_for_same_sequence():
    feed = ResourceProjectionFeed()
    s1 = feed.snapshot()
    s2 = feed.snapshot()
    s1_stable = {k: v for k, v in s1.items() if k != "generated_at"}
    s2_stable = {k: v for k, v in s2.items() if k != "generated_at"}
    assert s1_stable == s2_stable
