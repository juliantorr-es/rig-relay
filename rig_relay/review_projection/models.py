from __future__ import annotations

from enum import StrEnum, auto
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FileClassification(StrEnum):
    PUBLIC_ALREADY_DISCLOSED = auto()
    TRANSFORM_ALLOWED = auto()
    CONFIDENTIAL_HOLDBACK = auto()
    EXCLUDED_SECRET_OR_PRIVATE_MATERIAL = auto()
    GENERATED_OR_PROJECTION_SENSITIVE = auto()
    UNCLASSIFIED_REFUSED = auto()


class ProjectionMode(StrEnum):
    MAINTAINABILITY_REVIEW = auto()
    MINIMIZED_BUG_REPRODUCTION = auto()
    PUBLIC_BASELINE_REVIEW = auto()


class PublicBaselineAttestation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    
    schema_version: Literal["rig.review_projection.public_attestation.v1"] = "rig.review_projection.public_attestation.v1"
    commit_sha: str
    verified_files: dict[str, str] = Field(description="Mapping of relative path to blob hash")
    verification_timestamp: str
    source: str


class ReviewProjectionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["rig.review_projection.policy.v1"] = "rig.review_projection.policy.v1"
    confidential_categories: list[str] = Field(default_factory=list)
    secret_patterns: list[str] = Field(default_factory=list)
    allowed_domains: list[str] = Field(default_factory=list)


class InclusionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["rig.review_projection.inclusion_manifest.v1"] = "rig.review_projection.inclusion_manifest.v1"
    mode: ProjectionMode
    approved_files: list[str] = Field(default_factory=list)
    approved_globs: list[str] = Field(default_factory=list)
    exclude_overrides: list[str] = Field(default_factory=list)


class BundleManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["rig.review_projection.bundle_manifest.v1"] = "rig.review_projection.bundle_manifest.v1"
    status: Literal["review_projection_candidate"] = "review_projection_candidate"
    incomplete_warning: bool = True
    execution_prohibited: bool = True
    mode: ProjectionMode
    transformed_files: list[str] = Field(default_factory=list)
    excluded_counts: dict[str, int] = Field(default_factory=dict)
    applied_transformers: list[str] = Field(default_factory=list)


class LocalCrosswalk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["rig.review_projection.local_crosswalk.v1"] = "rig.review_projection.local_crosswalk.v1"
    projection_id: str
    local_only_warning: bool = True
    export_prohibited: bool = True
    mappings: dict[str, str] = Field(default_factory=dict)
    excluded_concrete_paths: list[str] = Field(default_factory=list)
    local_policy_matches: list[str] = Field(default_factory=list)
    candidate_zip_hash: str | None = None


class DisclosureReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["rig.review_projection.disclosure_receipt.v1"] = "rig.review_projection.disclosure_receipt.v1"
    projection_id: str
    mode: ProjectionMode
    created_at: str
    source_root_fingerprint: str
    branch: str
    head_sha: str
    public_baseline_status: str
    policy_version: str
    input_file_count: int
    classification_counts: dict[str, int]
    included_path_hashes: list[str]
    excluded_path_hashes: dict[str, str] = Field(description="Hash to reason")
    applied_rules: list[str]
    crosswalk_hash: str
    candidate_zip_path: str | None = None
    candidate_zip_sha256: str | None = None
    residual_scan_result: str
    output_status: Literal["candidate_generated", "refused", "classification_incomplete"]
    
    human_export_approval_required: Literal[True] = True
    legal_safety_not_determined: Literal[True] = True
    patent_safety_not_determined: Literal[True] = True
    confidential_holdback_exported: Literal[False] = False
    raw_source_content_in_receipt: Literal[False] = False
    raw_source_content_in_manifest: Literal[False] = False
