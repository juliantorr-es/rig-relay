from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class FleetWorkspaceStatusProjection(BaseModel):
    """Y0 consumer contract — what Gridline sees."""

    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    project_identity: str
    assigned_role: str
    lifecycle_state: str
    recovery_state: str | None = None
    changed_files_count: int = 0
    checkpoint_state: str
    claim_state: str
    conflict_state: str | None = None
    validation_required: bool = False
    review_readiness: bool = False
    safe_available_actions: list[str] = []
    branch_summary: str | None = None
    base_sha_summary: str | None = None
    head_sha_summary: str | None = None
    display_status: str


class WorkspaceContextReleaseRequirement(BaseModel):
    """Y2 consumer contract — what context compiler must provide."""

    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    repository_context_release_digest: str | None = None
    eligibility_requirement: str
    stale_context: bool = False
    refresh_required: bool = False
    assignment_refusal: bool = False
    refusal_reason: str | None = None


class WorkspaceHarnessProfileAssignmentContract(BaseModel):
    """Y3 consumer contract — what profile registry must provide."""

    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    session_id: str | None = None
    agent_role: str
    profile_resolution_digest: str | None = None
    session_envelope_digest: str | None = None
    capability_evidence_digest: str | None = None
    assignment_state: str
    refusal_reason: str | None = None


class WorkspaceRuntimeSessionBindingContract(BaseModel):
    """Y4 consumer contract — what runtime/MLX must provide."""

    model_config = ConfigDict(extra="forbid")
    workspace_id: str
    session_id: str | None = None
    runtime_binding_permitted: bool = False
    tool_execution_workspace_required: bool = True
    cancellation_linkage: bool = False
    shutdown_recovery_linkage: bool = False


class WorkspaceLifecycleMetrics(BaseModel):
    """Analytics consumer contract — content-light lifecycle metrics."""

    model_config = ConfigDict(extra="forbid")
    workspace_allocation_count: int = 0
    time_to_ready_seconds: float | None = None
    detach_recovery_count: int = 0
    work_preserved_recovery_count: int = 0
    integration_claim_conflicts: int = 0
    validation_duration_seconds: float | None = None
    review_duration_seconds: float | None = None
    retirement_reasons: list[str] = []
    refusal_reasons: list[str] = []
