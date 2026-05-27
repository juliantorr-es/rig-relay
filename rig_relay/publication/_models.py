from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import hashlib
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    pass


class PreviewRefusalCode(StrEnum):
    """Structured refusal reasons for publication preview compilation."""

    APPROVAL_NOT_GRANTED = "approval_not_granted"
    PROFILE_ABSENT = "profile_absent"
    PROFILE_INVALID = "profile_invalid"
    PRIVACY_CLASS_UNSAFE = "privacy_class_unsafe"
    CONTENT_LIGHT_GUARANTEE_MISSING = "content_light_guarantee_missing"
    INTERNAL_ONLY_MATERIAL_DETECTED = "internal_only_material_detected"
    SCHEMA_MISMATCH = "schema_mismatch"
    READINESS_INCOMPATIBLE = "readiness_incompatible"
    PAGES_ACTION_INCOMPATIBLE = "pages_action_incompatible"
    SAFETY_SCAN_FAILED = "safety_scan_failed"
    POLICY_UNRECOGNIZED = "policy_unrecognized"
    PROFILE_STALE = "profile_stale"


class PreviewEvidenceReceipt(BaseModel):
    """Canonical evidence receipt for a publication preview compilation.

    Emitted for every compile or refusal outcome. Content-light — contains
    hashes and status, never raw file contents or private data.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.publication_preview_receipt.v1", frozen=True
    )
    receipt_id: str
    compiled_at: str
    compilation_successful: bool
    profile_candidate_digest: str
    result_digest: str | None = None
    refusal_code: str | None = None
    refusal_reasons: list[str] = Field(default_factory=list)
    safety_passed: bool = False
    deployment_ready: bool = False
    preview_only: bool = True
    evidence_digest: str = ""

    def compute_digest(self) -> str:
        from json import dumps

        canonical = {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "compiled_at": self.compiled_at,
            "compilation_successful": self.compilation_successful,
            "profile_candidate_digest": self.profile_candidate_digest,
            "result_digest": self.result_digest,
            "refusal_code": self.refusal_code,
            "refusal_reasons": sorted(self.refusal_reasons),
            "safety_passed": self.safety_passed,
            "deployment_ready": self.deployment_ready,
            "preview_only": self.preview_only,
        }
        payload = dumps(canonical, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"


class PublicationPreviewRefusal(BaseModel):
    """Structured refusal when preview compilation cannot proceed."""

    model_config = ConfigDict(extra="forbid")

    refusal_code: PreviewRefusalCode
    reasons: list[str] = Field(default_factory=list)
    receipt: PreviewEvidenceReceipt | None = None


class PublicationPreviewResult(BaseModel):
    """Application-service result for a publication preview compilation.

    Contains the full compiler result plus canonical evidence receipt.
    """

    model_config = ConfigDict(extra="forbid")

    compiler_result: ProjectPageCompilerResult
    receipt: PreviewEvidenceReceipt
    refused: PreviewRefusalCode | None = None

    @property
    def success(self) -> bool:
        return self.refused is None and self.compiler_result.compilation_successful


class ProjectPageCompilerInput(BaseModel):
    """Internal compiler input — constructed from typed models, not raw dicts.

    The application service validates live producer-compatible input before
    constructing this internal input shape.
    """

    model_config = ConfigDict(extra="forbid")

    profile_candidate: dict = Field(
        description="L0-shaped PublishableProjectProfileCandidate as dict (model_dump)"
    )
    publication_readiness: dict | None = Field(
        default=None, description="J0 PublicationReadiness as dict"
    )
    pages_action: dict | None = Field(
        default=None, description="J0 PagesActionPreparation as dict"
    )
    narrative_approvals: dict[str, str] = Field(
        default_factory=dict,
        description="Map of narrative section key → approval status",
    )
    publication_policy: str = Field(
        default="preview_only",
        description="Publication policy: preview_only (default), developer_approved, or public_release",
    )
    project_repo_owner: str = Field(
        default="", description="Repository owner for Pages URL construction"
    )
    project_repo_name: str = Field(
        default="", description="Repository name for Pages URL construction"
    )


class ProjectPagePublicationProjection(BaseModel):
    """Content-light projection conforming to rig.relay.publication_projection.v1.

    This is the frontend-consumable contract that P0 may consume after R0 release.
    It is the project_page surface — distinct from the portfolio_site surface.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.publication_projection.v1", frozen=True
    )
    publication_surface: str = Field(default="project_page", frozen=True)
    projection_id: str
    content_light_guarantee: bool = Field(default=True, frozen=True)
    privacy_class: str = Field(default="public_safe", frozen=True)
    projection_digest: str
    generated_at: str

    project_identity: dict
    status_overview: dict
    accomplishments: dict
    released_boundaries: dict
    mission_timeline: dict
    architecture_overview: dict = Field(default_factory=dict)
    capability_views: dict = Field(default_factory=dict)
    audit_proofs: list[str] = Field(default_factory=list)
    changelog: list[dict] = Field(default_factory=list)
    screenshots_demos: list[str] = Field(default_factory=list)

    def compute_digest(self) -> str:
        raw = (
            f"{self.schema_version}:{self.projection_id}:"
            f"{self.publication_surface}:{self.project_identity.get('project_name', '')}"
        )
        return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


