"""GitHub Truth Operator Projection — bounded, content-light operator evidence UX.

Translates GitHubTruthAdapter evidence into operator-visible projection fields.
Content-light: no raw paths, logs, token material, private metadata, or API payloads.
Supports progressive disclosure: state → evidence digest → authorized detail.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rig_relay.integrations.github_provider._truth_models import (
    GitHubInstallationAccess,
    GitHubPublicationVerification,
    GitHubRepositoryIdentity,
    GitHubTokenStatus,
    GitHubVerificationStatus,
)


class GitHubConnectionProjection(BaseModel):
    """Operator-visible GitHub App connection state."""

    model_config = ConfigDict(extra="forbid")

    connected: bool = False
    token_status: str = "unavailable"
    token_expires_in_seconds: float | None = None
    permissions_granted_count: int = 0
    repositories_granted_count: int = 0
    app_id: int = 0
    evidence_digest: str | None = None

    @classmethod
    def from_installation_access(
        cls, access: GitHubInstallationAccess
    ) -> GitHubConnectionProjection:
        return cls(
            connected=access.token_status == GitHubTokenStatus.AVAILABLE,
            token_status=access.token_status,
            token_expires_in_seconds=access.token_expires_in_seconds,
            permissions_granted_count=len(access.granted_permissions),
            repositories_granted_count=len(access.granted_repository_hashes),
            app_id=access.app_id,
            evidence_digest=access._evidence_digest(),
        )


_STATUS_LABELS: dict[str, str] = {
    GitHubVerificationStatus.EXACT_PROMOTED: "Published — exact match",
    GitHubVerificationStatus.ACCEPTED_WITH_FOLLOW_ON: "Published — with follow-on commits",
    GitHubVerificationStatus.TARGET_BEHIND: "Remote behind — not yet pushed",
    GitHubVerificationStatus.TARGET_DIVERGENT: "Diverged — manual reconciliation needed",
    GitHubVerificationStatus.EXPECTED_COMMIT_MISSING: "Commit not found on remote",
    GitHubVerificationStatus.REMOTE_UNAVAILABLE: "Remote unavailable",
    GitHubVerificationStatus.PERMISSION_UNAVAILABLE: "GitHub App permission missing",
    GitHubVerificationStatus.VERIFICATION_INCOMPLETE: "Verification incomplete",
}


class PublicationStatusProjection(BaseModel):
    """Operator-visible publication verification projection."""

    model_config = ConfigDict(extra="forbid")

    verification_status: str = "unknown"
    status_label: str = "Unknown"
    accepted_head_present: bool = False
    remote_head_sha: str | None = None
    expected_sha: str = ""
    ref: str = "main"
    follow_on_commits_count: int = 0
    follow_on_head_sha: str | None = None
    ci_state: str | None = None
    suggested_next_action: str | None = None
    error_kind: str | None = None
    evidence_digest: str | None = None

    @classmethod
    def from_verification(
        cls, verification: GitHubPublicationVerification
    ) -> PublicationStatusProjection:
        return cls(
            verification_status=verification.verification_status,
            status_label=_STATUS_LABELS.get(
                verification.verification_status, "Unknown"
            ),
            accepted_head_present=verification.accepted_head_present,
            remote_head_sha=verification.remote_head_sha,
            expected_sha=verification.expected_sha,
            ref=verification.ref,
            follow_on_commits_count=verification.follow_on_commits_count,
            follow_on_head_sha=verification.follow_on_head_sha,
            ci_state=verification.ci_state,
            suggested_next_action=verification.suggested_next_action,
            error_kind=verification.error_kind,
            evidence_digest=verification._evidence_digest(),
        )


_CI_STATE_LABELS: dict[str, str] = {
    "success": "All checks passed",
    "failure": "Checks failing",
    "pending": "Checks in progress",
    "error": "Check error",
    "no_status": "No CI configured",
}


class CIStateProjection(BaseModel):
    """Operator-visible CI status projection."""

    model_config = ConfigDict(extra="forbid")

    overall_state: str = "no_status"
    passed: int = 0
    failed: int = 0
    pending: int = 0
    skipped: int = 0
    cancelled: int = 0
    neutral: int = 0
    total: int = 0
    suggested_next_action: str | None = None
    evidence_digest: str | None = None

    @property
    def state_label(self) -> str:
        return _CI_STATE_LABELS.get(self.overall_state, "Unknown")


class RepositoryProjection(BaseModel):
    """Operator-visible repository identity projection."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    visibility: str | None = None
    default_branch_available: bool = False
    evidence_digest: str | None = None

    @classmethod
    def from_identity(cls, identity: GitHubRepositoryIdentity) -> RepositoryProjection:
        return cls(
            repository_hash=identity.repository_hash,
            visibility=identity.visibility,
            default_branch_available=identity.default_branch is not None,
            evidence_digest=identity._evidence_digest(),
        )


