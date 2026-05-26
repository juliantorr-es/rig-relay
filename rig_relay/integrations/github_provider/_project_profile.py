"""Local project-profile proposal model — GitHub-facing project configuration.

Represents GitHub-facing project settings (repo name, description, visibility, etc.)
without becoming a second authority for checkpoint, promotion, lane, or disclosure state.
Separate from GitHub user profile and repository truth models.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProjectProfileProposal(BaseModel):
    """Proposed GitHub-facing project configuration.

    Must not mutate checkpoint, promotion, lane, or disclosure state.
    Provides bounded metadata for repo creation, Pages, portfolio, and CI.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.project_profile_proposal.v1"

    # Repository identity
    proposed_repo_name: str = ""
    proposed_description: str = ""
    proposed_homepage: str = ""
    proposed_visibility: str = "public"  # public, private

    # Topics / tags (where supported by existing policy)
    proposed_topics: list[str] = Field(default_factory=list)

    # Intent flags
    portfolio_inclusion: bool = False
    issue_tracking_enabled: bool = True
    pages_publishing_enabled: bool = False
    pages_source_branch: str = "main"
    pages_source_path: str = "/"

    # Required permissions (computed, not user-supplied)
    required_github_permissions: list[str] = Field(default_factory=list)

    # Authorization
    authorization_required: bool = True
    authorization_status: str = "pending"

    # Origin
    source_repo_root: str = ""
    source_branch: str = "main"
    expected_publication_head: str = ""

    # Blockers
    blockers: list[str] = Field(default_factory=list)

    def is_ready_for_bootstrap(self) -> bool:
        return (
            bool(self.proposed_repo_name)
            and not self.blockers
            and self.authorization_status == "granted"
        )

    def summary(self) -> dict[str, Any]:
        return {
            "proposed_repo_name": self.proposed_repo_name,
            "proposed_visibility": self.proposed_visibility,
            "pages_publishing_enabled": self.pages_publishing_enabled,
            "portfolio_inclusion": self.portfolio_inclusion,
            "issue_tracking_enabled": self.issue_tracking_enabled,
            "required_permissions_count": len(self.required_github_permissions),
            "authorization_status": self.authorization_status,
            "blockers_count": len(self.blockers),
        }


class ProjectProfileValidationResult(BaseModel):
    """Validation result for a project profile proposal."""

    model_config = ConfigDict(extra="forbid")

    valid: bool = True
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    permission_gaps: list[str] = Field(default_factory=list)

    @classmethod
    def from_proposal(
        cls, proposal: ProjectProfileProposal
    ) -> ProjectProfileValidationResult:
        errors: list[str] = []
        warnings: list[str] = []
        permission_gaps: list[str] = []

        if not proposal.proposed_repo_name or not proposal.proposed_repo_name.strip():
            errors.append("Repository name is required")

        if proposal.proposed_visibility not in {"public", "private"}:
            errors.append("Visibility must be 'public' or 'private'")

        if proposal.pages_publishing_enabled and not proposal.proposed_homepage:
            warnings.append("Pages publishing enabled but no homepage URL configured")

        if proposal.pages_publishing_enabled:
            permission_gaps.append("Pages:write")
            permission_gaps.append("Administration:write")

        return cls(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            permission_gaps=permission_gaps,
        )


__all__ = ["ProjectProfileProposal", "ProjectProfileValidationResult"]
