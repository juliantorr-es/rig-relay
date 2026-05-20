from __future__ import annotations

import pytest

from rig_relay.events.resource_projection import ResourceProjection

pytestmark = [pytest.mark.contract, pytest.mark.integration, pytest.mark.substrate]


def make_event(event_type: str, payload: dict | None = None) -> dict:
    return {"event_type": event_type, "payload": payload or {}}


def test_bridge_status_updated_sets_health_to_runtime_state():
    proj = ResourceProjection()
    proj.apply_event(make_event("bridge.status.updated", {"runtime_state": "idle"}))
    assert proj.bridge_backend_health == "idle"


def test_bridge_disconnect_sets_health_to_disconnected():
    proj = ResourceProjection()
    proj.bridge_backend_health = "healthy"
    proj.apply_event(make_event("bridge.disconnect"))
    assert proj.bridge_backend_health == "disconnected"


def test_projection_stale_sets_freshness_to_stale():
    proj = ResourceProjection()
    proj.projection_freshness = "fresh"
    proj.apply_event(make_event("projection.stale"))
    assert proj.projection_freshness == "stale"


def test_projection_fresh_sets_freshness_to_fresh():
    proj = ResourceProjection()
    proj.projection_freshness = "stale"
    proj.apply_event(make_event("projection.fresh"))
    assert proj.projection_freshness == "fresh"


def test_resource_cpu_pressure_high_sets_queue_pressure_high():
    proj = ResourceProjection()
    proj.apply_event(make_event("resource.cpu_pressure.high"))
    assert proj.event_queue_pressure == "high"


def test_queue_pressure_normal_sets_queue_pressure_normal():
    proj = ResourceProjection()
    proj.event_queue_pressure = "high"
    proj.apply_event(make_event("runtime.queue_pressure.normal"))
    assert proj.event_queue_pressure == "normal"


def test_unknown_event_type_is_silently_ignored():
    proj = ResourceProjection()
    initial_summary = proj.as_summary()
    proj.apply_event(make_event("completely.unknown.event.type"))
    assert proj.as_summary() == initial_summary


def test_error_events_increment_consumer_error_count():
    proj = ResourceProjection()
    proj.apply_event(make_event("worker.failed"))
    assert proj.consumer_error_count == 1
    proj.apply_event(make_event("tool.invocation.failed"))
    assert proj.consumer_error_count == 2


def test_reconnect_failed_increments_pressure():
    proj = ResourceProjection()
    proj.apply_event(make_event("bridge.reconnect_failed"))
    assert proj.reconnect_pressure == "moderate"
    proj.apply_event(make_event("bridge.reconnect_failed"))
    proj.apply_event(make_event("bridge.reconnect_failed"))
    assert proj.reconnect_pressure == "high"


def test_as_summary_includes_all_required_keys():
    proj = ResourceProjection()
    summary = proj.as_summary()
    required_keys = {
        "bridge_backend_health",
        "bridge_status_age_ms",
        "projection_freshness",
        "reconnect_pressure",
        "event_queue_pressure",
        "consumer_error_count",
        "github_rate_limit_health",
        "test_validation_pressure",
    }
    for key in required_keys:
        assert key in summary, f"missing key: {key}"


def test_github_events_affect_rate_limit_health():
    proj = ResourceProjection()
    proj.apply_event(make_event("github.rate_limit.near_exhausted"))
    assert proj.github_rate_limit_health == "near_exhausted"
    proj.apply_event(make_event("github.rate_limit.restored"))
    assert proj.github_rate_limit_health == "healthy"


def test_bridge_backend_stale_detected_sets_stale():
    proj = ResourceProjection()
    proj.apply_event(make_event("bridge.backend_stale.detected"))
    assert proj.bridge_backend_health == "stale"


def test_resource_test_budget_exhausted_sets_pressure():
    proj = ResourceProjection()
    proj.apply_event(make_event("resource.test_budget.exhausted"))
    assert proj.test_validation_pressure == "pending"
