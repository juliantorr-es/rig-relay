from __future__ import annotations

from datetime import datetime
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
    WORKSPACE_READY = "workspace_ready"
    WORKSPACE_ACTIVATED = "workspace_activated"
    VALIDATION_STARTED = "validation_started"
    VALIDATION_COMPLETED = "validation_completed"
    REVIEW_STARTED = "review_started"
    REVIEW_COMPLETED = "review_completed"
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
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


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
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


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


class FleetWorkspaceProjection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.fleet_workspace_projection.v1"
    generated_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    workspaces: list[FleetWorkspaceProjectionItem] = Field(default_factory=list)


__all__ = [
    "FleetWorkspaceProjection",
    "FleetWorkspaceProjectionItem",
    "ManagedWorkspace",
    "ManagedWorkspaceIdentity",
    "RecoveryState",
    "WorkspaceIdentity",
    "WorkspaceLifecycleEvent",
    "WorkspaceLifecycleEventKind",
    "WorkspaceRole",
    "WorkspaceState",
]
