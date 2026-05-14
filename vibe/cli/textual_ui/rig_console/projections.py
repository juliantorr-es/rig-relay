"""Session pane projection — content-light derived state for one session card.

Projections are backend-authored, frontend-rendered state summaries. They
contain no raw stdout, stderr, file contents, diffs, command transcripts,
or secrets — only metadata, counts, hashes, and structured summaries.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.evidence.receipt_index import ToolReceiptIndexRecord

_EVIDENCE_RAIL_CAP = 20
_DASHBOARD_BACKLOG_CAP = 5


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


class DashboardProjection(BaseModel):
    """Content-light projection for the DashboardScreen.

    Composes session pane, evidence rail, header metadata, footer
    hints, and backlog items — all derived from backend state.
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

    @property
    def backlog_capped(self) -> list[str]:
        """Return backlog items capped at _DASHBOARD_BACKLOG_CAP."""
        return self.backlog_items[:_DASHBOARD_BACKLOG_CAP]
