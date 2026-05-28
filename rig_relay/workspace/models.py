from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceRole(StrEnum):
    IMPLEMENTER = "implementer"
    TESTER = "tester"
    REVIEWER = "reviewer"
    DOCUMENTER = "documenter"
    ORCHESTRATOR = "orchestrator"


class WorkspaceState(StrEnum):
    REQUESTED = "requested"
    RESERVED = "reserved"
    WORKTREE_CREATED = "worktree_created"
    BOOTSTRAPPING = "bootstrapping"
    READY = "ready"
    ACTIVE = "active"
    VALIDATING = "validating"
    UNDER_REVIEW = "under_review"
    CHECKPOINTED = "checkpointed"
    RELEASED_FOR_INTEGRATION = "released_for_integration"
    INTEGRATED = "integrated"
    PUBLISHED = "published"
    RETIRED = "retired"


class RecoveryState(StrEnum):
    RESERVATION_REFUSED = "reservation_refused"
    BOOTSTRAP_FAILED = "bootstrap_failed"
    STALE_BASE = "stale_base"
    SESSION_DETACHED = "session_detached"
    RECOVERY_REQUIRED = "recovery_required"
    RECOVERED = "recovered"
    INTEGRATION_CONFLICT = "integration_conflict"
    RESET_REFUSED = "reset_refused"
    REMOVAL_REFUSED = "removal_refused"
    QUARANTINED = "quarantined"


class WorkPreservationState(StrEnum):
    NO_WORK_DETECTED = "no_work_detected"
    UNCOMMITTED_EDITS_PRESENT = "uncommitted_edits_present"
    UNCHECKPOINTED_EDITS_PRESENT = "uncheckpointed_edits_present"
    CHECKPOINT_PRESENT = "checkpoint_present"
    REAPPLICATION_SUSPECTED = "reapplication_suspected"
    CLEAN = "clean"


class WorkLossAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    worktree_exists: bool
    work_preservation: WorkPreservationState
    uncommitted_changes_count: int = 0
    changed_files: list[str] = Field(default_factory=list)
    current_head_sha: str | None = None
    checkpoint_sha: str | None = None
    duplicate_checkpoint_detected: bool = False
    duplicate_diff_detected: bool = False
    recovery_required: bool
    recovery_possible: bool
    validation_required: bool
    assessment_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class WorkspaceIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str = Field(default_factory=lambda: str(uuid4()))
    project_identity: str
    mission_id: str | None = None
    lane_id: str | None = None
    agent_profile_name: str | None = None
    role: WorkspaceRole = WorkspaceRole.IMPLEMENTER


class ManagedWorkspaceIdentity(WorkspaceIdentity):
    pass


class WorkspaceLifecycleEventKind(StrEnum):
    WORKSPACE_REQUESTED = "workspace_requested"
    WORKSPACE_RESERVED = "workspace_reserved"
    WORKTREE_CREATED = "worktree_created"
    BOOTSTRAP_STARTED = "bootstrap_started"
    BOOTSTRAP_COMPLETED = "bootstrap_completed"
    WORKSPACE_ACTIVATED = "workspace_activated"
    VALIDATION_STARTED = "validation_started"
    REVIEW_STARTED = "review_started"
    WORKSPACE_CHECKPOINTED = "workspace_checkpointed"
    RELEASED_FOR_INTEGRATION = "released_for_integration"
    INTEGRATED = "integrated"
    PUBLISHED = "published"
    WORKSPACE_RETIRED = "workspace_retired"
    RESERVATION_REFUSED = "reservation_refused"
    BOOTSTRAP_FAILED = "bootstrap_failed"
    STALE_BASE_DETECTED = "stale_base_detected"
    SESSION_DETACHED = "session_detached"
    RECOVERY_REQUIRED = "recovery_required"
    RECOVERED = "recovered"
    INTEGRATION_CONFLICT = "integration_conflict"
    RESET_REFUSED = "reset_refused"
    REMOVAL_REFUSED = "removal_refused"
    QUARANTINED = "quarantined"
    WORKTREE_LOCKED = "worktree_locked"
    WORKTREE_UNLOCKED = "worktree_unlocked"
    WORKTREE_REPAIRED = "worktree_repaired"
    WORKTREE_PRUNED = "worktree_pruned"
    CHANGES_RECORDED = "changes_recorded"
    BOUNDARY_CLAIM_ACQUIRED = "boundary_claim_acquired"
    BOUNDARY_CLAIM_RELEASED = "boundary_claim_released"
    BOUNDARY_CONFLICT_DETECTED = "boundary_conflict_detected"
    WORK_PRESERVATION_ASSESSED = "work_preservation_assessed"
    VALIDATION_REQUIRED = "validation_required"
    REAPPLICATION_SUSPECTED = "reapplication_suspected"


class WorkspaceLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str
    event_kind: WorkspaceLifecycleEventKind
    state_before: WorkspaceState | None = None
    state_after: WorkspaceState | None = None
    recovery_before: RecoveryState | None = None
    recovery_after: RecoveryState | None = None
    worktree_path: str | None = None
    branch_name: str | None = None
    base_commit_sha: str | None = None
    head_sha: str | None = None
    session_id: str | None = None
    changed_files_count: int | None = None
    checkpoint_sha: str | None = None
    reason: str | None = None
    prior_event_digest: str | None = None
    event_digest: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ManagedWorkspace(BaseModel):
    model_config = ConfigDict(extra="forbid")
    identity: WorkspaceIdentity
    state: WorkspaceState = WorkspaceState.REQUESTED
    recovery_state: RecoveryState | None = None
    worktree_path: str | None = None
    branch_name: str | None = None
    base_branch: str = "main"
    base_commit_sha: str | None = None
    managed_branch_name: str | None = None
    head_sha: str | None = None
    changed_files_count: int = Field(default=0, ge=0)
    checkpoint_sha: str | None = None
    session_id: str | None = None
    context_capsule_digest: str | None = None
    harness_profile_digest: str | None = None
    runtime_binding_reference: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class FleetWorkspaceProjectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    project_identity: str
    role: WorkspaceRole = WorkspaceRole.IMPLEMENTER
    branch_summary: str | None = None
    lifecycle_status: WorkspaceState = WorkspaceState.REQUESTED
    recovery_required: bool = False
    changed_files_count: int = Field(default=0, ge=0)
    checkpoint_state: str | None = None
    claim_state: str | None = None
    safe_available_actions: list[str] = Field(default_factory=list)
    base_sha: str | None = None
    head_sha: str | None = None
    branch_name: str | None = None
    worktree_path_hash: str | None = None
    session_id: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    display_status: str = "Unavailable"


class FleetWorkspaceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.fleet_workspace_projection.v1"
    generated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    total_workspaces: int = 0
    active_workspaces: int = 0
    recovery_needed: int = 0
    workspaces: list[FleetWorkspaceProjectionItem] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AssignmentState(StrEnum):
    READY_FOR_ASSIGNMENT = "ready_for_assignment"
    ASSIGNED = "assigned"
    DETACHED_WITH_WORK_PRESERVED = "detached_with_work_preserved"
    RECOVERY_REQUIRED = "recovery_required"
    RECOVERED = "recovered"
    BLOCKED_MISSING_CONTEXT_RELEASE = "blocked_missing_context_release"
    RELEASED_FOR_INTEGRATION = "released_for_integration"
    RETIRED = "retired"


class WorkspaceAssignmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    mission_id: str | None = None
    lane_id: str | None = None
    agent_role: WorkspaceRole
    session_id: str | None = None
    context_capsule_digest: str | None = None
    harness_profile_digest: str | None = None
    runtime_binding_reference: str | None = None


class WorkspaceAssignmentReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    receipt_id: str = Field(default_factory=lambda: str(uuid4()))
    workspace_id: str
    mission_id: str | None = None
    lane_id: str | None = None
    agent_role: WorkspaceRole
    assignment_state: AssignmentState
    session_id: str | None = None
    base_sha: str | None = None
    branch_name: str | None = None
    integration_claims: list[str] = Field(default_factory=list)
    context_capsule_digest: str | None = None
    harness_profile_digest: str | None = None
    runtime_binding_reference: str | None = None
    evidence_digest: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class CurrentAssignmentProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    assignment_state: AssignmentState
    agent_role: str
    session_id: str | None = None
    context_available: bool = False
    profile_available: bool = False
    runtime_available: bool = False
    blocked_reason: str | None = None


__all__ = [
    "AssignmentState",
    "CurrentAssignmentProjection",
    "FleetWorkspaceProjection",
    "FleetWorkspaceProjectionItem",
    "ManagedWorkspace",
    "ManagedWorkspaceIdentity",
    "RecoveryState",
    "WorkLossAssessment",
    "WorkPreservationState",
    "WorkspaceAssignmentReceipt",
    "WorkspaceAssignmentRequest",
    "WorkspaceIdentity",
    "WorkspaceLifecycleEvent",
    "WorkspaceLifecycleEventKind",
    "WorkspaceRole",
    "WorkspaceState",
]
