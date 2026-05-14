"""FleetProjection — content-light read model for the fleet coordination plane.

Summarizes queue state, active leases, blockers, patch proposals, and
agent/session liveness from existing fleet/coordination artifacts.

All sub-models have extra="forbid" and carry only IDs, statuses, counts,
hashes, sanitized reasons, timestamps, and path refs/hashes.

No raw stdout, stderr, content, diffs, patches, prompts, secrets, argv,
or snippets.

Missing artifacts (queue not yet created, no lease store, no patches)
produce empty-safe defaults — never crash.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ── Constants ──────────────────────────────────────────────────────────

_SCHEMA_VERSION = "rig.fleet.projection.v1"
_MAX_RECENT_EVENTS = 50


# ── Sub-models ─────────────────────────────────────────────────────────


class FleetAgentSummary(BaseModel):
    """Summary of active agents/sessions in the fleet."""

    model_config = ConfigDict(extra="forbid")

    total_agents: int = 0
    active_sessions: int = 0
    recent_heartbeats: int = 0
    stale_sessions: int = 0


class FleetQueueSummary(BaseModel):
    """Summary of queue state — counts by status."""

    model_config = ConfigDict(extra="forbid")

    queued: int = 0
    running: int = 0
    blocked: int = 0
    completed: int = 0
    failed: int = 0
    cancelled: int = 0
    total: int = 0
    highest_priority: int = 0


class FleetLeaseSummary(BaseModel):
    """Summary of active leases."""

    model_config = ConfigDict(extra="forbid")

    total_active: int = 0
    exclusive_write: int = 0
    shared_read: int = 0
    stale: int = 0
    expired: int = 0
    path_count: int = 0


class FleetBlockerSummary(BaseModel):
    """Summary of current blockers."""

    model_config = ConfigDict(extra="forbid")

    total_blockers: int = 0
    blocker_kinds: dict[str, int] = Field(default_factory=dict)
    oldest_blocked_at: str | None = None


class FleetPatchProposalSummary(BaseModel):
    """Summary of pending patch proposals."""

    model_config = ConfigDict(extra="forbid")

    pending: int = 0
    applied: int = 0
    rejected: int = 0
    revised: int = 0
    total: int = 0
    oldest_pending_at: str | None = None
    latest_proposal_id: str | None = None


# ── Root model ─────────────────────────────────────────────────────────


class FleetProjection(BaseModel):
    """Content-light read model for the fleet coordination plane.

    Built from available fleet/coordination artifacts. Returns empty-safe
    defaults when artifacts are missing or not yet implemented.

    Deferred integrations (not yet wired, always return default):
    - queue: FleetQueueSummary (0/empty) until queue runner is present
    - patches: FleetPatchProposalSummary (0/empty) until patch review UI is built
    - agents: FleetAgentSummary (0/empty) until session registry is wired
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    projection_id: str
    created_at: str
    fleet_name: str = "default"
    agents: FleetAgentSummary = Field(default_factory=FleetAgentSummary)
    queue: FleetQueueSummary = Field(default_factory=FleetQueueSummary)
    leases: FleetLeaseSummary = Field(default_factory=FleetLeaseSummary)
    blockers: FleetBlockerSummary = Field(default_factory=FleetBlockerSummary)
    patches: FleetPatchProposalSummary = Field(default_factory=FleetPatchProposalSummary)
    recent_event_count: int = 0


# ── Builder ────────────────────────────────────────────────────────────


def build_fleet_projection(
    *,
    coordination_root: Path | None = None,
    queue: FleetQueueSummary | None = None,
    leases: FleetLeaseSummary | None = None,
    blockers: FleetBlockerSummary | None = None,
    patches: FleetPatchProposalSummary | None = None,
    agents: FleetAgentSummary | None = None,
    recent_event_count: int = 0,
    projection_id: str | None = None,
    created_at: str | None = None,
) -> FleetProjection:
    """Build a FleetProjection from available fleet/coordination artifacts.

    All parameters are optional. Missing or None inputs produce empty-safe
    defaults. The builder never crashes on missing roots, missing files,
    or not-yet-implemented subsystems.

    For Phase 0, the following subsystems return empty defaults:
    - agents: not yet wired (needs session registry)
    - queue: not yet wired (needs queue runner integration)
    - patches: not yet wired (needs patch review UI)
    - blockers: not yet wired (needs blocker detection logic)

    Args:
        coordination_root: Path to the coordination store root. Currently
            unused in Phase 0 — reserved for future lease/blocker reading.
        queue: Pre-built FleetQueueSummary (built externally from
            FleetQueueSnapshot if available). None → empty default.
        leases: Pre-built FleetLeaseSummary (built externally from
            PathLeaseManager/ExecutionLeaseStore if available).
            None → empty default.
        blockers: Pre-built FleetBlockerSummary. None → empty default.
        patches: Pre-built FleetPatchProposalSummary. None → empty default.
        agents: Pre-built FleetAgentSummary. None → empty default.
        recent_event_count: Count of recent coordination events.
        projection_id: Optional explicit ID. Auto-generated from timestamp.
        created_at: Optional ISO 8601 timestamp. Auto-generated.

    Returns:
        A content-light FleetProjection with all fields populated.
    """
    stamp = created_at or datetime.now(UTC).isoformat()
    pid = projection_id or _generate_projection_id(stamp)

    return FleetProjection(
        schema_version=_SCHEMA_VERSION,
        projection_id=pid,
        created_at=stamp,
        agents=agents or FleetAgentSummary(),
        queue=queue or FleetQueueSummary(),
        leases=leases or FleetLeaseSummary(),
        blockers=blockers or FleetBlockerSummary(),
        patches=patches or FleetPatchProposalSummary(),
        recent_event_count=recent_event_count,
    )


def _generate_projection_id(timestamp: str) -> str:
    import hashlib

    raw = f"fleet_projection:{timestamp}"
    return "fp-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


__all__ = [
    "FleetAgentSummary",
    "FleetBlockerSummary",
    "FleetLeaseSummary",
    "FleetPatchProposalSummary",
    "FleetProjection",
    "FleetQueueSummary",
    "build_fleet_projection",
]
