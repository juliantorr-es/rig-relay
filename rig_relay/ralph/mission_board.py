"""Orchestrator mission board — composite projection for pywebview demo.

Three workstreams:
1. Assigned Subagent Lanes — missions assigned to configured subagent profiles
2. Ralph Background Reports — autonomous convergence work completed by Ralph
3. Review Entrypoint — review completed Ralph work with orchestrator

Content-light: IDs, statuses, hashes, counts. No raw payloads.
Backend owns all policy. Frontend is a dumb renderer.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

BOARD_VERSION = "rig.ui.orchestrator_mission_board.v2"


class MissionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mission_id: str = ""
    title: str = ""
    status: str = "pending"
    assigned_profile_id: str = ""
    assigned_profile_name: str = ""
    lane_id: str = ""


class SubagentLaneItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_id: str = ""
    display_name: str = ""
    profile_kind: str = ""
    role: str = ""
    active_missions: int = 0
    max_concurrent: int = 1
    status: str = "idle"
    lane_id: str | None = None

    model_binding_id: str = ""
    model_binding_label: str = ""
    provider_id: str = ""
    provider_status: str = "demo_local"
    requires_api_key: bool = False


class RalphReportItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    report_id: str = ""
    report_kind: str = ""
    title: str = ""
    ralph_lane_id: str = ""
    branch_name: str | None = None
    status: str = ""
    relevance_score: float = 0.0
    requires_orchestrator_review: bool = True


class LifecycleTimelineEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_order: int = 0
    status: str = "pending"
    label: str = ""
    detail: str = ""
    blocked: bool = False


class ReviewEntrypoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    available: bool = False
    pending_review_count: int = 0
    latest_report_id: str = ""
    label: str = ""
    action: str = "review_with_orchestrator"
    requires_confirmation: bool = False


class OrchestratorMissionBoard(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = BOARD_VERSION
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    active_sprint: str = "current"
    total_missions: int = 0
    active_missions: int = 0
    completed_missions: int = 0

    missions: list[MissionItem] = Field(default_factory=list)

    assigned_subagent_lanes: list[SubagentLaneItem] = Field(default_factory=list)
    active_assignments: list[MissionItem] = Field(default_factory=list)

    ralph_reports: list[RalphReportItem] = Field(default_factory=list)
    pending_ralph_report_count: int = 0
    latest_ralph_report: RalphReportItem | None = None

    lifecycle_timeline: list[LifecycleTimelineEntry] = Field(default_factory=list)
    background_enabled: bool = False

    isolated_lane_execution_enabled: bool = False
    live_runtime_mutation_enabled: bool = False
    merge_enabled: bool = False
    push_enabled: bool = False

    review_entrypoint: ReviewEntrypoint | None = None

    available_actions: list[dict[str, str | bool]] = Field(
        default_factory=lambda: [
            {
                "action": "orchestrator_new_mission",
                "label": "New mission",
                "requires_confirmation": True,
            },
            {
                "action": "orchestrator_assign_sprint",
                "label": "Assign sprint to subagents",
                "requires_confirmation": True,
            },
            {
                "action": "ralph_scan",
                "label": "Ralph scan",
                "requires_confirmation": False,
            },
            {
                "action": "review_with_orchestrator",
                "label": "Review with orchestrator",
                "requires_confirmation": True,
            },
        ]
    )


def build_mission_board(
    missions: list[dict[str, Any]] | None = None,
    subagent_profiles: list[Any] | None = None,
    subagent_bindings: list[Any] | None = None,
    subagent_assignments: list[dict[str, Any]] | None = None,
    ralph_reports: list[Any] | None = None,
    lifecycle: dict[str, Any] | None = None,
    pending_review_count: int = 0,
    background_enabled: bool = False,
) -> OrchestratorMissionBoard:
    mission_items: list[MissionItem] = []
    for m in missions or []:
        mission_items.append(
            MissionItem(
                mission_id=m.get("mission_id", ""),
                title=m.get("title", ""),
                status=m.get("status", "pending"),
                assigned_profile_id=m.get("assigned_profile_id", ""),
                assigned_profile_name=m.get("assigned_profile_name", ""),
                lane_id=m.get("lane_id", ""),
            )
        )

    if not mission_items:
        mission_items = [
            MissionItem(
                mission_id="demo-mission-1",
                title="Extract ToolRuntime boundary from AgentLoop",
                status="active",
                assigned_profile_id="profile-runtime-agent",
                assigned_profile_name="Runtime Agent",
                lane_id="lane-runtime-agent",
            ),
            MissionItem(
                mission_id="demo-mission-2",
                title="Wire Ralph lifecycle into pywebview",
                status="active",
                assigned_profile_id="profile-frontend-agent",
                assigned_profile_name="Frontend Agent",
                lane_id="lane-frontend-agent",
            ),
        ]

    subagent_lanes = _build_subagent_lanes(
        subagent_profiles or [], subagent_bindings or []
    )
    active_assignments = [
        m for m in mission_items if m.status in {"active", "assigned", "in_progress"}
    ]

    ralph_report_items = _build_ralph_report_items(ralph_reports or [])
    pending = [
        r
        for r in ralph_report_items
        if r.status in {"created", "delivered_to_orchestrator"}
    ]
    latest = pending[0] if pending else None

    timeline = _build_lifecycle_timeline(lifecycle or {}, background_enabled)

    effective_pending = pending_review_count or len(pending)
    review = None
    if effective_pending > 0:
        label_suffix = "Ralph report" if effective_pending == 1 else "Ralph reports"
        review = ReviewEntrypoint(
            available=True,
            pending_review_count=effective_pending,
            latest_report_id=latest.report_id if latest else "",
            label=f"Review {effective_pending} {label_suffix} with orchestrator",
            action="review_with_orchestrator",
            requires_confirmation=True,
        )

    return OrchestratorMissionBoard(
        total_missions=len(mission_items),
        active_missions=sum(1 for m in mission_items if m.status == "active"),
        completed_missions=sum(1 for m in mission_items if m.status == "completed"),
        missions=mission_items,
        assigned_subagent_lanes=subagent_lanes,
        active_assignments=active_assignments,
        ralph_reports=ralph_report_items,
        pending_ralph_report_count=len(pending),
        latest_ralph_report=latest,
        lifecycle_timeline=timeline,
        background_enabled=background_enabled,
        isolated_lane_execution_enabled=(
            lifecycle.get("isolated_lane_execution_enabled", False)
            if lifecycle
            else False
        ),
        live_runtime_mutation_enabled=False,
        merge_enabled=lifecycle.get("merge_enabled", False) if lifecycle else False,
        push_enabled=lifecycle.get("push_enabled", False) if lifecycle else False,
        review_entrypoint=review,
    )


def _build_subagent_lanes(
    profiles: list[Any], bindings: list[Any] | None = None
) -> list[SubagentLaneItem]:
    bindings_map: dict[str, Any] = {}
    for b in bindings or []:
        for pid in (
            getattr(b, "allowed_profile_ids", [])
            if hasattr(b, "allowed_profile_ids")
            else b.get("allowed_profile_ids", [])
        ):
            bindings_map[pid] = b

    lanes: list[SubagentLaneItem] = []
    for p in profiles:
        pid = getattr(p, "profile_id", "")
        binding = bindings_map.get(pid)
        lanes.append(
            SubagentLaneItem(
                profile_id=pid,
                display_name=getattr(p, "display_name", ""),
                profile_kind=getattr(p, "profile_kind", ""),
                role=getattr(p, "role", ""),
                active_missions=0,
                max_concurrent=getattr(p, "max_concurrent_missions", 1),
                status="idle",
                model_binding_id=getattr(binding, "binding_id", "") if binding else "",
                model_binding_label=(
                    getattr(binding, "display_name", "") if binding else ""
                ),
                provider_id=getattr(binding, "provider_id", "") if binding else "",
                provider_status=(
                    getattr(binding, "status", "demo_local")
                    if binding
                    else "demo_local"
                ),
                requires_api_key=(
                    getattr(binding, "requires_api_key", False) if binding else False
                ),
            )
        )
    return lanes


def _build_ralph_report_items(reports: list[Any]) -> list[RalphReportItem]:
    items: list[RalphReportItem] = []
    for r in reports:
        if hasattr(r, "model_dump"):
            items.append(
                RalphReportItem(
                    report_id=r.report_id,
                    report_kind=r.report_kind,
                    title=r.title,
                    ralph_lane_id=r.ralph_lane_id,
                    branch_name=r.branch_name,
                    status=r.status,
                    relevance_score=r.relevance_score,
                    requires_orchestrator_review=(
                        r.status in {"created", "delivered_to_orchestrator"}
                    ),
                )
            )
        else:
            items.append(
                RalphReportItem(
                    report_id=r.get("report_id", ""),
                    report_kind=r.get("report_kind", ""),
                    title=r.get("title", ""),
                    ralph_lane_id=r.get("ralph_lane_id", ""),
                    branch_name=r.get("branch_name"),
                    status=r.get("status", ""),
                    relevance_score=r.get("relevance_score", 0.0),
                    requires_orchestrator_review=r.get("status")
                    in {"created", "delivered_to_orchestrator"},
                )
            )
    return items


def _build_lifecycle_timeline(
    lifecycle: dict[str, Any], background_enabled: bool
) -> list[LifecycleTimelineEntry]:
    entries: list[LifecycleTimelineEntry] = [
        LifecycleTimelineEntry(
            step_order=1,
            status="completed" if background_enabled else "pending",
            label="Background enabled",
            detail="Toggle ON",
            blocked=not background_enabled,
        )
    ]
    lanes = (
        lifecycle.get("active_lanes", []) or lifecycle.get("completed_lanes", []) or []
    )
    has_lane = len(lanes) > 0
    has_commit = any(l.get("latest_commit_sha") for l in lanes)
    has_bundle = any(l.get("review_bundle_sha256") for l in lanes)

    entries.append(
        LifecycleTimelineEntry(
            step_order=2,
            status="completed" if has_lane else "pending",
            label="Lane created",
            detail="Worktree/branch created" if has_lane else "Awaiting lane proposal",
            blocked=not background_enabled,
        )
    )
    entries.append(
        LifecycleTimelineEntry(
            step_order=3,
            status="completed" if has_lane else "pending",
            label="Execution completed",
            detail="Scoped lane execution done" if has_lane else "Awaiting execution",
            blocked=not has_lane,
        )
    )
    entries.append(
        LifecycleTimelineEntry(
            step_order=4,
            status="completed" if has_commit else "pending",
            label="Commit recorded",
            detail="Committed to Ralph branch" if has_commit else "No commits yet",
            blocked=not has_lane,
        )
    )
    entries.append(
        LifecycleTimelineEntry(
            step_order=5,
            status="completed" if has_bundle else "pending",
            label="Review bundle sealed",
            detail="Ready for review" if has_bundle else "Awaiting seal",
            blocked=not has_commit,
        )
    )
    entries.append(
        LifecycleTimelineEntry(
            step_order=6,
            status="completed" if has_bundle else "pending",
            label="Ralph report delivered",
            detail="Reported to orchestrator" if has_bundle else "Awaiting report",
            blocked=not has_bundle,
        )
    )
    entries.append(
        LifecycleTimelineEntry(
            step_order=7,
            status="pending",
            label="Adoption proposal",
            detail="Awaiting orchestrator review",
            blocked=True,
        )
    )
    entries.append(
        LifecycleTimelineEntry(
            step_order=8,
            status="pending",
            label="Merge",
            detail="Requires adoption approval",
            blocked=True,
        )
    )
    entries.append(
        LifecycleTimelineEntry(
            step_order=9,
            status="pending",
            label="Push to preproduction",
            detail="Requires preproduction approval",
            blocked=True,
        )
    )
    return entries


__all__ = [
    "BOARD_VERSION",
    "LifecycleTimelineEntry",
    "MissionItem",
    "OrchestratorMissionBoard",
    "RalphReportItem",
    "ReviewEntrypoint",
    "SubagentLaneItem",
    "build_mission_board",
]
