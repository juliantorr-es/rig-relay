from __future__ import annotations

import hashlib
import json
from typing import Literal

import jsonschema
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

# ---- Provider policy enumerations ------------------------------------

EndpointFamily = Literal["responses", "chat_completions", "unknown_refused"]

ProviderControlMode = Literal[
    "default_api_controls",
    "modified_abuse_monitoring_verified",
    "zero_data_retention_verified",
    "unclassified_refused",
]

ApplicationStateClassification = Literal[
    "retention_present_or_possible",
    "no_application_state_claim_unverified",
    "application_state_use_refused",
    "unclassified_refused",
]

PromptCacheRetentionClassification = Literal[
    "cache_retention_unverified",
    "cache_retention_present_or_possible",
    "cache_use_refused",
    "cache_retention_verified",
]

ProviderCapability = Literal[
    "plain_text_request_only",
    "hosted_container_refused",
    "remote_mcp_refused",
    "file_image_input_refused",
    "background_mode_refused",
    "stateful_conversation_refused",
    "thread_or_assistant_refused",
    "vector_store_or_file_store_refused",
    "web_search_or_external_tool_refused",
    "unknown_capability_refused",
]

PERMITTED_CAPABILITIES: frozenset[ProviderCapability] = frozenset({
    "plain_text_request_only"
})

REFUSED_CAPABILITIES: frozenset[ProviderCapability] = frozenset({
    "hosted_container_refused",
    "remote_mcp_refused",
    "file_image_input_refused",
    "background_mode_refused",
    "stateful_conversation_refused",
    "thread_or_assistant_refused",
    "vector_store_or_file_store_refused",
    "web_search_or_external_tool_refused",
    "unknown_capability_refused",
})

ProviderContextItemClassification = Literal[
    "mission_scoped_source_candidate",
    "credential_or_secret_refused",
    "private_authentication_material_refused",
    "patent_or_counsel_material_refused",
    "legal_strategy_material_refused",
    "confidential_audit_artifact_refused",
    "confidential_sink_descendant_refused",
    "local_crosswalk_refused",
    "provider_policy_evidence_body_refused",
    "encrypted_snapshot_refused",
    "unrelated_repository_content_refused",
    "unclassified_path_refused",
]

EXCLUDED_ITEM_CLASSIFICATIONS: frozenset[ProviderContextItemClassification] = (
    frozenset({
        "credential_or_secret_refused",
        "private_authentication_material_refused",
        "patent_or_counsel_material_refused",
        "legal_strategy_material_refused",
        "confidential_audit_artifact_refused",
        "confidential_sink_descendant_refused",
        "local_crosswalk_refused",
        "provider_policy_evidence_body_refused",
        "encrypted_snapshot_refused",
        "unrelated_repository_content_refused",
        "unclassified_path_refused",
    })
)

AdmissionOutcome = Literal[
    "admitted_for_future_transport_layer",
    "refused_campaign_provider_context_disabled",
    "refused_mode_not_approved",
    "refused_mission_scope_expansion",
    "refused_absolute_exclusion_intersection",
    "refused_endpoint_or_capability",
    "refused_unverified_provider_control_claim",
    "halt_campaign_security_or_confidentiality_boundary",
]


# ---- Context item descriptor -----------------------------------------


class ProviderContextItemDescriptor(BaseModel):
    """A content-light classified context descriptor.

    Carries classification metadata only.  Never raw source, prompts,
    credentials, secrets, crosswalks, or evidence bodies.
    """

    model_config = ConfigDict(extra="forbid")

    normalized_identity: str = Field(min_length=1)
    context_classification: ProviderContextItemClassification
    identity_digest: str = Field(min_length=1)


# ---- Provider disclosure policy attestation --------------------------


class ProviderDisclosurePolicyAttestation(BaseModel):
    """Fixture-safe provider disclosure attestation.

    Encodes the provider-control policy for a single mission/admission
    boundary.  This is a narrower execution attestation, not a competing
    campaign-level authority.
    """

    model_config = ConfigDict(extra="forbid")

    attestation_identity: str = Field(min_length=1)
    campaign_approved_provider_mode: Literal[
        "hosted_confidential_full_source_user_approved",
        "hosted_confidential_minimized_user_approved",
        "provider_context_refused",
    ]
    provider_family_identity: str = Field(min_length=1)
    provider_model_identity: str | None = None
    reason_model_identity_unavailable: str | None = None
    endpoint_family: EndpointFamily
    provider_control_mode: ProviderControlMode
    campaign_scope_digest: str = Field(min_length=1)
    human_approval_marker: Literal[True]
    mission_scope_enforcement_marker: Literal[True]
    full_source_approved_marker: bool
    minimized_source_approved_marker: bool
    zero_data_retention_verified_marker: bool
    modified_abuse_monitoring_verified_marker: bool
    abuse_monitoring_retention_classification: str = Field(min_length=1)
    application_state_classification: ApplicationStateClassification
    prompt_cache_retention_classification: PromptCacheRetentionClassification
    permitted_capabilities: list[ProviderCapability]
    refused_capabilities: list[ProviderCapability]
    attestation_source_class: str = Field(min_length=1)
    no_real_provider_request_in_this_slice_marker: Literal[True]
    actual_provider_request_performed: Literal[False]
    actual_external_transmission_performed: Literal[False]

    @model_validator(mode="after")
    def check_control_mode(self) -> ProviderDisclosurePolicyAttestation:
        pc = self.provider_control_mode
        if pc == "zero_data_retention_verified":
            if self.zero_data_retention_verified_marker is not True:
                raise ValueError(
                    "zero_data_retention_verified requires "
                    "zero_data_retention_verified_marker == true"
                )
        elif pc == "modified_abuse_monitoring_verified":
            if self.modified_abuse_monitoring_verified_marker is not True:
                raise ValueError(
                    "modified_abuse_monitoring_verified requires "
                    "modified_abuse_monitoring_verified_marker == true"
                )
        elif pc == "default_api_controls":
            if self.zero_data_retention_verified_marker is True:
                raise ValueError("default_api_controls must not claim ZDR verified")
            if self.modified_abuse_monitoring_verified_marker is True:
                raise ValueError("default_api_controls must not claim MAM verified")
        elif pc == "unclassified_refused":
            pass  # valid only as a terminal classification
        return self

    @model_validator(mode="after")
    def check_approval_markers(self) -> ProviderDisclosurePolicyAttestation:
        mode = self.campaign_approved_provider_mode
        if mode == "hosted_confidential_full_source_user_approved":
            if self.full_source_approved_marker is not True:
                raise ValueError(
                    "full-source mode requires full_source_approved_marker == true"
                )
        elif mode == "hosted_confidential_minimized_user_approved":
            if self.minimized_source_approved_marker is not True:
                raise ValueError(
                    "minimized-source mode requires "
                    "minimized_source_approved_marker == true"
                )
        elif mode == "provider_context_refused":
            if self.full_source_approved_marker is True:
                raise ValueError(
                    "refused mode must not have full_source_approved_marker == true"
                )
            if self.minimized_source_approved_marker is True:
                raise ValueError(
                    "refused mode must not have minimized_source_approved_marker == true"
                )
        return self

    @model_validator(mode="after")
    def check_required_identity(self) -> ProviderDisclosurePolicyAttestation:
        if (
            not self.provider_model_identity
            and not self.reason_model_identity_unavailable
        ):
            raise ValueError(
                "must provide provider_model_identity or "
                "reason_model_identity_unavailable"
            )
        return self


