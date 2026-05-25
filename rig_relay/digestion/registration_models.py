"""Durable registration models — app-owned repository and checkout records.

Slice 1B: Durable Registration and Workspace Planning.
All state is stored under Application Support, keyed by opaque repository identity.
Zero writes to the user's repository.
"""

from __future__ import annotations

from datetime import UTC, datetime
import uuid

from pydantic import BaseModel, ConfigDict, Field


class RegisteredRepository(BaseModel):
    """Durable logical repository record stored under Application Support.

    Stable across HEAD changes, dirty state changes, and path moves
    when remote-derived identity is available. Local-only repos require
    explicit reassociation after unrecognized path moves.
    """

    model_config = ConfigDict(extra="forbid")

    repository_id: str = Field(
        description="Stable opaque repository identifier. Remote-derived digest when GitHub-backed; app-assigned UUID otherwise."
    )
    repository_label: str | None = Field(
        default=None,
        description="Human-readable label derived from the repository (GitHub owner/repo name or directory name).",
    )
    remote_identity_digest: str | None = Field(
        default=None,
        description="SHA256 digest of GitHub owner/repo when remote-derived identity is available. Stable reconciliation signal.",
    )
    is_github_backed: bool = Field(
        default=False,
        description="Whether the repository has a recognized GitHub remote.",
    )
    is_local_only: bool = Field(
        default=True,
        description="Whether the repository has no remotes. Requires reassociation after path move.",
    )
    registered_at: str = Field(
        description="ISO 8601 timestamp of initial registration."
    )
    last_updated_at: str = Field(
        description="ISO 8601 timestamp of most recent registration or reconciliation."
    )
    latest_preview_freshness: dict | None = Field(
        default=None,
        description="Most recent preview freshness markers: head_sha, branch, dirty_summary, ecosystem_count.",
    )


class SourceCheckoutRecord(BaseModel):
    """Durable record for a specific local checkout of a registered repository.

    Contains the last observed path digest, git common-directory correlation,
    and checkout characteristics. One repository may have multiple checkouts.
    """

    model_config = ConfigDict(extra="forbid")

    checkout_id: str = Field(
        description="App-assigned UUID for this specific local checkout."
    )
    repository_id: str = Field(
        description="The logical repository this checkout belongs to."
    )
    last_observed_path_digest: str = Field(
        description="SHA256 digest of the last observed resolved checkout path. Used as a matching signal, not a durable identity."
    )
    git_common_dir_digest: str | None = Field(
        default=None,
        description="SHA256 digest of the Git common directory. Correlates checkouts sharing the same repository administrative state.",
    )
    last_observed_branch: str | None = Field(
        default=None,
        description="Branch observed at last registration or reconciliation.",
    )
    last_observed_head_sha: str | None = Field(
        default=None, description="HEAD SHA at last registration or reconciliation."
    )
    is_primary_checkout: bool = Field(
        default=True,
        description="True if this is a primary checkout (not a linked worktree).",
    )
    registered_at: str = Field(
        description="ISO 8601 timestamp when this checkout was registered."
    )
    last_reconciled_at: str = Field(
        description="ISO 8601 timestamp of most recent path reconciliation."
    )
    requires_reassociation: bool = Field(
        default=False,
        description="True if the checkout was moved to an unrecognized path and needs user reassociation. Only relevant for local-only repositories.",
    )


class WorkspacePreparationPlan(BaseModel):
    """A plan for creating an execution workspace. No workspace is created yet.

    Produced during Slice 1B workspace planning. Slice 1C consumes and
    revalidates this plan before provisioning.
    """

    model_config = ConfigDict(extra="forbid")

    plan_id: str = Field(description="App-assigned UUID for this preparation plan.")
    repository_id: str = Field(description="Logical repository identity.")
    checkout_id: str = Field(
        description="Source checkout identity this plan is based on."
    )
    provider_eligibility: str = Field(
        description="Provider eligibility: git_worktree_available or unsupported_in_current_phase."
    )
    admitted_base_sha: str | None = Field(
        default=None,
        description="Exact HEAD SHA from the current preview, proposed as the base commit for worktree creation.",
    )
    proposed_managed_branch: str = Field(
        default="",
        description="Proposed managed branch name (e.g., rig-mission-<short-id>).",
    )
    proposed_worktree_location: str = Field(
        default="",
        description="Proposed app-owned worktree path under Application Support.",
    )
    branch_prefix: str = Field(
        default="rig-mission",
        description="Configurable branch prefix for managed worktrees.",
    )
    source_checkout_is_dirty: bool = Field(
        default=False,
        description="Whether the source checkout has uncommitted changes that will NOT be included in a managed workspace.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings about this plan: uncommitted source changes, hook risk, stale preview.",
    )
    generated_at: str = Field(
        description="ISO 8601 timestamp when this plan was generated."
    )
    digest: str = Field(
        default="",
        description="SHA256 digest binding this plan's identity fields for cross-slice revalidation.",
    )


def generate_stable_repository_id(
    is_github_backed: bool, remote_identity_digest: str | None
) -> str:
    """Generate a stable opaque repository identifier.

    GitHub-backed: deterministic SHA256 of remote_identity_digest.
    Local-only: always generates a new app-assigned UUID. The caller
    (register_repository) is responsible for finding existing
    registrations through correlation signals before calling this.

    Correlation signals (path_digest, git_common_dir_digest) are used
    for REDISCOVERY, not IDENTITY derivation.
    """
    import hashlib

    if is_github_backed and remote_identity_digest is not None:
        return hashlib.sha256(f"github:{remote_identity_digest}".encode()).hexdigest()
    return str(uuid.uuid4())


def generate_checkout_id() -> str:
    """Generate a new UUID for a source checkout record."""
    return str(uuid.uuid4())


def utc_now_iso() -> str:
    """Return current UTC timestamp as ISO 8601 string."""
    return datetime.now(UTC).isoformat()
