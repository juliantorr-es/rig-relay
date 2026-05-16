"""RalphReport — durable report from Ralph to orchestrator.

Ralph delivers reports when lanes are sealed, blocked, or produce risks.
Reports are stored and listed for orchestrator review consumption.
Not a normal subagent assignment — Ralph reports autonomously.

Content-light: IDs, hashes, status enums. No raw payloads.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

REPORT_VERSION = "rig.ralph_report.v1"


class RalphReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = REPORT_VERSION
    report_id: str = Field(default_factory=lambda: str(uuid4()))
    report_kind: str = "completed_lane"
    ralph_lane_id: str | None = None
    branch_name: str | None = None
    commit_shas: list[str] = Field(default_factory=list)
    review_bundle_sha256: str | None = None
    adoption_proposal_id: str | None = None
    title: str = ""
    summary: str = ""
    why: str = ""
    source_refs: list[dict[str, str]] = Field(default_factory=list)
    target_assignment_id: str | None = None
    target_orchestrator_lane_id: str | None = None
    relevance_score: float | None = None
    status: str = "created"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    delivered_at: str | None = None
    reviewed_at: str | None = None
    merge_enabled: bool = False
    push_enabled: bool = False


class RalphReportStore:
    def __init__(self) -> None:
        self._reports: dict[str, RalphReport] = {}

    def save_report(self, report: RalphReport) -> RalphReport:
        self._reports[report.report_id] = report
        return report

    def load_report(self, report_id: str) -> RalphReport | None:
        return self._reports.get(report_id)

    def list_pending_reports(self) -> list[RalphReport]:
        return [
            r
            for r in self._reports.values()
            if r.status not in ("reviewed", "deferred", "rejected")
        ]

    def list_by_status(self, status: str) -> list[RalphReport]:
        return [r for r in self._reports.values() if r.status == status]

    def mark_delivered(self, report_id: str) -> RalphReport | None:
        r = self._reports.get(report_id)
        if r:
            r.status = "delivered_to_orchestrator"
            r.delivered_at = datetime.now(UTC).isoformat()
        return r

    def mark_reviewed(self, report_id: str) -> RalphReport | None:
        r = self._reports.get(report_id)
        if r:
            r.status = "reviewed"
            r.reviewed_at = datetime.now(UTC).isoformat()
        return r

    def mark_deferred(self, report_id: str) -> RalphReport | None:
        r = self._reports.get(report_id)
        if r:
            r.status = "deferred"
        return r

    def mark_rejected(self, report_id: str) -> RalphReport | None:
        r = self._reports.get(report_id)
        if r:
            r.status = "rejected"
        return r

    def mark_accepted_for_adoption(self, report_id: str) -> RalphReport | None:
        r = self._reports.get(report_id)
        if r:
            r.status = "accepted_for_adoption"
        return r

    def list_all(self) -> list[RalphReport]:
        return list(self._reports.values())


def build_demo_ralph_reports() -> list[RalphReport]:
    return [
        RalphReport(
            report_id="ralph-report-demo-1",
            report_kind="completed_lane",
            ralph_lane_id="ralph_lane_demo_1",
            branch_name="ralph/guard-singleton-fix-a1b2",
            commit_shas=["abc123def456"],
            review_bundle_sha256="sha256:bundle1",
            title="DirtyFileGuard singleton ownership fix completed",
            summary="Identified shared guard singleton across forked agents. Prepared fix in isolated lane.",
            why="Triggered by finding_20260513_dirty_guard_singleton",
            source_refs=[
                {"kind": "finding", "id": "finding_20260513_dirty_guard_singleton"}
            ],
            target_assignment_id="assignment-runtime-agent-1",
            relevance_score=0.9,
            status="created",
        ),
        RalphReport(
            report_id="ralph-report-demo-2",
            report_kind="convergence_seam",
            ralph_lane_id="ralph_lane_demo_2",
            branch_name="ralph/agentloop-kernel-boundary-c3d4",
            commit_shas=["def789abc012"],
            review_bundle_sha256="sha256:bundle2",
            title="AgentLoop runtime kernel boundary seam identified",
            summary="Multiple architecture seams converge on AgentLoop. Prepared boundary documentation and lane proposal.",
            why="Triggered by finding_20260514_agent_loop_runtime_kernel",
            source_refs=[
                {"kind": "finding", "id": "finding_20260514_agent_loop_runtime_kernel"}
            ],
            status="created",
        ),
    ]


__all__ = [
    "REPORT_VERSION",
    "RalphReport",
    "RalphReportStore",
    "build_demo_ralph_reports",
]
