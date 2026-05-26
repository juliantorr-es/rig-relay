"""Bounded GitHub truth evidence models — content-light, hash-heavy.

Follows the _GitEvidenceModel pattern from rig_relay/core/tools/builtins/git.py.
All models have redacted_projection() and _evidence_digest().
Never contain raw tokens, keys, private paths, or raw API payloads.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _GitHubEvidenceModel(BaseModel):
    """Mixin for bounded GitHub evidence with redaction and integrity."""

    def _evidence_digest(self) -> str:
        raw = self.model_dump_json()
        return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def redacted_projection(self) -> dict[str, Any]:
        raise NotImplementedError


# ── Installation Access ───────────────────────────────────────────────


class GitHubInstallationAccess(_GitHubEvidenceModel):
    """Installation identity and permission availability (no secrets)."""

    model_config = ConfigDict(extra="forbid")

    installation_hash: str
    app_id: int
    installation_id_hash: str
    token_status: str  # available, expired, unavailable, acquisition_failed
    token_expires_at_iso: str | None = None
    token_expires_in_seconds: float | None = None
    granted_permissions: list[str] = Field(default_factory=list)
    granted_repository_hashes: list[str] = Field(default_factory=list)
    account_hash: str | None = None  # owner hash if discoverable
    errors: list[str] = Field(default_factory=list)
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "token_status": self.token_status,
            "token_expires_in_seconds": self.token_expires_in_seconds,
            "permissions_granted_count": len(self.granted_permissions),
            "repositories_granted_count": len(self.granted_repository_hashes),
            "app_id": self.app_id,
            "evidence_digest": self._evidence_digest(),
            "error_kind": self.error_kind,
        }


# ── Repository Identity ────────────────────────────────────────────────


class GitHubRepositoryIdentity(_GitHubEvidenceModel):
    model_config = ConfigDict(extra="forbid")

    owner: str
    repo: str
    repository_hash: str
    visibility: str | None = None  # public, private, internal
    default_branch: str = "main"
    description: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "repository_hash": self.repository_hash,
            "visibility": self.visibility,
            "default_branch_available": self.default_branch is not None,
            "evidence_digest": self._evidence_digest(),
        }


# ── Remote Ref Observation ─────────────────────────────────────────────


class GitHubRemoteRefObservation(_GitHubEvidenceModel):
    """Observation of a remote branch/ref head."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    ref: str = "refs/heads/main"
    remote_head_sha: str | None = None
    resolved: bool = False
    observed_at_iso: str | None = None
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "repository_hash": self.repository_hash,
            "ref_resolved": self.resolved,
            "remote_head_sha": self.remote_head_sha,
            "evidence_digest": self._evidence_digest(),
            "error_kind": self.error_kind,
        }


# ── Commit Presence ───────────────────────────────────────────────────


class GitHubCommitPresence(_GitHubEvidenceModel):
    """Whether an expected commit exists on a remote ref."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    expected_sha: str
    ref: str = "main"
    present: bool = False
    remote_head_sha: str | None = None
    relationship: str | None = None  # exact, ancestor, descendant, divergent, absent
    ahead_by: int = 0  # commits ahead of expected
    behind_by: int = 0  # commits behind expected
    total_commits_diff: int = 0
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "repository_hash": self.repository_hash,
            "expected_sha": self.expected_sha,
            "present": self.present,
            "remote_head_sha": self.remote_head_sha,
            "relationship": self.relationship,
            "ahead_by": self.ahead_by,
            "behind_by": self.behind_by,
            "total_commits_diff": self.total_commits_diff,
            "evidence_digest": self._evidence_digest(),
            "error_kind": self.error_kind,
        }


# ── Compare Result ────────────────────────────────────────────────────


class GitHubCompareResult(_GitHubEvidenceModel):
    """Comparison between two commits (base vs head)."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    base_sha: str
    head_sha: str
    status: str = "unknown"  # identical, ahead, behind, diverged
    ahead_by: int = 0
    behind_by: int = 0
    total_commits: int = 0
    files_changed_count: int = 0
    additions: int = 0
    deletions: int = 0
    change_kind_counts: dict[str, int] = Field(default_factory=dict)
    truncated: bool = False
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "repository_hash": self.repository_hash,
            "base_sha": self.base_sha,
            "head_sha": self.head_sha,
            "status": self.status,
            "ahead_by": self.ahead_by,
            "behind_by": self.behind_by,
            "total_commits": self.total_commits,
            "files_changed_count": self.files_changed_count,
            "additions": self.additions,
            "deletions": self.deletions,
            "evidence_digest": self._evidence_digest(),
            "truncated": self.truncated,
            "error_kind": self.error_kind,
        }


# ── CI Status Evidence ────────────────────────────────────────────────


