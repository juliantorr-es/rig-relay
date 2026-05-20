from __future__ import annotations

import pytest

from rig_relay.events.metrics import EventFabricMetrics

pytestmark = [pytest.mark.contract, pytest.mark.integration]


@pytest.fixture
def metrics() -> EventFabricMetrics:
    return EventFabricMetrics()


def test_update_from_resource_projection_sets_bridge_backend_health(
    metrics: EventFabricMetrics,
):
    snapshot = {"bridge_backend_health": "healthy"}
    metrics.update_from_resource_projection(snapshot)
    assert metrics.bridge_backend_health == "healthy"


def test_update_from_resource_projection_sets_projection_freshness(
    metrics: EventFabricMetrics,
):
    snapshot = {"projection_freshness": "fresh"}
    metrics.update_from_resource_projection(snapshot)
    assert metrics.projection_freshness == "fresh"


def test_update_from_resource_projection_defaults_on_missing_fields(
    metrics: EventFabricMetrics,
):
    snapshot: dict = {}
    metrics.update_from_resource_projection(snapshot)
    assert metrics.bridge_backend_health == "unknown"
    assert metrics.projection_freshness == "unknown"
    assert metrics.reconnect_pressure == "none"


def test_to_prometheus_text_generates_valid_format(metrics: EventFabricMetrics):
    text = metrics.to_prometheus_text()
    assert "# HELP rig_" in text
    assert "# TYPE rig_" in text
    lines = text.strip().split("\n")
    names_with_help = [l for l in lines if l.startswith("# HELP")]
    names_with_type = [l for l in lines if l.startswith("# TYPE")]
    assert len(names_with_help) >= 5
    assert len(names_with_type) >= 5


def test_to_prometheus_text_includes_metric_values(metrics: EventFabricMetrics):
    metrics.consumer_error_count = 42
    metrics.wal_uncommitted_count = 7
    text = metrics.to_prometheus_text()
    assert "rig_consumer_error_count 42" in text
    assert "rig_wal_uncommitted_count 7" in text


def test_to_prometheus_text_contains_no_raw_event_payloads(metrics: EventFabricMetrics):
    text = metrics.to_prometheus_text()
    assert "token_prefix" not in text
    assert "access_token" not in text
    assert "raw_response" not in text
    assert "secret" not in text
    assert "private_key" not in text


def test_to_json_returns_dict_with_all_metric_fields(metrics: EventFabricMetrics):
    result = metrics.to_json()
    assert isinstance(result, dict)
    assert "bridge_backend_health" in result
    assert "projection_freshness" in result
    assert "reconnect_pressure" in result
    assert "event_queue_pressure" in result
    assert "consumer_error_count" in result
    assert "wal_uncommitted_count" in result
    assert "last_updated" in result


def test_metrics_are_content_light(metrics: EventFabricMetrics):
    result = metrics.to_json()
    for key in result:
        assert "token" not in str(key).lower() or key == "last_updated"
    for value in result.values():
        if isinstance(value, str):
            assert "secret" not in value
            assert "password" not in value


def test_consumer_error_count_increments_correctly():
    m1 = EventFabricMetrics()
    m1.consumer_error_count += 1
    m1.consumer_error_count += 1
    assert m1.consumer_error_count == 2
    m1.consumer_error_count += 3
    assert m1.consumer_error_count == 5


def test_to_opentelemetry_metrics_returns_dict(metrics: EventFabricMetrics):
    result = metrics.to_opentelemetry_metrics()
    assert isinstance(result, dict)
    assert "bridge_backend_health" in result


def test_all_metric_names_prefixed_with_rig(metrics: EventFabricMetrics):
    text = metrics.to_prometheus_text()
    metric_lines = [
        l for l in text.strip().split("\n") if not l.startswith("#") and l.strip()
    ]
    for line in metric_lines:
        assert line.startswith("rig_"), f"Metric line does not start with rig_: {line}"
