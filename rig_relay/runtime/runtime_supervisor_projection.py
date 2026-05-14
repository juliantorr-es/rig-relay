"""RuntimeSupervisorProjection — content-light projection of runtime execution state.

Derived from RuntimeAuditEvent records, not raw tool payloads. Summarizes
recent invocations, status counts, and changed path activity for display
in projections or dashboards.

Content-light: no raw stdout, stderr, file contents, diffs, snippets,
or secrets. Only aggregated counts, status summaries, and hashed path refs.
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.runtime.runtime_audit_event import (
    RuntimeAuditEvent,
    RuntimeAuditPersistenceStore,
)

# ── Constants ──────────────────────────────────────────────────────────

_SCHEMA_VERSION = "rig.relay.runtime_supervisor_projection.v1"

_MAX_RECENT_INVOCATIONS = 20


# ── Model ─────────────────────────────────────────────────────────────


class RuntimeSupervisorProjection(BaseModel):
    """Content-light summary projection of runtime execution state.

    Derived from RuntimeAuditEvent records. Contains no raw payloads,
    only aggregated counts, recent invocations (content-light), and
    timestamp.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = _SCHEMA_VERSION
    projection_id: str
    created_at: str
    total_invocations: int = 0
    status_counts: dict[str, int] = Field(default_factory=dict)
    recent_invocations: list[RuntimeAuditEvent] = Field(default_factory=list)
    changed_path_count: int = 0
    changed_path_hashes: list[str] = Field(default_factory=list)


# ── Builder ───────────────────────────────────────────────────────────


def build_runtime_supervisor_projection(
    store_or_events: RuntimeAuditPersistenceStore | list[RuntimeAuditEvent],
    *,
    max_recent: int = _MAX_RECENT_INVOCATIONS,
    projection_id: str | None = None,
    created_at: str | None = None,
) -> RuntimeSupervisorProjection:
    """Build a RuntimeSupervisorProjection from audit events.

    Args:
        store_or_events: Either a RuntimeAuditPersistenceStore (reads
            all events) or a list of RuntimeAuditEvent instances.
        max_recent: Maximum number of recent invocations to include.
        projection_id: Optional explicit projection ID. Auto-generated
            from timestamp if omitted.
        created_at: Optional ISO 8601 timestamp. Auto-generated if omitted.

    Returns:
        A content-light RuntimeSupervisorProjection.
    """
    stamp = created_at or datetime.now(UTC).isoformat()
    pid = projection_id or _generate_projection_id(stamp)

    # Resolve events
    if isinstance(store_or_events, RuntimeAuditPersistenceStore):
        events = store_or_events.read_events()
    else:
        events = store_or_events

    # Status counts
    status_counts: dict[str, int] = {}
    changed_path_hashes: set[str] = set()
    for event in events:
        status = event.status
        status_counts[status] = status_counts.get(status, 0) + 1
        if event.runtime_result_sha256:
            changed_path_hashes.add(event.runtime_result_sha256)

    # Recent invocations (most recent first, capped)
    sorted_events = sorted(events, key=lambda e: e.created_at, reverse=True)
    recent = sorted_events[:max_recent]

    # Changed path count from recent events
    changed_path_count = sum(len(e.changed_paths) for e in recent)

    return RuntimeSupervisorProjection(
        schema_version=_SCHEMA_VERSION,
        projection_id=pid,
        created_at=stamp,
        total_invocations=len(events),
        status_counts=status_counts,
        recent_invocations=recent,
        changed_path_count=changed_path_count,
        changed_path_hashes=sorted(changed_path_hashes),
    )


def _generate_projection_id(timestamp: str) -> str:
    """Generate a content-addressed projection ID."""
    import hashlib

    raw = f"projection:{timestamp}"
    return "proj-" + hashlib.sha256(raw.encode()).hexdigest()[:16]


__all__ = ["RuntimeSupervisorProjection", "build_runtime_supervisor_projection"]
