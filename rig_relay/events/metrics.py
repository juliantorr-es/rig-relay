from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(slots=True)
class EventFabricMetrics:
    bridge_backend_health: str = "unknown"
    projection_freshness: str = "unknown"
    reconnect_pressure: str = "none"
    event_queue_pressure: str = "none"
    consumer_error_count: int = 0
    wal_uncommitted_count: int = 0
    last_updated: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def update_from_resource_projection(self, snapshot: dict[str, Any]) -> None:
        self.bridge_backend_health = snapshot.get("bridge_backend_health", "unknown")
        self.projection_freshness = snapshot.get("projection_freshness", "unknown")
        self.reconnect_pressure = snapshot.get("reconnect_pressure", "none")
        self.event_queue_pressure = snapshot.get("event_queue_pressure", "none")
        self.consumer_error_count = snapshot.get("consumer_error_count", 0)
        self.last_updated = datetime.now(UTC).isoformat()

    def to_prometheus_text(self) -> str:
        lines: list[str] = []

        gauge_metrics = [
            (
                "rig_bridge_backend_health",
                "Bridge backend health status",
                self._health_value(self.bridge_backend_health),
            ),
            (
                "rig_projection_freshness",
                "Projection freshness status",
                self._freshness_value(self.projection_freshness),
            ),
            (
                "rig_reconnect_pressure",
                "Reconnect pressure level",
                self._pressure_value(self.reconnect_pressure),
            ),
            (
                "rig_event_queue_pressure",
                "Event queue pressure level",
                self._pressure_value(self.event_queue_pressure),
            ),
            (
                "rig_wal_uncommitted_count",
                "WAL uncommitted entry count",
                self.wal_uncommitted_count,
            ),
        ]

        counter_metrics = [
            (
                "rig_consumer_error_count",
                "Consumer error count",
                self.consumer_error_count,
            )
        ]

        for name, help_text, value in gauge_metrics:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {value}")

        for name, help_text, value in counter_metrics:
            lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} counter")
            lines.append(f"{name} {value}")

        return "\n".join(lines) + "\n"

    def to_json(self) -> dict[str, Any]:
        return {
            "bridge_backend_health": self.bridge_backend_health,
            "projection_freshness": self.projection_freshness,
            "reconnect_pressure": self.reconnect_pressure,
            "event_queue_pressure": self.event_queue_pressure,
            "consumer_error_count": self.consumer_error_count,
            "wal_uncommitted_count": self.wal_uncommitted_count,
            "last_updated": self.last_updated,
        }

    def to_opentelemetry_metrics(self) -> dict[str, Any]:
        return self.to_json()

    @staticmethod
    def _health_value(status: str) -> int:
        mapping = {
            "healthy": 1,
            "unknown": 0,
            "degraded": 2,
            "disconnected": 3,
            "stale": 4,
            "near_exhausted": 3,
        }
        return mapping.get(status, 0)

    @staticmethod
    def _freshness_value(status: str) -> int:
        mapping = {"fresh": 1, "unknown": 0, "stale": 2}
        return mapping.get(status, 0)

    @staticmethod
    def _pressure_value(status: str) -> int:
        mapping = {"none": 0, "moderate": 1, "high": 2}
        return mapping.get(status, 0)


__all__ = ["EventFabricMetrics"]
