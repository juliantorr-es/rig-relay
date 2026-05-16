"""Ralph lifecycle projection — pywebview widget state for background lanes.

Surfaces active/completed/pending lanes, worktree/branch state,
review bundles, adoption proposals, and gate statuses.
Distinguishes isolated_lane_execution_enabled from live_runtime_mutation_enabled.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

LIFECYCLE_VERSION = "rig.ui.ralph_background_lifecycle.v1"

LANE_STATUSES = [
    "proposed",
    "lane_start_pending",
    "lane_start_approved",
    "worktree_created",
    "active",
    "committed",
    "sealed",
    "review_pending",
    "adoption_proposed",
    "adopted",
    "rejected",
    "expired",
    "failed",
]


class LifecycleGateStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    allowed: bool = False
    label: str = ""
    requires: str = ""


class LifecycleLaneSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str = ""
    mission_id: str = ""
    branch_name: str = ""
    worktree_path: str = ""
    status: str = ""
    approval_state: str = ""
    latest_commit_sha: str = ""
    review_bundle_sha256: str = ""
    changed_files: list[str] = Field(default_factory=list)


class LifecycleAdoptionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = ""
    source_lane_id: str = ""
    target_kind: str = ""
    target_lane_id: str | None = None
    status: str = ""
    relevance_score: float = 0.0


class RalphLifecycleProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = LIFECYCLE_VERSION
    background_enabled: bool = False

    isolated_lane_execution_enabled: bool = False
    live_runtime_mutation_enabled: bool = False
    merge_enabled: bool = False
    push_enabled: bool = False

    active_lane_count: int = 0
    completed_lane_count: int = 0
    pending_review_count: int = 0

    active_lanes: list[LifecycleLaneSummary] = Field(default_factory=list)
    completed_lanes: list[LifecycleLaneSummary] = Field(default_factory=list)
    latest_lane: LifecycleLaneSummary | None = None
    latest_adoption_proposal: LifecycleAdoptionSummary | None = None

    gates: list[LifecycleGateStatus] = Field(default_factory=list)

    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

    available_actions: list[dict[str, str | bool]] = Field(
        default_factory=lambda: [
            {
                "action": "ralph_background_toggle_on",
                "label": "Enable background lanes",
                "requires_confirmation": True,
            },
            {
                "action": "ralph_background_toggle_off",
                "label": "Disable background lanes",
                "requires_confirmation": True,
            },
            {
                "action": "ralph_lane_propose",
                "label": "Propose lane from candidate",
                "requires_confirmation": True,
            },
            {
                "action": "ralph_review_finished_lanes",
                "label": "Review finished lanes",
                "requires_confirmation": False,
            },
        ]
    )


def build_lifecycle_projection(
    policy: Any = None,
    active_lanes: list[Any] | None = None,
    completed_lanes: list[Any] | None = None,
    latest_adoption: Any = None,
    model_analytics: dict[str, Any] | None = None,
) -> RalphLifecycleProjection:
    from rig_relay.ralph.background_policy import default_policy

    p = policy or default_policy()
    active = active_lanes or []
    completed = completed_lanes or []

    gates = [
        LifecycleGateStatus(
            name="Worktree creation",
            allowed=p.allow_isolated_worktree_creation
            if hasattr(p, "allow_isolated_worktree_creation")
            else False,
            label="allowed"
            if getattr(p, "allow_isolated_worktree_creation", False)
            else "blocked",
            requires="background policy",
        ),
        LifecycleGateStatus(
            name="Lane execution",
            allowed=p.allow_isolated_lane_execution
            if hasattr(p, "allow_isolated_lane_execution")
            else False,
            label="allowed"
            if getattr(p, "allow_isolated_lane_execution", False)
            else "blocked",
            requires="lane_start_approved",
        ),
        LifecycleGateStatus(
            name="Ralph branch commits",
            allowed=p.allow_ralph_branch_commits
            if hasattr(p, "allow_ralph_branch_commits")
            else False,
            label="allowed"
            if getattr(p, "allow_ralph_branch_commits", False)
            else "blocked",
            requires="isolated lane + policy",
        ),
        LifecycleGateStatus(
            name="Adoption merge",
            allowed=p.allow_adoption_merge
            if hasattr(p, "allow_adoption_merge")
            else False,
            label="requires adoption approval",
            requires="human approval + SHA match",
        ),
        LifecycleGateStatus(
            name="Push to preproduction",
            allowed=p.allow_push_to_preproduction
            if hasattr(p, "allow_push_to_preproduction")
            else False,
            label="requires preproduction approval",
            requires="human approval + validations",
        ),
    ]

    latest_lane = None
    if active:
        la = active[-1]
        latest_lane = LifecycleLaneSummary(
            lane_id=getattr(la, "lane_id", ""),
            mission_id=getattr(la, "mission_id", ""),
            branch_name=getattr(la, "branch_name", ""),
            worktree_path=getattr(la, "worktree_path", ""),
            status=getattr(la, "status", ""),
            approval_state=getattr(la, "approval_state", ""),
            latest_commit_sha=getattr(la, "latest_commit_sha", "") or "",
            review_bundle_sha256=getattr(la, "review_bundle_sha256", "") or "",
        )
    elif completed:
        la = completed[-1]
        latest_lane = LifecycleLaneSummary(
            lane_id=getattr(la, "lane_id", ""),
            branch_name=getattr(la, "branch_name", ""),
            status=getattr(la, "status", ""),
            latest_commit_sha=getattr(la, "latest_commit_sha", "") or "",
            review_bundle_sha256=getattr(la, "review_bundle_sha256", "") or "",
        )

    adoption_summary = None
    if latest_adoption:
        adoption_summary = LifecycleAdoptionSummary(
            proposal_id=getattr(latest_adoption, "proposal_id", ""),
            source_lane_id=getattr(latest_adoption, "source_ralph_lane_id", ""),
            target_kind=getattr(latest_adoption, "target_kind", ""),
            target_lane_id=getattr(latest_adoption, "target_lane_id", None),
            status=getattr(latest_adoption, "status", ""),
            relevance_score=getattr(latest_adoption, "relevance_score", 0.0),
        )

    return RalphLifecycleProjection(
        background_enabled=p.enabled,
        isolated_lane_execution_enabled=(
            getattr(p, "allow_isolated_lane_execution", False)
        ),
        live_runtime_mutation_enabled=False,
        merge_enabled=getattr(p, "allow_adoption_merge", False),
        push_enabled=getattr(p, "allow_push_to_preproduction", False),
        active_lane_count=len(active),
        completed_lane_count=len(completed),
        pending_review_count=len(completed),
        active_lanes=[
            LifecycleLaneSummary(
                lane_id=getattr(la, "lane_id", ""),
                branch_name=getattr(la, "branch_name", ""),
                status=getattr(la, "status", ""),
                latest_commit_sha=getattr(la, "latest_commit_sha", "") or "",
            )
            for la in active
        ],
        completed_lanes=[
            LifecycleLaneSummary(
                lane_id=getattr(la, "lane_id", ""),
                branch_name=getattr(la, "branch_name", ""),
                status=getattr(la, "status", ""),
                review_bundle_sha256=getattr(la, "review_bundle_sha256", "") or "",
            )
            for la in completed
        ],
        latest_lane=latest_lane,
        latest_adoption_proposal=adoption_summary,
        gates=gates,
    )


__all__ = [
    "LIFECYCLE_VERSION",
    "LifecycleGateStatus",
    "LifecycleLaneSummary",
    "RalphLifecycleProjection",
    "build_lifecycle_projection",
]
