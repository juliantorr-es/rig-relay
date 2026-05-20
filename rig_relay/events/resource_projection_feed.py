from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import hashlib
import json
from typing import Any

from rig_relay.events.command_boundary import ReactionClass, classify_reaction
from rig_relay.events.resource_projection import ResourceProjection


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(slots=True)
class ResourceProjectionFeed:
    projection: ResourceProjection = field(default_factory=ResourceProjection)
    _last_snapshot_id: str = ""
    _event_count: int = 0
    _command_boundary_violations: list[str] = field(default_factory=list)

    async def handle_event(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("event_type", ""))
        intended = "projection_update"
        reaction = classify_reaction(event_type, intended)
        if reaction == ReactionClass.FORBIDDEN:
            self._command_boundary_violations.append(event_type)
            return
        self.projection.apply_event(event)
        self._event_count += 1

    def snapshot(self) -> dict[str, Any]:
        summary = self.projection.as_summary()
        return {
            "schema_version": "rig.event.resource_projection_snapshot.v1",
            "generated_at": _now_iso(),
            "snapshot_id": _sha256_text(
                json.dumps(summary, sort_keys=True) + self._last_snapshot_id
            ),
            "event_count": self._event_count,
            "bridge_backend_health": summary["bridge_backend_health"],
            "bridge_status_age_ms": summary["bridge_status_age_ms"],
            "projection_freshness": summary["projection_freshness"],
            "reconnect_pressure": summary["reconnect_pressure"],
            "event_queue_pressure": summary["event_queue_pressure"],
            "consumer_error_count": summary["consumer_error_count"],
            "github_rate_limit_health": summary["github_rate_limit_health"],
            "test_validation_pressure": summary["test_validation_pressure"],
            "command_boundary_summary": {
                "violations": sorted(set(self._command_boundary_violations)),
                "violation_count": len(self._command_boundary_violations),
                "gated_command_classes": sorted({
                    e
                    for e in self._command_boundary_violations
                    if classify_reaction(e, "projection_update")
                    == ReactionClass.GATED_COMMAND_REQUIRED
                }),
            },
            "recommended_scheduling_hints": self._build_hints(),
            "degraded_reasons": self._build_degraded_reasons(),
            "redaction_status": "content_light",
        }

    def _build_hints(self) -> list[str]:
        hints: list[str] = []
        if self.projection.reconnect_pressure == "high":
            hints.append("increase_reconnect_backoff")
        if self.projection.event_queue_pressure == "high":
            hints.append("serialize_noncritical_tools")
        if self.projection.github_rate_limit_health == "near_exhausted":
            hints.append("reduce_github_polling_cadence")
        if self.projection.projection_freshness == "stale":
            hints.append("request_project_refresh")
        if self.projection.bridge_backend_health == "disconnected":
            hints.append("trigger_backend_reconnect")
        return hints

    def _build_degraded_reasons(self) -> list[str]:
        reasons: list[str] = []
        if self.projection.bridge_backend_health in {
            "stale",
            "degraded",
            "disconnected",
        }:
            reasons.append(
                f"bridge_backend_health={self.projection.bridge_backend_health}"
            )
        if self.projection.reconnect_pressure in {"moderate", "high"}:
            reasons.append(f"reconnect_pressure={self.projection.reconnect_pressure}")
        if self.projection.consumer_error_count > 0:
            reasons.append(f"consumer_errors={self.projection.consumer_error_count}")
        if self.projection.github_rate_limit_health in {"degraded", "near_exhausted"}:
            reasons.append(
                f"github_rate_limit={self.projection.github_rate_limit_health}"
            )
        return reasons


__all__ = ["ResourceProjectionFeed"]
