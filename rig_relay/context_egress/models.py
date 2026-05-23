from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ProviderMode(StrEnum):
    PUBLIC_CONTEXT_ONLY = "public_context_only"
    HOSTED_PROVIDER_STANDARD_CONFIDENTIAL_MINIMIZED = (
        "hosted_provider_standard_confidential_minimized"
    )
    HOSTED_PROVIDER_ZDR_CONFIDENTIAL_MINIMIZED = (
        "hosted_provider_zdr_confidential_minimized"
    )
    PROVIDER_UNCLASSIFIED_REFUSED = "provider_unclassified_refused"


class ContextClassification(StrEnum):
    PUBLIC_VERIFIED_CONTEXT = "public_verified_context"
    CONFIDENTIAL_MINIMIZABLE_CONTEXT = "confidential_minimizable_context"
    CONFIDENTIAL_MINIMIZED_PROVIDER_CONTEXT = "confidential_minimized_provider_context"
    CONFIDENTIAL_NONTRANSMITTABLE_CONTEXT = "confidential_nontransmittable_context"
    SECRET_OR_CREDENTIAL_REFUSED = "secret_or_credential_refused"
    COUNSEL_OR_IP_AUDIT_REFUSED = "counsel_or_ip_audit_refused"
    LOCAL_CROSSWALK_OR_POLICY_MAP_REFUSED = "local_crosswalk_or_policy_map_refused"
    GENERATED_SENSITIVE_ARTIFACT_REFUSED = "generated_sensitive_artifact_refused"
    UNCLASSIFIED_REFUSED = "unclassified_refused"


class RetentionMode(StrEnum):
    STANDARD = "standard"
    MODIFIED_ABUSE_MONITORING = "modified_abuse_monitoring"
    ZERO_DATA_RETENTION = "zero_data_retention"
    UNKNOWN = "unknown"


class ContextSectionKind(StrEnum):
    STABLE_APPROVED_PREFIX = "stable_approved_prefix"
    DYNAMIC_MINIMIZED_SUFFIX = "dynamic_minimized_suffix"


class CacheReadinessStatus(StrEnum):
    STABLE_PREFIX_LAYOUT_PROVEN = "stable_prefix_layout_proven"
    STABLE_PREFIX_UNSTABLE = "stable_prefix_unstable"
    SIZE_MEASUREMENT_ONLY_TOKEN_ELIGIBILITY_UNVERIFIED = (
        "size_measurement_only_token_eligibility_unverified"
    )
    REFUSED = "refused"


class ProviderPolicyAttestation(BaseModel):
    schema_version: str = "v1"
    provider_family: str
    endpoint_family: str
    model_family_label: str | None = None
    retention_mode: RetentionMode
    training_default_classification: str = "unknown"
    store_false_required: bool = True
    forbidden_stateful_features: list[str] = Field(default_factory=list)
    forbidden_remote_tools: list[str] = Field(default_factory=list)
    human_approved_confidential_minimization: bool
    approval_timestamp: datetime
    approval_scope: str
    attestation_source_class: str
    expiry_or_review_needed_marker: datetime | None = None


class BoundedMissionManifest(BaseModel):
    schema_version: str = "v1"
    mission_id: str
    provider_mode: ProviderMode
    approved_input_root: str
    approved_fixture_root: str | None = None
    approved_file_list: list[str] = Field(default_factory=list)
    approved_input_classifications: list[ContextClassification] = Field(
        default_factory=list
    )
    forbidden_classifications: list[ContextClassification] = Field(default_factory=list)
    minimum_necessary_purpose_label: str
    human_approval_marker: bool
    max_context_block_count: int | None = None
    max_context_size_bytes: int | None = None
    output_sink_root: str
    stop_after_candidate_generation: bool = True
    no_transmission_marker: bool = True


class EgressCandidateSection(BaseModel):
    section_kind: ContextSectionKind
    opaque_identity: str
    classification: ContextClassification = (
        ContextClassification.CONFIDENTIAL_MINIMIZED_PROVIDER_CONTEXT
    )
    minimized_content: str


class EgressCandidate(BaseModel):
    sections: list[EgressCandidateSection] = Field(default_factory=list)
    provider_mode: ProviderMode
    generic_purpose_metadata: str
    not_transmitted: bool = True
    output_remains_confidential: bool = True
    human_provider_submission_approval_required: bool = True


class EgressCrosswalk(BaseModel):
    original_to_opaque_mapping: dict[str, str] = Field(default_factory=dict)
    local_only_warning: str = "LOCAL ONLY. DO NOT EXPORT."
    export_prohibition: bool = True
    egress_candidate_hash: str | None = None


class ContextEfficiencyEvidence(BaseModel):
    schema_version: str = "v1"
    stable_prefix_sha256: str | None = None
    dynamic_suffix_sha256: str | None = None
    stable_prefix_reusable: bool = False
    stable_prefix_change_reasons: list[str] = Field(default_factory=list)
    projection_input_character_count: int = 0
    projection_output_character_count: int = 0
    projection_input_utf8_byte_count: int = 0
    projection_output_utf8_byte_count: int = 0
    projection_character_reduction_ratio: float = 0.0
    projection_utf8_byte_reduction_ratio: float = 0.0
    approved_block_count: int = 0
    refused_block_count: int = 0
    crosswalk_sent_to_provider: bool = False
    receipt_sent_to_provider: bool = False
    cache_readiness_status: CacheReadinessStatus = CacheReadinessStatus.REFUSED
    actual_provider_token_metrics_collected: bool = False
    actual_provider_cost_savings_claimed: bool = False


class EgressReceipt(BaseModel):
    schema_version: str = "v1"
    egress_decision_id: str
    mission_id: str
    provider_mode: ProviderMode
    provider_family: str
    endpoint_family_classification: str
    retention_mode_attested: RetentionMode
    policy_version: str
    source_scope_hash: str
    classification_counts: dict[ContextClassification, int] = Field(
        default_factory=dict
    )
    excluded_material_counts: dict[ContextClassification, int] = Field(
        default_factory=dict
    )
    egress_candidate_hash: str | None = None
    crosswalk_artifact_hash: str
    residual_scan_status: str
    output_status: str
    refusal_reason_codes: list[str] = Field(default_factory=list)
    hosted_provider_processing_accepted_by_user: bool = True
    not_transmitted: bool = True
    output_remains_confidential: bool = True
    declassified: bool = False
    secrets_exported: bool = False
    counsel_material_exported: bool = False
    audit_material_exported: bool = False
    local_crosswalk_exported: bool = False
    raw_source_in_receipt: bool = False
    raw_source_in_provider_candidate: bool = False
    legal_safety_not_determined: bool = True
    patent_safety_not_determined: bool = True
    fixture_only_nonpublic_input_enforced: bool = True
    live_confidential_repository_input_processed: bool = False
    actual_provider_token_metrics_collected: bool = False
    actual_cached_token_metrics_collected: bool = False
    actual_provider_cost_savings_claimed: bool = False
    provider_cache_eligibility_verified: bool = False
    stable_prefix_layout_proven: bool = False