class WithheldSummary(BaseModel):
    """What was withheld from the public output and why."""

    model_config = ConfigDict(extra="forbid")

    total_items_withheld: int = 0
    total_items_redacted: int = 0
    internal_facts_count: int = 0
    evidence_references_count: int = 0
    raw_paths_removed: int = 0
    reasons: list[str] = Field(default_factory=list)


class ProposedContentSummary(BaseModel):
    """Generated/model-produced content status — all proposed unless approved."""

    model_config = ConfigDict(extra="forbid")

    total_sections: int = 0
    sections_proposed: int = 0
    sections_approved: int = 0
    sections_rejected: int = 0
    sections: list[dict] = Field(default_factory=list)
    requires_developer_review: bool = True


class PublicationReadinessSummary(BaseModel):
    """J0 publication readiness rendered for the preview report."""

    model_config = ConfigDict(extra="forbid")

    has_pages: bool = False
    pages_build_status: str | None = None
    publication_eligible: bool = False
    readiness_state: str = "unknown"
    blockers: list[str] = Field(default_factory=list)
    pages_action_state: str = "planned"
    pages_action_requires_approval: bool = True
    pages_action_will_mutate_remote: bool = False
    suggested_next_action: str | None = None


class ProjectPagePreviewReport(BaseModel):
    """Report describing what is public, withheld, proposed, and what actions remain."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.project_page_preview_report.v1", frozen=True
    )
    report_id: str
    projection_id: str
    generated_at: str

    public_section_count: int = 0
    withheld: WithheldSummary = Field(default_factory=WithheldSummary)
    proposed_content: ProposedContentSummary = Field(
        default_factory=ProposedContentSummary
    )
    publication_readiness: PublicationReadinessSummary = Field(
        default_factory=PublicationReadinessSummary
    )
    approval_gate_passed: bool = False
    safety_scan_passed: bool = False
    schema_validation_passed: bool = False
    ready_for_preview: bool = False
    ready_for_deployment: bool = False

    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class PublicationSafetyReport(BaseModel):
    """Safety scan result for the compiled project page output."""

    model_config = ConfigDict(extra="forbid")

    passed: bool
    scan_id: str
    scanned_at: str
    total_fields_checked: int = 0
    forbidden_content_found: list[str] = Field(default_factory=list)
    secrets_detected: bool = False
    raw_paths_detected: bool = False
    private_content_detected: bool = False
    proposed_marked_as_approved: bool = False
    warnings: list[str] = Field(default_factory=list)


class ProjectPageCompilerResult(BaseModel):
    """Complete compiler output — projection, static bundle, and preview report."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(
        default="rig.relay.project_page_compiler_result.v1", frozen=True
    )
    result_id: str
    compiler_digest: str
    generated_at: str

    projection: ProjectPagePublicationProjection
    static_bundle_path: str | None = None
    static_bundle_digest: str | None = None
    preview_report: ProjectPagePreviewReport
    safety_report: PublicationSafetyReport

    compilation_successful: bool
    deployment_ready: bool = False
    warnings: list[str] = Field(default_factory=list)

    def compute_result_digest(self) -> str:
        raw = (
            f"{self.result_id}:{self.projection.projection_digest}:"
            f"{self.preview_report.report_id}"
        )
        return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _digest_sha256(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"
