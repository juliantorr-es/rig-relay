"""Deployment and portfolio synthesis models for Lane X3.1.

X3.1 repairs: truthful status model, T1.2 evidence binding, deterministic
portfolio output, safe HTML contract, approval-gated synthesis.
"""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field


class DeploymentRefusalCode(StrEnum):
    """Structured refusal reasons for publication deployment."""

    PREVIEW_NOT_APPROVED = "preview_not_approved"
    SAFETY_NOT_PASSED = "safety_not_passed"
    COMPILATION_FAILED = "compilation_failed"
    EVIDENCE_DIGEST_MISMATCH = "evidence_digest_mismatch"
    EVIDENCE_RECEIPT_ABSENT = "evidence_receipt_absent"
    EVIDENCE_RECEIPT_CORRUPT = "evidence_receipt_corrupt"
    CONTENT_LIGHT_VIOLATION = "content_light_violation"
    AUTHORIZATION_MISSING = "authorization_missing"
    AUTHORIZATION_REVOKED = "authorization_revoked"
    AUTHORIZATION_EXPIRED = "authorization_expired"
    AUTHORIZATION_DIGEST_MISMATCH = "authorization_digest_mismatch"
    PAGES_NOT_CONFIGURED = "pages_not_configured"
    PAGES_CONFIG_FAILED = "pages_config_failed"
    PERMISSION_MISSING = "permission_missing"
    CONTENT_PUSH_FAILED = "content_push_failed"
    BRANCH_CREATION_FAILED = "branch_creation_failed"
    REMOTE_BUILD_FAILED = "remote_build_failed"
    REMOTE_VERIFICATION_FAILED = "remote_verification_failed"
    REMOTE_STATUS_INDETERMINATE = "remote_status_indeterminate"
    STALE_OPERATION = "stale_operation"
    IDEMPOTENCY_CONFLICT = "idempotency_conflict"
    REPO_NOT_FOUND = "repo_not_found"
    STATIC_CONTENT_MISSING = "static_content_missing"
    INSUFFICIENT_PERMISSIONS = "insufficient_permissions"


class DeploymentPhase(StrEnum):
    """Truthful deployment phases — X3.1 repair #5 status model."""

    PREPARED = "prepared"
    AUTHORIZATION_PENDING = "authorization_pending"
    AUTHORIZED = "authorized"
    PAGES_CONFIGURING = "pages_configuring"
    PAGES_CONFIGURED = "pages_configured"
    CONTENT_PUBLISHING = "content_publishing"
    CONTENT_PUBLISHED = "content_published"
    BUILD_PENDING = "build_pending"
    PUBLISHED_VERIFIED = "published_verified"
    REFUSED = "refused"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"


class DeploymentPreparationResult(BaseModel):
    """Result of deployment readiness inspection before any mutation.

    X3.1 repair #2: binds real T1.2 PreviewEvidenceReceipt.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.publication_deployment_preparation.v1", frozen=True
    )
    preparation_id: str
    operation_id: str
    ready_to_deploy: bool = False
    compilation_valid: bool = False
    safety_valid: bool = False
    preview_evidence_valid: bool = False
    preview_evidence_digest: str = ""
    preview_receipt_digest: str = ""
    approval_gate_passed: bool = False
    content_digest: str = ""
    pages_ready: bool = False
    pages_site_exists: bool = False
    pages_requires_create: bool = False
    pages_requires_update: bool = False
    pages_target_repo: str = ""
    pages_source_branch: str = ""
    pages_source_path: str = ""
    static_content_available: bool = False
    static_content_digest: str = ""
    static_bundle_path: str = ""
    authorization_required: bool = True
    authorization_request_digest: str = ""
    blockers: list[str] = Field(default_factory=list)
    suggested_action: str = ""
    prepared_at: str = ""
    evidence_digest: str = ""

    def compute_digest(self) -> str:
        canonical = {
            "schema_version": self.schema_version,
            "preparation_id": self.preparation_id,
            "operation_id": self.operation_id,
            "ready_to_deploy": self.ready_to_deploy,
            "compilation_valid": self.compilation_valid,
            "safety_valid": self.safety_valid,
            "preview_evidence_valid": self.preview_evidence_valid,
            "preview_evidence_digest": self.preview_evidence_digest,
            "preview_receipt_digest": self.preview_receipt_digest,
            "approval_gate_passed": self.approval_gate_passed,
            "content_digest": self.content_digest,
            "pages_target_repo": self.pages_target_repo,
            "static_content_digest": self.static_content_digest,
            "authorization_required": self.authorization_required,
            "blockers": sorted(self.blockers),
        }
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        self.evidence_digest = f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"
        return self.evidence_digest


class DeploymentOutcomeReceipt(BaseModel):
    """Canonical evidence receipt for a publication deployment outcome.

    X3.1 repairs #5 and #6: truthful phase, evidence integrity.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.publication_deployment_evidence.v1", frozen=True
    )
    receipt_id: str
    operation_id: str
    preparation_digest: str = ""
    profile_candidate_digest: str
    preview_evidence_digest: str
    preview_receipt_digest: str = ""
    compilation_result_digest: str = ""
    authorization_receipt_digest: str = ""
    deployment_phase: str = ""
    pages_site_url: str = ""
    pages_build_status: str = ""
    pages_configured: bool = False
    content_published: bool = False
    build_initiated: bool = False
    refusal_code: str | None = None
    refusal_reasons: list[str] = Field(default_factory=list)
    remote_request_sent: bool = False
    remote_verified: bool = False
    remote_verification_digest: str = ""
    recovery_required: bool = False
    recovery_hint: str = ""
    deployed_at: str = ""
    evidence_digest: str = ""

    def compute_digest(self) -> str:
        canonical = {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "operation_id": self.operation_id,
            "preparation_digest": self.preparation_digest,
            "profile_candidate_digest": self.profile_candidate_digest,
            "preview_evidence_digest": self.preview_evidence_digest,
            "preview_receipt_digest": self.preview_receipt_digest,
            "compilation_result_digest": self.compilation_result_digest,
            "authorization_receipt_digest": self.authorization_receipt_digest,
            "deployment_phase": self.deployment_phase,
            "pages_site_url": self.pages_site_url,
            "pages_build_status": self.pages_build_status,
            "pages_configured": self.pages_configured,
            "content_published": self.content_published,
            "build_initiated": self.build_initiated,
            "refusal_code": self.refusal_code,
            "refusal_reasons": sorted(self.refusal_reasons),
            "remote_request_sent": self.remote_request_sent,
            "remote_verified": self.remote_verified,
            "remote_verification_digest": self.remote_verification_digest,
            "recovery_required": self.recovery_required,
            "deployed_at": self.deployed_at,
        }
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


