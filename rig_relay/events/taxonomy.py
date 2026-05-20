from __future__ import annotations

_BRIDGE_EVENTS = [
    "bridge.connection.begin",
    "bridge.auth.succeeded",
    "bridge.backend_loop.started",
    "bridge.status.updated",
    "bridge.first_status.sent",
    "bridge.heartbeat.sent",
    "bridge.backend_stale.detected",
    "bridge.disconnect",
    "bridge.backend_loop.stopped",
    "bridge.projection_loop.error",
]

_PROJECTION_EVENTS = [
    "projection.first_content_sent",
    "projection.changed",
    "projection.unchanged_for_interval",
    "projection.stale",
    "projection.fresh",
]

_RUNTIME_EVENTS = [
    "runtime.queue_pressure.high",
    "runtime.queue_pressure.normal",
    "runtime.backpressure.threshold_reached",
]

_SUPERVISOR_EVENTS = [
    "supervisor.spawn.started",
    "supervisor.spawn.completed",
    "supervisor.spawn.failed",
    "supervisor.cancelled",
    "supervisor.timed_out",
    "supervisor.stall_detected",
    "supervisor.orphaned_loop_detected",
]

_WORKER_EVENTS = [
    "worker.claimed",
    "worker.completed",
    "worker.failed",
    "worker.file_lease_conflict",
    "worker.capacity.available",
]

_TOOL_EVENTS = [
    "tool.invocation.started",
    "tool.invocation.completed",
    "tool.invocation.failed",
    "tool.invocation.blocked_by_policy",
    "tool.receipt.emitted",
]

_GITHUB_EVENTS = [
    "github.permission.audit.completed",
    "github.rate_limit.near_exhausted",
    "github.rate_limit.restored",
    "github.webhook.delivery_failed",
    "github.webhook.dead_lettered",
    "github.public_surface.preview_ready",
    "github.pr_publish.blocked_by_permission",
]

_TELEMETRY_EVENTS = [
    "telemetry.event_batch_appended",
    "telemetry.file_size_threshold_reached",
    "telemetry.opt_out_detected",
    "telemetry.consent_restored",
]

_REDACTION_EVENTS = [
    "redaction.match_detected",
    "redaction.quarantine_triggered",
    "redaction.quarantine_cleared",
]

_RELEASE_GATE_EVENTS = [
    "release_gate.check_passed",
    "release_gate.check_failed",
    "release_gate.blocked",
    "release_gate.evidence_converged",
]

_TEST_EVENTS = [
    "test.intent.declared",
    "test.started",
    "test.finished",
    "test.targeted_passed",
    "test.pressure.high",
    "test.final_validation_justified",
]

_COORDINATION_EVENTS = [
    "coordination.lease.conflict_detected",
    "coordination.lease.reclaimed",
    "coordination.artifact.published",
    "coordination.handoff.requested",
    "coordination.handoff.completed",
]

_RESOURCE_EVENTS = [
    "resource.cpu_pressure.high",
    "resource.test_budget.exhausted",
    "resource.github_budget.degraded",
    "resource.worker_capacity.available",
    "resource.frontend_refresh.degraded",
]

_POLICY_EVENTS = [
    "policy.decision.blocked",
    "policy.decision.allowed",
    "policy.decision.requires_review",
]

SEEDED_EVENT_TYPES: list[str] = sorted(
    _BRIDGE_EVENTS
    + _PROJECTION_EVENTS
    + _RUNTIME_EVENTS
    + _SUPERVISOR_EVENTS
    + _WORKER_EVENTS
    + _TOOL_EVENTS
    + _GITHUB_EVENTS
    + _TELEMETRY_EVENTS
    + _REDACTION_EVENTS
    + _RELEASE_GATE_EVENTS
    + _TEST_EVENTS
    + _COORDINATION_EVENTS
    + _RESOURCE_EVENTS
    + _POLICY_EVENTS
)

EVENT_TYPE_CATEGORIES: dict[str, list[str]] = {
    "bridge": _BRIDGE_EVENTS,
    "projection": _PROJECTION_EVENTS,
    "runtime": _RUNTIME_EVENTS,
    "supervisor": _SUPERVISOR_EVENTS,
    "worker": _WORKER_EVENTS,
    "tool": _TOOL_EVENTS,
    "github": _GITHUB_EVENTS,
    "telemetry": _TELEMETRY_EVENTS,
    "redaction": _REDACTION_EVENTS,
    "release_gate": _RELEASE_GATE_EVENTS,
    "test": _TEST_EVENTS,
    "coordination": _COORDINATION_EVENTS,
    "resource": _RESOURCE_EVENTS,
    "policy": _POLICY_EVENTS,
}

__all__ = ["EVENT_TYPE_CATEGORIES", "SEEDED_EVENT_TYPES"]
