"""Session pane projection — content-light derived state for one session card.

Projections are backend-authored, frontend-rendered state summaries. They
contain no raw stdout, stderr, file contents, diffs, command transcripts,
or secrets — only metadata, counts, hashes, and structured summaries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.coordination.fleet_projection import FleetProjection
from rig_relay.desktop.execution_progress import ExecutionProgressProjection
from rig_relay.evidence.receipt_index import ToolReceiptIndexRecord
from rig_relay.runtime.runtime_audit_event import RuntimeAuditEvent
from rig_relay.runtime.runtime_supervisor_projection import RuntimeSupervisorProjection

_EVIDENCE_RAIL_CAP = 20
_DASHBOARD_BACKLOG_CAP = 5
_INSPECTOR_ITEM_CAP = 30


class SessionPaneProjection(BaseModel):
    """Content-light projection for one session card in the Rig console.

    All fields are derived from backend state — coordination leases,
    receipts, validate profiles, and git state. No raw tool output or
    file contents are exposed.

    Missing data degrades to None or 0 — never fabricated.
    """

    model_config = ConfigDict(extra="forbid")

    # ── Identity ──────────────────────────────────────────────────
    session_id: str
    lane_id: str | None = None
    task_title: str | None = None

    # ── Status ────────────────────────────────────────────────────
    status: str = "unknown"
    branch_name: str | None = None
    worktree_path: str | None = None
    last_heartbeat_at: str | None = None
    current_step: str | None = None

    # ── Validate ──────────────────────────────────────────────────
    validate_status: str | None = None
    blocker_summary: dict[str, int] = {}

    # ── Receipts ──────────────────────────────────────────────────
    receipt_count: int = 0
    latest_receipt_kind: str | None = None
    changed_paths: list[str] = Field(default_factory=list)

    # ── User interaction ──────────────────────────────────────────
    pending_user_action: str | None = None

    def with_heartbeat(self, *, now: datetime | None = None) -> SessionPaneProjection:
        """Return a copy with an updated heartbeat timestamp."""
        ts = (now or datetime.now(UTC)).isoformat()
        return self.model_copy(update={"last_heartbeat_at": ts})

    def with_blocker(
        self, blockers: dict[str, int] | None = None
    ) -> SessionPaneProjection:
        """Return a copy with updated blocker summary and validate status."""
        return self.model_copy(
            update={"blocker_summary": blockers or {}, "validate_status": "blocked"}
        )

    def with_receipt(self, kind: str) -> SessionPaneProjection:
        """Return a copy incrementing receipt count and updating latest kind."""
        return self.model_copy(
            update={
                "receipt_count": self.receipt_count + 1,
                "latest_receipt_kind": kind,
            }
        )

    def sort_changed_paths(self, max_paths: int = 5) -> SessionPaneProjection:
        """Return a copy with changed paths sorted and capped."""
        capped = sorted(self.changed_paths)[:max_paths]
        return self.model_copy(update={"changed_paths": capped})

    def to_display_dict(self) -> dict[str, Any]:
        """Return a plain dict suitable for widget rendering.

        Ensures no raw content fields leak into display data.
        """
        return self.model_dump(mode="json", exclude_none=True)


class EvidenceRailItemProjection(BaseModel):
    """Content-light projection for one receipt item in the evidence rail.

    Contains no raw tool output, file contents, diffs, or secrets —
    only metadata, status, and structured classification.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str | None = None
    captured_at: str | None = None
    tool_name: str
    status: str
    error_kind: str | None = None
    path: str | None = None
    changed: bool | None = None
    duration_ms: float | None = None


class EvidenceRailProjection(BaseModel):
    """Content-light projection for the evidence rail widget.

    Summarises a session's receipt activity without exposing raw
    tool output, file contents, diffs, or command transcripts.
    """

    model_config = ConfigDict(extra="forbid")

    session_id: str
    receipt_count: int = 0
    mutation_count: int = 0
    refusal_count: int = 0
    timeout_count: int = 0
    items: list[EvidenceRailItemProjection] = Field(default_factory=list)


def evidence_rail_from_receipt_index(
    records: list[ToolReceiptIndexRecord],
    session_id: str,
    max_items: int = _EVIDENCE_RAIL_CAP,
) -> EvidenceRailProjection:
    """Build an EvidenceRailProjection from a list of ToolReceiptIndexRecord objects.

    Content-safe adapter: extracts only metadata fields. Does not read
    files, parse JSONL, or expose raw output.

    Items are ordered by captured_at (descending) when available, then capped.
    """
    mutation_count = 0
    refusal_count = 0
    timeout_count = 0
    items: list[EvidenceRailItemProjection] = []

    for record in records:
        if record.tool_name == "search_replace" and record.changed:
            mutation_count += 1
        if record.status == "refused":
            refusal_count += 1
        if record.status == "timed_out" or (
            record.tool_name == "bash" and record.error_kind == "timeout"
        ):
            timeout_count += 1

        items.append(
            EvidenceRailItemProjection(
                event_id=record.event_id,
                captured_at=record.captured_at,
                tool_name=record.tool_name,
                status=record.status or "unknown",
                error_kind=record.error_kind,
                path=record.path,
                changed=record.changed,
                duration_ms=record.duration_ms,
            )
        )

    # Sort by captured_at descending, None last
    def _sort_key(item: EvidenceRailItemProjection) -> str:
        return item.captured_at or ""

    items.sort(key=_sort_key, reverse=True)
    items = items[:max_items]

    return EvidenceRailProjection(
        session_id=session_id,
        receipt_count=len(items),
        mutation_count=mutation_count,
        refusal_count=refusal_count,
        timeout_count=timeout_count,
        items=items,
    )


