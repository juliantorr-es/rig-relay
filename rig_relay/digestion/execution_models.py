"""Execution workspace models — provisioning, state, and cleanup.

Slice 1C: Managed Worktree Provisioning and Mission Admission.
Git-backed worktree provisioning with hook gating and cross-slice revalidation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class WorkspaceProviderType(StrEnum):
    GIT_WORKTREE = "git_worktree"
    IMPORTED_COPY = "imported_copy"  # deferred
    NON_GIT_SANDBOX = "non_git_sandbox"  # deferred


class ProvisioningStatus(StrEnum):
    PROVISIONED = "provisioned"
    STALE_PLAN_DIGEST = "stale_plan_digest"
    STALE_HEAD = "stale_head"
    STALE_CHECKOUT_REFERENCE = "stale_checkout_reference"
    STALE_CHECKOUT_GIT_REPOSITORY_CHANGED = (
        "stale_checkout_reference_git_repository_changed"
    )
    HOOK_AUTHORIZATION_REQUIRED = "workspace_provisioning_requires_hook_authorization"
    BRANCH_COLLISION = "branch_collision"
    WORKSPACE_PATH_CONFLICT = "workspace_path_conflict"
    REFUSED = "refused"
    PROVIDER_NOT_IMPLEMENTED = "provider_not_implemented"


class WorkspaceCleanupDisposition(StrEnum):
    ACTIVE = "active"
    CHECKPOINTED = "checkpointed"
    RETAINED_FOR_REVIEW = "retained_for_review"
    USER_APPROVED_CLEANUP = "user_approved_cleanup"
    REMOVED = "removed"
    ABORTED_WITH_UNCOMMITTED_CHANGES = "aborted_with_uncommitted_changes"
    RETAINED_FOR_RECOVERY = "retained_for_recovery"


class ProvisioningInput(BaseModel):
    """Input required for execution workspace provisioning.

    Consumed by ExecutionWorkspaceProvider.provision().
    Bind to a persisted WorkspacePreparationPlan, not raw intake.
    """

    model_config = ConfigDict(extra="forbid")

    plan_digest: str = Field(
        description="SHA256 digest from the WorkspacePreparationPlan for cross-slice validation."
    )
    repository_id: str = Field(description="Logical repository identity.")
    source_checkout_id: str = Field(
        description="Exact source checkout identity this workspace is derived from."
    )
    admitted_base_sha: str = Field(
        description="Exact HEAD SHA to create the managed worktree from."
    )
    proposed_managed_branch: str = Field(description="Proposed managed branch name.")
    proposed_worktree_location: str = Field(
        description="Proposed app-owned worktree path."
    )
    branch_prefix: str = Field(
        default="rig-mission", description="Configurable branch prefix."
    )
    source_checkout_path: str = Field(
        description="Filesystem path to the source checkout for revalidation."
    )


class ExecutionWorkspace(BaseModel):
    """A provisioned execution workspace. Created by ExecutionWorkspaceProvider."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str = Field(
        description="App-assigned UUID for this execution workspace."
    )
    repository_id: str = Field(description="Logical repository identity.")
    source_checkout_id: str = Field(
        description="Source checkout identity this workspace was derived from."
    )
    provider_type: str = Field(
        description="ExecutionWorkspaceProvider that created this workspace."
    )
    managed_root_path: str = Field(
        description="Absolute path to the managed workspace root."
    )
    managed_branch: str = Field(description="Managed branch name.")
    base_commit_sha: str = Field(
        description="Exact commit SHA this workspace was created from."
    )
    created_at: str = Field(description="ISO 8601 timestamp of creation.")
    initial_clean_state_digest: str = Field(
        default="", description="SHA256 digest of the initial workspace clean state."
    )
    cleanup_disposition: str = Field(
        default=WorkspaceCleanupDisposition.ACTIVE,
        description="Current cleanup disposition.",
    )


class WorkspaceState(BaseModel):
    """Current state of an execution workspace."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    exists: bool
    is_dirty: bool = False
    branch: str | None = None
    head_sha: str | None = None
    uncommitted_file_count: int = 0
    checkpoint_count: int = 0
    cleanup_disposition: str = WorkspaceCleanupDisposition.ACTIVE


class CleanupResult(BaseModel):
    """Result of a workspace cleanup operation."""

    model_config = ConfigDict(extra="forbid")

    workspace_id: str
    status: str = Field(
        description="Cleanup status: retained, removed, refused_dirty, error."
    )
    reason: str | None = Field(
        default=None, description="Human-readable reason for the cleanup outcome."
    )
    force_used: bool = Field(
        default=False,
        description="Whether --force was used. Must be False in normal path.",
    )


class ForceCleanupAuthorization(BaseModel):
    """Explicit user authorization for forced workspace cleanup.

    Required for force=True cleanup. Without valid authorization,
    dirty workspaces are retained. Normal (non-force) cleanup of
    clean workspaces does not require this authorization.
    """

    model_config = ConfigDict(extra="forbid")

    authorization_id: str = Field(
        description="App-assigned UUID for this authorization."
    )
    execution_workspace_id: str = Field(
        description="Workspace being authorized for cleanup."
    )
    dirty_state_digest: str = Field(
        description="SHA256 digest of the workspace's current dirty state at authorization time."
    )
    disposition: str = Field(
        description="Cleanup disposition: user_approved_cleanup only."
    )
    authorized_at: str = Field(description="ISO 8601 timestamp of authorization.")
