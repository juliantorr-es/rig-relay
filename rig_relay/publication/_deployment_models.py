"""Deployment and portfolio synthesis models for Lane X3.2.

X3.2 architecture:
  Gate A — AuthorizedPublicationTransitionPreparation bridges T1.2 → deployment
  Gate B — ApprovedStaticPublicationBundle enforces digest-bound content
  Gate C — PublicationTransitionPhase: truthful Pages configuration states
  Gate D — PublicationTransitionReceipt: linked state-transition evidence
  Gate E — VerifiedApprovedProjectPublicationRecord: binds real T1.2 receipts
  Gate F — PublicationStatusContract: X0-consumable status projection
"""

from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DeploymentRefusalCode(StrEnum):
    PREVIEW_NOT_APPROVED = "preview_not_approved"
    SAFETY_NOT_PASSED = "safety_not_passed"
    COMPILATION_FAILED = "compilation_failed"
    EVIDENCE_DIGEST_MISMATCH = "evidence_digest_mismatch"
    EVIDENCE_RECEIPT_ABSENT = "evidence_receipt_absent"
    EVIDENCE_RECEIPT_CORRUPT = "evidence_receipt_corrupt"
    TRANSITION_PREPARATION_INVALID = "transition_preparation_invalid"
    BUNDLE_DIGEST_MISMATCH = "bundle_digest_mismatch"
    BUNDLE_CONTENT_EMPTY = "bundle_content_empty"
    BUNDLE_PATH_UNSAFE = "bundle_path_unsafe"
    AUTHORIZATION_MISSING = "authorization_missing"
    AUTHORIZATION_REVOKED = "authorization_revoked"
    AUTHORIZATION_EXPIRED = "authorization_expired"
    AUTHORIZATION_DIGEST_MISMATCH = "authorization_digest_mismatch"
    PAGES_CONFIG_FAILED = "pages_config_failed"
    PAGES_CREATE_FAILED = "pages_create_failed"
    PAGES_UPDATE_FAILED = "pages_update_failed"
    PAGES_INSPECT_FAILED = "pages_inspect_failed"
    CONTENT_PUSH_FAILED = "content_push_failed"
    CONTENT_PUSH_PARTIAL = "content_push_partial"
    REPO_NOT_FOUND = "repo_not_found"


class PublicationTransitionPhase(StrEnum):
    PREPARED = "prepared"
    AUTHORIZATION_REQUIRED = "authorization_required"
    AUTHORIZED = "authorized"
    PAGES_CONFIGURATION_UNCHANGED = "pages_configuration_unchanged"
    PAGES_CREATED = "pages_created"
    PAGES_UPDATED = "pages_updated"
    CONTENT_PUBLICATION_STARTED = "content_publication_started"
    CONTENT_PUBLICATION_PARTIAL = "content_publication_partial"
    CONTENT_PUBLISHED = "content_published"
    BUILD_REQUESTED = "build_requested"
    BUILD_PENDING = "build_pending"
    PUBLISHED_VERIFIED = "published_verified"
    REFUSED = "refused"
    FAILED = "failed"
    RECOVERY_REQUIRED = "recovery_required"


class AuthorizedPublicationTransitionPreparation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.relay.publication_transition_preparation.v1", frozen=True
    )
    publication_operation_id: str
    preview_operation_id: str = ""
    preview_evidence_digest: str
    preview_receipt_digest: str = ""
    preview_result_digest: str = ""
    static_bundle_digest: str
    target_repository_identity_digest: str
    target_surface: str = "project_page"
    source_branch: str = "gh-pages"
    source_path: str = "/"
    requested_pages_action: str = "configure_and_deploy"
    publication_policy: str = "public_release"
    authorization_required: bool = True
    preparation_digest: str = ""
    created_at: str = ""
    evidence_digest: str = ""

    def compute_digest(self) -> str:
        c = {
            "schema_version": self.schema_version,
            "publication_operation_id": self.publication_operation_id,
            "preview_operation_id": self.preview_operation_id,
            "preview_evidence_digest": self.preview_evidence_digest,
            "preview_receipt_digest": self.preview_receipt_digest,
            "preview_result_digest": self.preview_result_digest,
            "static_bundle_digest": self.static_bundle_digest,
            "target_repository_identity_digest": self.target_repository_identity_digest,
            "target_surface": self.target_surface,
            "source_branch": self.source_branch,
            "source_path": self.source_path,
            "requested_pages_action": self.requested_pages_action,
            "publication_policy": self.publication_policy,
            "authorization_required": self.authorization_required,
        }
        p = json.dumps(c, sort_keys=True, separators=(",", ":"))
        d = f"sha256:{hashlib.sha256(p.encode()).hexdigest()}"
        self.preparation_digest = d
        self.evidence_digest = d
        return d


class ApprovedStaticPublicationBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.relay.publication_static_bundle.v1", frozen=True
    )
    files: dict[str, str] = Field(default_factory=dict)
    content_digest: str = ""
    preview_result_digest: str = ""
    preparation_digest: str = ""
    target_surface: str = "project_page"
    safety_scan_digest: str = ""
    evidence_digest: str = ""

    def compute_content_digest(self) -> str:
        parts = [f"{p}:{c}" for p, c in sorted(self.files.items())]
        raw = "\n".join(parts)
        self.content_digest = f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"
        return self.content_digest

    def validate_paths(self) -> list[str]:
        v: list[str] = []
        for path in self.files:
            if ".." in path or path.startswith("/"):
                v.append(f"unsafe_path:{path}")
            if path.startswith(".github/") or ".secret" in path.lower():
                v.append(f"restricted_path:{path}")
            if not path.endswith((
                ".html",
                ".css",
                ".js",
                ".svg",
                ".png",
                ".jpg",
                ".ico",
                ".json",
                ".txt",
            )):
                v.append(f"unsupported_extension:{path}")
        return v

    def is_empty(self) -> bool:
        return len(self.files) == 0

    @classmethod
    def from_compiler_result(
        cls,
        compiler_result: Any,
        *,
        preparation_digest: str = "",
        target_surface: str = "project_page",
    ) -> ApprovedStaticPublicationBundle | None:
        bundle_path = getattr(compiler_result, "static_bundle_path", None)
        if not bundle_path:
            return None
        import os
        from pathlib import Path as _Path

        bp = _Path(bundle_path)
        if not bp.is_dir():
            return None
        files: dict[str, str] = {}
        for root_str, _dirs, filenames in os.walk(str(bp)):
            root = _Path(root_str)
            for fn in filenames:
                full = root / fn
                rel = str(full.relative_to(bp))
                try:
                    files[rel] = full.read_text(encoding="utf-8")
                except (UnicodeDecodeError, OSError):
                    continue
        b = cls(
            files=files,
            preview_result_digest=getattr(
                compiler_result, "compute_result_digest", lambda: ""
            )(),
        )
        b.compute_content_digest()
        return b


class ContentPublicationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.relay.publication_content_manifest.v1", frozen=True
    )
    operation_id: str
    bundle_content_digest: str
    target_branch: str
    expected_files: list[str] = Field(default_factory=list)
    published_files: list[str] = Field(default_factory=list)
    failed_files: list[dict] = Field(default_factory=list)
    publication_complete: bool = False
    publication_partial: bool = False
    evidence_digest: str = ""

    def compute_digest(self) -> str:
        c = {
            "operation_id": self.operation_id,
            "bundle_content_digest": self.bundle_content_digest,
            "target_branch": self.target_branch,
            "expected_count": len(self.expected_files),
            "published_count": len(self.published_files),
            "failed_count": len(self.failed_files),
            "complete": self.publication_complete,
            "partial": self.publication_partial,
        }
        p = json.dumps(c, sort_keys=True, separators=(",", ":"))
        self.evidence_digest = f"sha256:{hashlib.sha256(p.encode()).hexdigest()}"
        return self.evidence_digest


class PublicationTransitionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.relay.publication_transition_receipt.v1", frozen=True
    )
    receipt_id: str
    operation_id: str
    transition_preparation_digest: str = ""
    preview_evidence_digest: str = ""
    preview_receipt_digest: str = ""
    static_bundle_digest: str = ""
    authorization_receipt_digest: str = ""
    transition_phase: str = ""
    pages_site_url: str = ""
    pages_build_status: str = ""
    pages_created: bool = False
    pages_updated: bool = False
    content_publication_manifest_digest: str = ""
    content_published: bool = False
    build_initiated: bool = False
    remote_verified: bool = False
    remote_verification_digest: str = ""
    refusal_code: str | None = None
    refusal_reasons: list[str] = Field(default_factory=list)
    recovery_required: bool = False
    recovery_hint: str = ""
    deployed_at: str = ""
    evidence_digest: str = ""

    def compute_digest(self) -> str:
        c = {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "operation_id": self.operation_id,
            "transition_preparation_digest": self.transition_preparation_digest,
            "preview_evidence_digest": self.preview_evidence_digest,
            "preview_receipt_digest": self.preview_receipt_digest,
            "static_bundle_digest": self.static_bundle_digest,
            "authorization_receipt_digest": self.authorization_receipt_digest,
            "transition_phase": self.transition_phase,
            "pages_site_url": self.pages_site_url,
            "pages_build_status": self.pages_build_status,
            "pages_created": self.pages_created,
            "pages_updated": self.pages_updated,
            "content_publication_manifest_digest": self.content_publication_manifest_digest,
            "content_published": self.content_published,
            "build_initiated": self.build_initiated,
            "remote_verified": self.remote_verified,
            "remote_verification_digest": self.remote_verification_digest,
            "refusal_code": self.refusal_code,
            "refusal_reasons": sorted(self.refusal_reasons),
            "recovery_required": self.recovery_required,
            "deployed_at": self.deployed_at,
        }
        p = json.dumps(c, sort_keys=True, separators=(",", ":"))
        return f"sha256:{hashlib.sha256(p.encode()).hexdigest()}"


class VerifiedApprovedProjectPublicationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.relay.publication_verified_project_record.v1", frozen=True
    )
    record_id: str
    profile_candidate_digest: str
    preview_evidence_digest: str
    preview_receipt_digest: str = ""
    compilation_successful: bool = False
    safety_passed: bool = False
    refusal_code: str | None = None
    compilation_result_digest: str = ""
    transition_preparation_digest: str = ""
    authorization_evidence_digest: str = ""
    privacy_class: str = "public_safe"
    content_light_guarantee: bool = True
    publication_surface: str = "project_page"
    projection: dict = Field(default_factory=dict)
    projection_digest: str = ""
    verified: bool = False
    verification_digest: str = ""

    def compute_digest(self) -> str:
        raw = f"{self.record_id}:{self.profile_candidate_digest}:{self.preview_evidence_digest}:{self.compilation_result_digest}:{self.transition_preparation_digest}:{self.projection_digest}"
        return f"sha256:{hashlib.sha256(raw.encode()).hexdigest()}"


class PortfolioProjectionRejection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    profile_candidate_digest: str
    compilation_receipt_digest: str
    rejection_reason: str
    rejection_detail: str = ""


class PortfolioSynthesisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str = Field(
        default="rig.relay.publication_portfolio_synthesis.v1", frozen=True
    )
    developer_display_name: str = ""
    developer_headline: str = ""
    developer_bio: str = ""
    verified_records: list = Field(default_factory=list)
    portfolio_title: str = "Developer Portfolio"


class PortfolioSynthesisResult(BaseModel):
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


class PublicationStatusContract(BaseModel):
    """X3.3 Gate G — X0-consumable typed publication surface state."""

    model_config = ConfigDict(extra="forbid")
    schema_version: str = "rig.relay.publication_status.v1"
    publication_operation_id: str
    transition_phase: str = PublicationTransitionPhase.PREPARED.value
    target_repository_digest: str = ""
    target_surface: str = ""
    authorization_required: bool = True
    authorization_status: str = "pending"
    pages_configured: bool = False
    content_published: bool = False
    content_publication_mode: str = "none"
    published_commit_sha: str = ""
    build_status: str = ""
    build_commit_sha: str = ""
    build_commit_matches_published: bool = False
    published_verified: bool = False
    refusal_code: str | None = None
    recovery_required: bool = False
    status_message: str = ""
    available_actions: list[str] = Field(default_factory=list)
    evidence_digest: str = ""


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def _digest_sha256(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode()).hexdigest()}"


__all__ = [
    "ApprovedStaticPublicationBundle",
    "AuthorizedPublicationTransitionPreparation",
    "ContentPublicationManifest",
    "DeploymentRefusalCode",
    "PortfolioProjectionRejection",
    "PortfolioSynthesisInput",
    "PortfolioSynthesisResult",
    "PublicationStatusContract",
    "PublicationTransitionPhase",
    "PublicationTransitionReceipt",
    "VerifiedApprovedProjectPublicationRecord",
]