class InspectorItemProjection(BaseModel):
    """Content-light summary for one selected inspector item."""

    model_config = ConfigDict(extra="forbid")

    item_id: str
    source_kind: str
    title: str
    status: str | None = None
    tool_name: str | None = None
    created_at: str | None = None
    duration_ms: float | None = None
    changed_paths: list[str] = Field(default_factory=list)
    receipt_sha256: str | None = None
    runtime_result_sha256: str | None = None
    error_kind: str | None = None
    refusal_reason: str | None = None
    path: str | None = None
    summary: str | None = None


class InspectorProjection(BaseModel):
    """Projection for the inspector drawer."""

    model_config = ConfigDict(extra="forbid")

    visible: bool = False
    selected_index: int = 0
    empty_state: str = "No item selected"
    items: list[InspectorItemProjection] = Field(default_factory=list)

    @property
    def selected_item(self) -> InspectorItemProjection | None:
        if not self.items:
            return None
        index = max(0, min(self.selected_index, len(self.items) - 1))
        return self.items[index]


def _build_inspector_audit_item(event: RuntimeAuditEvent) -> InspectorItemProjection:
    summary = f"{event.status} {event.tool_name}"
    return InspectorItemProjection(
        item_id=event.audit_event_id,
        source_kind="runtime_audit",
        title=f"Audit {event.tool_name}",
        status=event.status,
        tool_name=event.tool_name,
        created_at=event.created_at,
        duration_ms=event.duration_ms,
        changed_paths=list(event.changed_paths),
        receipt_sha256=event.receipt_sha256,
        runtime_result_sha256=event.runtime_result_sha256,
        error_kind=event.error_kind,
        refusal_reason=event.refusal_reason,
        summary=summary,
    )


def _build_inspector_evidence_item(
    item: EvidenceRailItemProjection,
) -> InspectorItemProjection:
    item_id = item.event_id or f"{item.tool_name}:{item.captured_at or 'unknown'}"
    summary = f"{item.status} {item.tool_name}"
    return InspectorItemProjection(
        item_id=item_id,
        source_kind="receipt",
        title=f"Receipt {item.tool_name}",
        status=item.status,
        tool_name=item.tool_name,
        created_at=item.captured_at,
        duration_ms=item.duration_ms,
        changed_paths=[item.path] if item.path else [],
        error_kind=item.error_kind,
        path=item.path,
        summary=summary,
    )


def _build_inspector_blocker_item(
    session: SessionPaneProjection,
) -> InspectorItemProjection | None:
    if not session.blocker_summary:
        return None
    summary = ", ".join(
        f"{count} {name}" for name, count in sorted(session.blocker_summary.items())
    )
    return InspectorItemProjection(
        item_id=f"{session.session_id}:blockers",
        source_kind="lease_blocker",
        title="Active Leases / Blockers",
        status=session.validate_status or "blocked",
        created_at=session.last_heartbeat_at,
        refusal_reason=summary,
        summary=summary,
    )


def build_inspector_projection(
    session: SessionPaneProjection,
    evidence: EvidenceRailProjection,
    supervisor: RuntimeSupervisorProjection | None = None,
) -> InspectorProjection:
    """Build a content-light inspector projection from current dashboard state."""
    items: list[InspectorItemProjection] = []

    if supervisor is not None:
        for event in supervisor.recent_invocations:
            items.append(_build_inspector_audit_item(event))

    blocker_item = _build_inspector_blocker_item(session)
    if blocker_item is not None:
        items.append(blocker_item)

    for item in evidence.items:
        items.append(_build_inspector_evidence_item(item))

    return InspectorProjection(items=items[:_INSPECTOR_ITEM_CAP])


class DashboardProjection(BaseModel):
    """Content-light projection for the DashboardScreen.

    Composes session pane, evidence rail, header metadata, footer
    hints, backlog items, and optional execution progress — all
    derived from backend state.
    No raw logs, file contents, diffs, or command transcripts.
    """

    model_config = ConfigDict(extra="forbid")

    title: str
    subtitle: str | None = None
    session: SessionPaneProjection
    evidence: EvidenceRailProjection
    safety_state: str | None = None
    footer_hint: str | None = None
    backlog_items: list[str] = Field(default_factory=list)
    execution_progress: ExecutionProgressProjection | None = None
    inspector: InspectorProjection = Field(default_factory=InspectorProjection)
    fleet: FleetProjection | None = None

    @property
    def backlog_capped(self) -> list[str]:
        """Return backlog items capped at _DASHBOARD_BACKLOG_CAP."""
        return self.backlog_items[:_DASHBOARD_BACKLOG_CAP]