class GitHubCIStatusEvidence(_GitHubEvidenceModel):
    """Content-light CI status summary for a commit."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    commit_sha: str
    overall_state: str  # success, failure, pending, error, no_status
    passed_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    skipped_count: int = 0
    cancelled_count: int = 0
    neutral_count: int = 0
    total_count: int = 0
    check_names: list[str] = Field(  # bounded: only names, not logs
        default_factory=list
    )
    workflow_runs: list[dict[str, Any]] = Field(default_factory=list)
    truncated: bool = False
    error_kind: str | None = None
    suggested_next_action: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "repository_hash": self.repository_hash,
            "commit_sha": self.commit_sha,
            "overall_state": self.overall_state,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "pending_count": self.pending_count,
            "skipped_count": self.skipped_count,
            "cancelled_count": self.cancelled_count,
            "neutral_count": self.neutral_count,
            "total_count": self.total_count,
            "evidence_digest": self._evidence_digest(),
            "truncated": self.truncated,
            "error_kind": self.error_kind,
            "suggested_next_action": self.suggested_next_action,
        }


# ── Check Run Evidence ─────────────────────────────────────────────────


class GitHubCheckRunEvidence(_GitHubEvidenceModel):
    """Bounded check run evidence without log dumps."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    commit_sha: str
    check_run_id: int
    name: str
    status: str  # queued, in_progress, completed
    conclusion: str | None = None  # success, failure, neutral, cancelled, skipped
    details_url_hash: str | None = None
    app_name: str = ""
    started_at: str | None = None
    completed_at: str | None = None
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "repository_hash": self.repository_hash,
            "commit_sha": self.commit_sha,
            "check_run_id": self.check_run_id,
            "name": self.name,
            "status": self.status,
            "conclusion": self.conclusion,
            "app_name": self.app_name,
            "evidence_digest": self._evidence_digest(),
            "error_kind": self.error_kind,
        }


# ── Publication Verification ───────────────────────────────────────────


class GitHubPublicationVerification(_GitHubEvidenceModel):
    """Verify that an approved commit is present on a remote ref."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    expected_sha: str
    ref: str = "main"
    verification_status: str  # exact_promoted, accepted_with_follow_on_commits,
    # target_behind, target_divergent, expected_commit_missing,
    # remote_unavailable, permission_unavailable,
    # verification_incomplete
    remote_head_sha: str | None = None
    accepted_head_present: bool = False
    follow_on_commits_count: int = 0
    follow_on_head_sha: str | None = None
    ci_state: str | None = None  # summarized CI state at remote head
    ci_evidence: GitHubCIStatusEvidence | None = None
    error_kind: str | None = None
    suggested_next_action: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "repository_hash": self.repository_hash,
            "expected_sha": self.expected_sha,
            "ref": self.ref,
            "verification_status": self.verification_status,
            "remote_head_sha": self.remote_head_sha,
            "accepted_head_present": self.accepted_head_present,
            "follow_on_commits_count": self.follow_on_commits_count,
            "follow_on_head_sha": self.follow_on_head_sha,
            "ci_state": self.ci_state,
            "evidence_digest": self._evidence_digest(),
            "error_kind": self.error_kind,
            "suggested_next_action": self.suggested_next_action,
        }


# ── Error Vocabulary ───────────────────────────────────────────────────


class GitHubTruthErrorKind:
    """Typed error outcomes for the GitHub truth adapter."""

    REPOSITORY_INACCESSIBLE = "github.repository_inaccessible"
    INSTALLATION_MISSING = "github.installation_missing"
    PERMISSION_MISSING = "github.permission_missing"
    TOKEN_EXPIRED = "github.token_expired"
    TOKEN_ACQUISITION_FAILED = "github.token_acquisition_failed"
    RATE_LIMITED = "github.rate_limited"
    REF_MISSING = "github.ref_missing"
    COMMIT_ABSENT = "github.commit_absent"
    REMOTE_DIVERGENCE = "github.remote_divergence"
    MALFORMED_RESPONSE = "github.malformed_response"
    API_UNAVAILABLE = "github.api_unavailable"
    EVIDENCE_TRUNCATED = "github.evidence_truncated"
    REFUSED_BY_POLICY = "github.refused_by_policy"
    AUTHORIZATION_PENDING = "github.authorization_pending"
    DISCLOSURE_UNAVAILABLE = "github.disclosure_unavailable"
    TIMEOUT = "github.timeout"
    UNKNOWN = "github.unknown_error"


class GitHubVerificationStatus:
    """Publication verification status values."""

    EXACT_PROMOTED = "exact_promoted"
    ACCEPTED_WITH_FOLLOW_ON = "accepted_with_follow_on_commits"
    TARGET_BEHIND = "target_behind"
    TARGET_DIVERGENT = "target_divergent"
    EXPECTED_COMMIT_MISSING = "expected_commit_missing"
    REMOTE_UNAVAILABLE = "remote_unavailable"
    PERMISSION_UNAVAILABLE = "permission_unavailable"
    CI_PENDING = "ci_pending"
    CI_FAILING = "ci_failing"
    CI_SUCCESSFUL = "ci_successful"
    WORKFLOW_UNAVAILABLE = "workflow_evidence_unavailable"
    VERIFICATION_INCOMPLETE = "verification_incomplete"


class GitHubTokenStatus:
    AVAILABLE = "available"
    EXPIRED = "expired"
    UNAVAILABLE = "unavailable"
    ACQUISITION_FAILED = "acquisition_failed"


class GitHubCommitRelationship:
    EXACT = "exact"
    ANCESTOR = "ancestor"
    DESCENDANT = "descendant"
    DIVERGENT = "divergent"
    ABSENT = "absent"


__all__ = [
    "GitHubCIStatusEvidence",
    "GitHubCheckRunEvidence",
    "GitHubCommitPresence",
    "GitHubCommitRelationship",
    "GitHubCompareResult",
    "GitHubInstallationAccess",
    "GitHubPublicationVerification",
    "GitHubRemoteRefObservation",
    "GitHubRepositoryIdentity",
    "GitHubTokenStatus",
    "GitHubTruthErrorKind",
    "GitHubVerificationStatus",
]