class ToolExecutionProjection(BaseModel):
    """Operator-visible tool execution summary for truth tools."""

    model_config = ConfigDict(extra="forbid")

    tool_name: str
    mutation_class: str
    determinism_class: str
    operation: str
    status: str  # ok, refused, error, unavailable
    summary: str
    error_kind: str | None = None
    evidence_digest: str | None = None
    suggested_next_action: str | None = None

    _DISCLOSURE_TIERS: dict[str, str] = {
        "read_only": "public",
        "remote_read": "public",
        "writes_evidence_only": "public",
        "writes_workspace": "restricted",
        "writes_temp_only": "restricted",
        "mutates_git_state": "authorized",
        "external_side_effect": "authorized",
        "unknown": "pending",
    }

    @property
    def disclosure_tier(self) -> str:
        return self._DISCLOSURE_TIERS.get(self.mutation_class, "pending")


class OperatorDashboardProjection(BaseModel):
    """Aggregated operator dashboard projection for GitHub truth evidence."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "rig.relay.github_operator_projection.v1"

    # Connection state
    connection: GitHubConnectionProjection = Field(
        default_factory=GitHubConnectionProjection
    )

    # Repository identity
    repository: RepositoryProjection | None = None

    # Publication status
    publication: PublicationStatusProjection | None = None

    # CI state
    ci: CIStateProjection | None = None

    # Tool execution context
    tool_executions: list[ToolExecutionProjection] = Field(default_factory=list)

    # Pending authorizations
    pending_authorizations: list[str] = Field(default_factory=list)

    # Parked lane dependencies
    parked_dependencies: list[str] = Field(default_factory=list)

    # Warnings
    warnings: list[str] = Field(default_factory=list)

    # Evidence digest
    dashboard_digest: str | None = None

    def compute_digest(self) -> str:
        raw = self.model_dump_json(exclude={"dashboard_digest"})
        return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def model_post_init(self, __context: Any) -> None:
        if self.dashboard_digest is None:
            self.dashboard_digest = self.compute_digest()


# ── Progressive Disclosure Helpers ─────────────────────────────────────


def build_operator_dashboard(
    *,
    installation_access: GitHubInstallationAccess | None = None,
    publication: GitHubPublicationVerification | None = None,
    repository: GitHubRepositoryIdentity | None = None,
    pending_authorizations: list[str] | None = None,
    parked_dependencies: list[str] | None = None,
) -> OperatorDashboardProjection:
    """Build a content-light operator dashboard from GitHub truth evidence."""
    dashboard = OperatorDashboardProjection()

    if installation_access is not None:
        dashboard.connection = GitHubConnectionProjection.from_installation_access(
            installation_access
        )

    if publication is not None:
        dashboard.publication = PublicationStatusProjection.from_verification(
            publication
        )

    if repository is not None:
        dashboard.repository = RepositoryProjection.from_identity(repository)

    if pending_authorizations is not None:
        dashboard.pending_authorizations = list(pending_authorizations)

    if parked_dependencies is not None:
        dashboard.parked_dependencies = list(parked_dependencies)

    if publication is not None and publication.ci_evidence is not None:
        dashboard.ci = CIStateProjection(
            overall_state=publication.ci_evidence.overall_state,
            passed=publication.ci_evidence.passed_count,
            failed=publication.ci_evidence.failed_count,
            pending=publication.ci_evidence.pending_count,
            skipped=publication.ci_evidence.skipped_count,
            cancelled=publication.ci_evidence.cancelled_count,
            neutral=publication.ci_evidence.neutral_count,
            total=publication.ci_evidence.total_count,
            suggested_next_action=publication.ci_evidence.suggested_next_action,
            evidence_digest=publication.ci_evidence._evidence_digest(),
        )

    if dashboard.dashboard_digest is None:
        dashboard.dashboard_digest = dashboard.compute_digest()

    # Recompute to reflect all assigned fields
    dashboard.dashboard_digest = dashboard.compute_digest()

    return dashboard


def assert_projection_content_light(projection: OperatorDashboardProjection) -> None:
    """Verify no raw secrets, tokens, or private metadata in projection."""
    from rig_relay.integrations.github_provider._redaction import (
        assert_no_raw_github_token,
    )

    serialized = projection.model_dump_json()
    assert_no_raw_github_token(serialized)

    # No raw repository paths
    for field_name in ("raw_path", "absolute_path", "file_contents"):
        assert field_name not in serialized, (
            f"Forbidden field {field_name} in projection"
        )


__all__ = [
    "CIStateProjection",
    "GitHubConnectionProjection",
    "OperatorDashboardProjection",
    "PublicationStatusProjection",
    "RepositoryProjection",
    "ToolExecutionProjection",
    "assert_projection_content_light",
    "build_operator_dashboard",
]