# ---- Provider context admission request -------------------------------


class ProviderContextAdmissionRequest(BaseModel):
    """Fixture-safe provider context admission request.

    Carries classified context descriptors only.  Never raw source,
    prompts, credentials, secrets, crosswalks, or evidence bodies.
    """

    model_config = ConfigDict(extra="forbid")

    attestation_identity: str = Field(min_length=1)
    campaign_identity: str = Field(min_length=1)
    mission_identity: str = Field(min_length=1)
    requested_provider_context_mode: Literal[
        "hosted_confidential_full_source_user_approved",
        "hosted_confidential_minimized_user_approved",
    ]
    requested_context_items: list[ProviderContextItemDescriptor] = Field(
        default_factory=list
    )
    requested_capabilities: list[ProviderCapability]
    requested_endpoint_family: EndpointFamily
    minimum_necessary_purpose_label: str = Field(min_length=1)
    human_approved_campaign_identity_reference: str = Field(min_length=1)


# ---- Provider context admission decision ------------------------------


class ProviderContextAdmissionDecision(BaseModel):
    """Content-light provider context admission decision.

    Contains only decision metadata.  Never raw source, prompts,
    provider context bodies, secrets, crosswalks, or evidence.
    """

    model_config = ConfigDict(extra="forbid")

    decision_identity: str = Field(min_length=1)
    campaign_identity: str = Field(min_length=1)
    mission_identity: str = Field(min_length=1)
    admission_outcome: AdmissionOutcome
    refusal_category: str | None = None
    refusal_reason: str | None = None
    approved_mode: str = Field(min_length=1)
    attested_provider_control_mode: ProviderControlMode
    requested_scope_digest: str = Field(min_length=1)
    admitted_scope_digest: str | None = None
    endpoint_family: EndpointFamily
    capability_classifications: list[ProviderCapability]
    provider_request_performed: Literal[False] = False
    external_transmission_performed: Literal[False] = False
    source_body_in_decision: Literal[False] = False
    secret_body_in_decision: Literal[False] = False
    actual_retention_behavior_observed: Literal[False] = False
    actual_zdr_operation_observed: Literal[False] = False
    actual_prompt_cache_behavior_observed: Literal[False] = False
    human_transport_activation_still_required: Literal[True] = True


# ---- Schema generation for provider-policy surface -------------------


class _ProviderPolicySchemaRoot(BaseModel):
    """Container that pulls all provider-policy types into $defs."""

    model_config = ConfigDict(extra="forbid")
    attestation: ProviderDisclosurePolicyAttestation
    item: ProviderContextItemDescriptor
    request: ProviderContextAdmissionRequest
    decision: ProviderContextAdmissionDecision


_PROVIDER_POLICY_ADAPTER: TypeAdapter[_ProviderPolicySchemaRoot] = TypeAdapter(
    _ProviderPolicySchemaRoot
)

_PROVIDER_REQUEST_ADAPTER: TypeAdapter[ProviderContextAdmissionRequest] = TypeAdapter(
    ProviderContextAdmissionRequest
)

_PROVIDER_DECISION_ADAPTER: TypeAdapter[ProviderContextAdmissionDecision] = TypeAdapter(
    ProviderContextAdmissionDecision
)


def generate_provider_policy_schema() -> dict:
    """Generate and self-validate the provider-policy JSON Schema.

    The schema exposes all four provider-policy types in $defs via a
    container root model.
    """
    schema = _PROVIDER_POLICY_ADAPTER.json_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    return schema


def compute_provider_policy_schema_identity() -> str:
    """Return SHA-256 hex digest of the deterministic schema JSON."""
    schema = generate_provider_policy_schema()
    return hashlib.sha256(
        json.dumps(schema, sort_keys=True, indent=2).encode("utf-8")
    ).hexdigest()
