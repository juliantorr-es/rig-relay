"""GitHub Issue Intake and CI/CD Diagnostic Models — bounded, content-light evidence.

Issue intake: bounded issue evidence with confidential default body handling.
CI diagnostics: job-level analysis, bounded failure classification, log protection.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class _GitHubDiagnosticModel(BaseModel):
    def _evidence_digest(self) -> str:
        raw = self.model_dump_json()
        return f"sha256:{hashlib.sha256(raw.encode('utf-8')).hexdigest()}"

    def redacted_projection(self) -> dict[str, Any]:
        raise NotImplementedError


# ── Issue Evidence ─────────────────────────────────────────────────────


class GitHubIssueEvidence(_GitHubDiagnosticModel):
    """Bounded issue evidence. Body is never stored raw — only hash."""

    model_config = ConfigDict(extra="forbid")

    issue_number: int
    title: str
    state: str  # open, closed
    labels: list[str] = Field(default_factory=list)
    assignee_hash: str | None = None
    milestone_title: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    comments_count: int = 0
    body_hash: str | None = None
    body_available: bool = False
    locked: bool = False
    url_hash: str | None = None
    evidence_digest_val: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "issue_number": self.issue_number,
            "title": self.title,
            "state": self.state,
            "labels": self.labels,
            "comments_count": self.comments_count,
            "body_available": self.body_available,
            "evidence_digest": self.evidence_digest_val or self._evidence_digest(),
        }


class GitHubIssueListResult(_GitHubDiagnosticModel):
    """Paginated issue list with truncation truth."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    issues: list[GitHubIssueEvidence] = Field(default_factory=list)
    total_count: int = 0
    returned_count: int = 0
    page: int = 1
    has_more: bool = False
    truncated: bool = False
    error_kind: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "repository_hash": self.repository_hash,
            "total_count": self.total_count,
            "returned_count": self.returned_count,
            "has_more": self.has_more,
            "truncated": self.truncated,
            "evidence_digest": self._evidence_digest(),
            "error_kind": self.error_kind,
        }


# ── CI/CD Diagnostic Models ────────────────────────────────────────────


class GitHubWorkflowJobEvidence(_GitHubDiagnosticModel):
    """Job-level CI evidence without raw log access."""

    model_config = ConfigDict(extra="forbid")

    job_id: int
    run_id: int
    name: str
    status: str  # queued, in_progress, completed
    conclusion: str | None = None  # success, failure, cancelled, skipped
    started_at: str | None = None
    completed_at: str | None = None
    steps_count: int = 0
    failed_steps_count: int = 0
    failed_step_names: list[str] = Field(default_factory=list)
    logs_url_hash: str | None = None
    logs_available: bool = False
    logs_withheld: bool = True  # default: logs not available to model

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "run_id": self.run_id,
            "name": self.name,
            "status": self.status,
            "conclusion": self.conclusion,
            "steps_count": self.steps_count,
            "failed_steps_count": self.failed_steps_count,
            "logs_withheld": self.logs_withheld,
            "evidence_digest": self._evidence_digest(),
        }


class GitHubCIDiagnosticEvidence(_GitHubDiagnosticModel):
    """Deep CI/CD diagnostic evidence — bounded, content-light."""

    model_config = ConfigDict(extra="forbid")

    repository_hash: str
    commit_sha: str | None = None

    # Run summary
    total_runs: int = 0
    success_runs: int = 0
    failure_runs: int = 0
    pending_runs: int = 0
    cancelled_runs: int = 0

    # Failure classification
    failure_reasons: list[str] = Field(default_factory=list)
    flaky_indicator: bool = False

    # Job diagnostics
    jobs: list[GitHubWorkflowJobEvidence] = Field(default_factory=list)
    failed_jobs: list[GitHubWorkflowJobEvidence] = Field(default_factory=list)

    # Bounded log evidence
    log_analysis_available: bool = False
    log_analysis_withheld: bool = True  # default: Lane A authorization needed
    log_evidence_hash: str | None = None

    truncated: bool = False
    error_kind: str | None = None
    suggested_next_action: str | None = None

    def redacted_projection(self) -> dict[str, Any]:
        return {
            "repository_hash": self.repository_hash,
            "commit_sha": self.commit_sha,
            "total_runs": self.total_runs,
            "success_runs": self.success_runs,
            "failure_runs": self.failure_runs,
            "pending_runs": self.pending_runs,
            "cancelled_runs": self.cancelled_runs,
            "failure_reasons_count": len(self.failure_reasons),
            "failed_jobs_count": len(self.failed_jobs),
            "log_analysis_withheld": self.log_analysis_withheld,
            "truncated": self.truncated,
            "evidence_digest": self._evidence_digest(),
            "error_kind": self.error_kind,
            "suggested_next_action": self.suggested_next_action,
        }


# ── Error Vocabulary ───────────────────────────────────────────────────


class GitHubDiagnosticErrorKind:
    ISSUE_LIST_FAILED = "github.issue.list_failed"
    CI_LIST_RUNS_FAILED = "github.ci.list_runs_failed"
    CI_LIST_JOBS_FAILED = "github.ci.list_jobs_failed"
    CI_LOG_ACCESS_FAILED = "github.ci.log_access_failed"
    PERMISSION_MISSING = "github.diagnostic.permission_missing"
    RATE_LIMITED = "github.diagnostic.rate_limited"
    API_UNAVAILABLE = "github.diagnostic.api_unavailable"
    LOGS_WITHHELD = "github.diagnostic.logs_withheld"
    AUTHORIZATION_PENDING = "github.diagnostic.authorization_pending"
    UNKNOWN = "github.diagnostic.unknown_error"


__all__ = [
    "GitHubCIDiagnosticEvidence",
    "GitHubDiagnosticErrorKind",
    "GitHubIssueEvidence",
    "GitHubIssueListResult",
    "GitHubWorkflowJobEvidence",
]