class DeploymentRecoveryState(BaseModel):
    """Recovery state for a deployment operation that needs retry/reconcile."""

    model_config = ConfigDict(extra="forbid")

    operation_id: str
    prior_attempt_receipt_digest: str
    prior_phase: str
    prior_remote_verified: bool = False
    prior_remote_sent: bool = False
    prior_authorization_consumed: bool = False
    prior_pages_configured: bool = False
    prior_content_published: bool = False
    recovery_action: str = ""
    recovery_blockers: list[str] = Field(default_factory=list)
    recoverable: bool = False


# ── Verified approved publication record ───────────────────────────────


class VerifiedApprovedProjectPublicationRecord(BaseModel):
    """Verified approved project publication record for portfolio synthesis.

    X3.1 repair #7: only verified records may enter portfolio synthesis.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.publication_verified_project_record.v1", frozen=True
    )
    record_id: str
    profile_candidate_digest: str
    preview_evidence_digest: str
    preview_receipt_digest: str = ""
    compilation_result_digest: str
    approval_evidence_digest: str = ""
    safety_passed: bool = False
    privacy_class: str = "public_safe"
    content_light_guarantee: bool = True
    publication_surface: str = "project_page"
    projection: dict = Field(default_factory=dict)
    projection_digest: str = ""
    verified: bool = False
    verification_digest: str = ""

    def compute_digest(self) -> str:
        raw = (
            f"{self.record_id}:{self.profile_candidate_digest}:"
            f"{self.preview_evidence_digest}:{self.compilation_result_digest}:"
            f"{self.projection_digest}"
        )
        return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


# ── Portfolio Synthesis Models ──────────────────────────────────────────


class PortfolioProjectionRejection(BaseModel):
    """A project record rejected from portfolio synthesis with reason."""

    model_config = ConfigDict(extra="forbid")

    profile_candidate_digest: str
    compilation_receipt_digest: str
    rejection_reason: str
    rejection_detail: str = ""


class PortfolioSynthesisInput(BaseModel):
    """Input for portfolio synthesis from verified approved records.

    X3.1 repair #7: requires VerifiedApprovedProjectPublicationRecord list.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.publication_portfolio_synthesis.v1", frozen=True
    )
    developer_display_name: str = ""
    developer_headline: str = ""
    developer_bio: str = ""
    verified_records: list = Field(
        default_factory=list,
        description="List of VerifiedApprovedProjectPublicationRecord instances",
    )
    portfolio_title: str = "Developer Portfolio"


class PortfolioSynthesisResult(BaseModel):
    """Result of portfolio synthesis.

    X3.1 repair #9: operation identity separate from content digest.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.publication_portfolio_synthesis.v1", frozen=True
    )
    synthesis_id: str
    generated_at: str
    compilation_successful: bool = False
    total_project_records: int = 0
    included_count: int = 0
    rejected_count: int = 0
    rejected_records: list[PortfolioProjectionRejection] = Field(default_factory=list)
    portfolio_projection: dict = Field(default_factory=dict)
    portfolio_html: str | None = None
    portfolio_html_digest: str | None = None
    portfolio_bundle_path: str | None = None
    content_digest: str = ""
    synthesis_digest: str = ""
    content_light_guarantee: bool = True
    privacy_class: str = "public_safe"
    safety_passed: bool = False
    safety_warnings: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    ready_for_deployment: bool = False


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _digest_sha256(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


__all__ = [
    "DeploymentOutcomeReceipt",
    "DeploymentPhase",
    "DeploymentPreparationResult",
    "DeploymentRecoveryState",
    "DeploymentRefusalCode",
    "PortfolioProjectionRejection",
    "PortfolioSynthesisInput",
    "PortfolioSynthesisResult",
    "VerifiedApprovedProjectPublicationRecord",
]
