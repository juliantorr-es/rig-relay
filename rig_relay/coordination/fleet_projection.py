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

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination.current_state import generate_current_state
from rig_relay.coordination.fleet_queue import FleetQueue, FleetQueueSnapshot

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


class FleetAgentDetail(BaseModel):
    """Granular summary for one agent/session in the workforce strip."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    status: str
    role: str | None = None
    last_heartbeat_age: str | None = None
    lease_summary: str | None = None


class FleetQueueNextItem(BaseModel):
    """Summary of the next runnable queue item."""

    model_config = ConfigDict(extra="forbid")

    queue_item_id: str | None = None
    kind: str | None = None
    priority: int = 0
    created_at: str | None = None


class FleetReplayDiagnostics(BaseModel):
    """Content-light replay diagnostics from queue event log."""

    model_config = ConfigDict(extra="forbid")

    total_lines: int = 0
    valid_events: int = 0
    malformed_lines: int = 0
    invalid_events: int = 0
    skipped_unknown_kind: int = 0
    total_skipped: int = 0


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
    next_item: FleetQueueNextItem | None = None
    replay: FleetReplayDiagnostics | None = None


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
    patches: FleetPatchProposalSummary = Field(
        default_factory=FleetPatchProposalSummary
    )
    agent_details: list[FleetAgentDetail] = Field(default_factory=list)
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
    agent_details: list[FleetAgentDetail] | None = None,
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

    if coordination_root is not None:
        if queue is None:
            queue = build_queue_summary(FleetQueue(coordination_root / "events.jsonl"))
        if leases is None:
            leases = build_lease_summary(coordination_root)
        if patches is None:
            patches = build_patch_proposal_summary(coordination_root)
        if agents is None:
            current_state = generate_current_state(coordination_root=coordination_root)
            summary = current_state.get("summary", {})
            agents = FleetAgentSummary(
                total_agents=summary.get("active_children", 0),
                active_sessions=summary.get("active_children", 0),
                recent_heartbeats=summary.get("active_children", 0),
                stale_sessions=summary.get("stale_leases", 0),
            )
            recent_event_count = len(current_state.get("recent_artifacts", [])) + len(
                current_state.get("recent_conflicts", [])
            )

    return FleetProjection(
        schema_version=_SCHEMA_VERSION,
        projection_id=pid,
        created_at=stamp,
        agents=agents or FleetAgentSummary(),
        queue=queue or FleetQueueSummary(),
        leases=leases or FleetLeaseSummary(),
        blockers=blockers or FleetBlockerSummary(),
        patches=patches or FleetPatchProposalSummary(),
        agent_details=agent_details or [],
        recent_event_count=recent_event_count,
    )


def _generate_projection_id(timestamp: str) -> str:
    import hashlib

    raw = f"fleet_projection:{timestamp}"
    return "fp-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


# ── Queue summary builder ──────────────────────────────────────────────


def build_queue_summary(queue: FleetQueue | None = None) -> FleetQueueSummary:
    """Build a FleetQueueSummary from a FleetQueue instance (or None).

    Reads the queue's event-sourced snapshot to produce counts, next
    runnable item summary, and replay diagnostics.

    If queue is None or the events file is missing/empty, returns
    empty-safe defaults. Never crashes.
    """
    if queue is None:
        return FleetQueueSummary()

    try:
        snapshot = queue.list_items()
    except Exception:
        return FleetQueueSummary()

    return build_queue_summary_from_snapshot(snapshot)


def build_queue_summary_from_snapshot(
    snapshot: FleetQueueSnapshot,
) -> FleetQueueSummary:
    """Build a FleetQueueSummary from an existing FleetQueueSnapshot.

    Extracts status counts, next runnable item, and replay diagnostics.
    """
    counts = snapshot.status_counts
    next_item: FleetQueueNextItem | None = None
    rr = snapshot.replay_report

    replay = (
        FleetReplayDiagnostics(
            total_lines=rr.total_lines,
            valid_events=rr.valid_events,
            malformed_lines=rr.malformed_lines,
            invalid_events=rr.invalid_events,
            skipped_unknown_kind=rr.skipped_unknown_kind,
            total_skipped=rr.total_skipped,
        )
        if rr
        else None
    )

    # Find next runnable from snapshot items

    # Use the same logic as queue.next_runnable_item but avoid circular
    # by computing from the snapshot directly
    queued_items = [i for i in snapshot.items if i.status == "queued"]
    if queued_items:
        cand = min(
            queued_items, key=lambda i: (-i.priority, i.created_at, i.queue_item_id)
        )
        next_item = FleetQueueNextItem(
            queue_item_id=cand.queue_item_id,
            kind=cand.kind,
            priority=cand.priority,
            created_at=cand.created_at,
        )

    return FleetQueueSummary(
        queued=counts.get("queued", 0),
        running=counts.get("running", 0),
        blocked=counts.get("blocked", 0),
        completed=counts.get("completed", 0),
        failed=counts.get("failed", 0),
        cancelled=counts.get("cancelled", 0),
        total=snapshot.total_count,
        highest_priority=next_item.priority if next_item else 0,
        next_item=next_item,
        replay=replay,
    )


# ── Lease summary builder ──────────────────────────────────────────────


def build_lease_summary(coordination_root: Path | None = None) -> FleetLeaseSummary:
    """Build a FleetLeaseSummary from a coordination root path.

    Reads active leases from PathLeaseManager. Returns empty-safe
    defaults if coordination_root is None, path doesn't exist, or
    reading fails in any way.
    """
    if coordination_root is None:
        return FleetLeaseSummary()

    try:
        from rig_relay.coordination.lease_manager import PathLeaseManager

        path_manager = PathLeaseManager(coordination_root)
        leases = path_manager.query_active_leases()
    except Exception:
        return FleetLeaseSummary()

    return FleetLeaseSummary(
        total_active=len(leases),
        exclusive_write=sum(1 for l in leases if l.mode == "write"),
        shared_read=sum(1 for l in leases if l.mode == "read"),
        path_count=sum(len(l.paths) for l in leases),
    )


# ── Patch proposal summary builder ─────────────────────────────────────


def build_patch_proposal_summary(
    patch_root: Path | None = None,
) -> FleetPatchProposalSummary:
    """Build a FleetPatchProposalSummary from a patch metadata directory.

    Scans .fleet/patch-proposals/*.json for proposal files. Returns
    empty-safe defaults if patch_root is None, doesn't exist, or
    reading fails.
    """
    if patch_root is None or not patch_root.exists():
        return FleetPatchProposalSummary()

    try:
        import json

        proposals_dir = patch_root / ".fleet" / "patch-proposals"
        if not proposals_dir.is_dir():
            return FleetPatchProposalSummary()

        pending = 0
        applied = 0
        rejected = 0
        revised = 0
        total = 0
        oldest_pending_at: str | None = None
        latest_proposal_id: str | None = None

        for path in sorted(proposals_dir.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                total += 1
                status = data.get("status", "")
                created = data.get("created_at", "")
                pid = data.get("proposal_id", "")
                if status == "pending":
                    pending += 1
                    if oldest_pending_at is None or created < oldest_pending_at:
                        oldest_pending_at = created
                elif status == "applied":
                    applied += 1
                elif status == "rejected":
                    rejected += 1
                elif status == "revised":
                    revised += 1
                latest_proposal_id = pid
            except Exception:
                continue

        return FleetPatchProposalSummary(
            pending=pending,
            applied=applied,
            rejected=rejected,
            revised=revised,
            total=total,
            oldest_pending_at=oldest_pending_at,
            latest_proposal_id=latest_proposal_id,
        )
    except Exception:
        return FleetPatchProposalSummary()


__all__ = [
    "FleetAgentSummary",
    "FleetBlockerSummary",
    "FleetLeaseSummary",
    "FleetPatchProposalSummary",
    "FleetProjection",
    "FleetQueueNextItem",
    "FleetQueueSummary",
    "FleetReplayDiagnostics",
    "build_fleet_projection",
    "build_lease_summary",
    "build_patch_proposal_summary",
    "build_queue_summary",
    "build_queue_summary_from_snapshot",
]
