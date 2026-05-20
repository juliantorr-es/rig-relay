from __future__ import annotations

import pytest

from rig_relay.events.alerting import AlertRule, evaluate_alerts
from rig_relay.events.metrics import EventFabricMetrics

pytestmark = [pytest.mark.contract, pytest.mark.integration]


def test_evaluate_alerts_returns_empty_for_healthy_metrics():
    metrics = EventFabricMetrics()
    metrics.bridge_backend_health = "healthy"
    metrics.projection_freshness = "fresh"
    metrics.reconnect_pressure = "none"
    metrics.consumer_error_count = 0
    metrics.wal_uncommitted_count = 0
    alerts = evaluate_alerts(metrics)
    assert alerts == []


def test_projection_stale_fires():
    metrics = EventFabricMetrics()
    metrics.projection_freshness = "stale"
    alerts = evaluate_alerts(metrics)
    triggered = [a for a in alerts if a["rule_name"] == "projection_stale"]
    assert len(triggered) == 1
    assert triggered[0]["severity"] == "warning"
    assert triggered[0]["current_value"] == "stale"


def test_reconnect_pressure_high_fires():
    metrics = EventFabricMetrics()
    metrics.reconnect_pressure = "high"
    alerts = evaluate_alerts(metrics)
    triggered = [a for a in alerts if a["rule_name"] == "reconnect_pressure_high"]
    assert len(triggered) == 1
    assert triggered[0]["severity"] == "warning"


def test_consumer_error_rate_fires():
    metrics = EventFabricMetrics()
    metrics.consumer_error_count = 11
    alerts = evaluate_alerts(metrics)
    triggered = [a for a in alerts if a["rule_name"] == "consumer_error_rate"]
    assert len(triggered) == 1
    assert triggered[0]["severity"] == "critical"
    assert triggered[0]["current_value"] == 11


def test_consumer_error_rate_does_not_fire_below_threshold():
    metrics = EventFabricMetrics()
    metrics.consumer_error_count = 5
    alerts = evaluate_alerts(metrics)
    triggered = [a for a in alerts if a["rule_name"] == "consumer_error_rate"]
    assert len(triggered) == 0


def test_bridge_disconnected_fires():
    metrics = EventFabricMetrics()
    metrics.bridge_backend_health = "disconnected"
    alerts = evaluate_alerts(metrics)
    triggered = [a for a in alerts if a["rule_name"] == "bridge_disconnected"]
    assert len(triggered) == 1
    assert triggered[0]["severity"] == "critical"


def test_wal_overflow_fires():
    metrics = EventFabricMetrics()
    metrics.wal_uncommitted_count = 1001
    alerts = evaluate_alerts(metrics)
    triggered = [a for a in alerts if a["rule_name"] == "wal_overflow"]
    assert len(triggered) == 1
    assert triggered[0]["severity"] == "critical"
    assert triggered[0]["current_value"] == 1001


def test_wal_overflow_does_not_fire_below_threshold():
    metrics = EventFabricMetrics()
    metrics.wal_uncommitted_count = 500
    alerts = evaluate_alerts(metrics)
    triggered = [a for a in alerts if a["rule_name"] == "wal_overflow"]
    assert len(triggered) == 0


def test_alert_output_includes_required_fields():
    metrics = EventFabricMetrics()
    metrics.projection_freshness = "stale"
    alerts = evaluate_alerts(metrics)
    assert len(alerts) >= 1
    alert = alerts[0]
    assert "rule_name" in alert
    assert "severity" in alert
    assert "current_value" in alert
    assert "threshold" in alert
    assert "triggered_at" in alert


def test_alert_output_is_content_light():
    metrics = EventFabricMetrics()
    metrics.bridge_backend_health = "disconnected"
    alerts = evaluate_alerts(metrics)
    for alert in alerts:
        assert "payload" not in alert
        assert "raw" not in str(alert)
        for value in alert.values():
            if isinstance(value, str):
                assert "secret" not in value.lower()
                assert "token" not in value.lower()


def test_custom_rules_evaluated():
    metrics = EventFabricMetrics()
    metrics.bridge_backend_health = "healthy"
    custom_rules = [
        AlertRule(
            rule_name="custom_health_check",
            severity="info",
            field="bridge_backend_health",
            operator="==",
            threshold="healthy",
        )
    ]
    alerts = evaluate_alerts(metrics, rules=custom_rules)
    assert len(alerts) == 1
    assert alerts[0]["rule_name"] == "custom_health_check"
    assert alerts[0]["current_value"] == "healthy"
