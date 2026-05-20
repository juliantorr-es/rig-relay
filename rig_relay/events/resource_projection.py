from __future__ import annotations

from dataclasses import dataclass, field

_HIGH_RECONNECT_THRESHOLD = 3

_QUEUE_PRESSURE_HIGH_EVENTS = frozenset({
    "runtime.queue_pressure.high",
    "runtime.backpressure.threshold_reached",
    "resource.cpu_pressure.high",
})

_ERROR_INCREMENT_EVENTS = frozenset({
    "worker.failed",
    "supervisor.spawn.failed",
    "supervisor.timed_out",
    "tool.invocation.failed",
})


@dataclass(slots=True)
class ResourceProjection:
    bridge_backend_health: str = "unknown"
    bridge_status_age_ms: int = 0
    projection_freshness: str = "unknown"
    reconnect_pressure: str = "none"
    event_queue_pressure: str = "none"
    consumer_error_count: int = 0
    github_rate_limit_health: str = "unknown"
    test_validation_pressure: str = "none"
    _reconnect_failures: int = field(default=0, repr=False)

    def apply_event(self, event: dict) -> None:
        event_type: str = event.get("event_type", "")
        payload: dict = event.get("payload", {})

        match event_type:
            case "bridge.status.updated":
                self.bridge_backend_health = payload.get("runtime_state", "unknown")
                self.bridge_status_age_ms = 0
            case "bridge.disconnect":
                self.bridge_backend_health = "disconnected"
            case "bridge.reconnect_failed":
                self._handle_reconnect_failed()
            case "bridge.backend_stale.detected":
                self.bridge_backend_health = "stale"
            case "projection.stale":
                self.projection_freshness = "stale"
            case "projection.fresh":
                self.projection_freshness = "fresh"
            case "runtime.queue_pressure.normal":
                self.event_queue_pressure = "normal"
            case "github.rate_limit.near_exhausted":
                self.github_rate_limit_health = "near_exhausted"
            case "github.rate_limit.restored":
                self.github_rate_limit_health = "healthy"
            case "resource.test_budget.exhausted":
                self.test_validation_pressure = "pending"
            case "resource.github_budget.degraded":
                self.github_rate_limit_health = "degraded"
            case _:
                if event_type in _QUEUE_PRESSURE_HIGH_EVENTS:
                    self.event_queue_pressure = "high"
                elif event_type in _ERROR_INCREMENT_EVENTS:
                    self.consumer_error_count += 1

    def _handle_reconnect_failed(self) -> None:
        self._reconnect_failures += 1
        if self._reconnect_failures >= _HIGH_RECONNECT_THRESHOLD:
            self.reconnect_pressure = "high"
        elif self._reconnect_failures == 1:
            self.reconnect_pressure = "moderate"

    def as_summary(self) -> dict:
        return {
            "bridge_backend_health": self.bridge_backend_health,
            "bridge_status_age_ms": self.bridge_status_age_ms,
            "projection_freshness": self.projection_freshness,
            "reconnect_pressure": self.reconnect_pressure,
            "event_queue_pressure": self.event_queue_pressure,
            "consumer_error_count": self.consumer_error_count,
            "github_rate_limit_health": self.github_rate_limit_health,
            "test_validation_pressure": self.test_validation_pressure,
        }


__all__ = ["ResourceProjection"]
